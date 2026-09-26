"""Bounded English generation; source facts and failure states belong to the app."""
from __future__ import annotations

import asyncio
import json
import logging
import uuid

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from ..llm.failures import failure_code
from ..llm.spark_client import llm_complete, parse_json
from ..prompt_templates import invoke_learning_prompt
from .subtitle_service import source_lines

log = logging.getLogger(__name__)
GENERATION_TIMEOUT = 135
RETRYABLE = {"rate_limit", "connection", "provider_error", "empty_response", "incomplete_response", "truncated", "invalid_structure", "source_mismatch"}
ERRORS = {
    "timeout": (504, "这次生成等待超时，请稍后重试。"),
    "authentication": (503, "英语生成服务连接失败，请联系管理员检查服务配置。"),
    "quota": (503, "英语生成服务额度暂时不足，请稍后再试或联系管理员。"),
    "rate_limit": (503, "英语生成服务暂时繁忙，请稍后重试。"),
    "connection": (503, "暂时无法连接英语生成服务，请稍后重试。"),
    "provider_error": (503, "英语生成服务暂时出错，请稍后重试。"),
    "truncated": (502, "这次内容没有生成完整，请减少本次单词或字幕后重试。"),
    "empty_response": (502, "这次没有收到生成内容，请重试。"),
    "incomplete_response": (502, "这次生成中断了，请重试。"),
    "content_filter": (502, "这次内容未能生成，请调整场景描述后重试。"),
    "invalid_structure": (502, "这次内容未通过完整性检查，请重试。"),
    "source_mismatch": (502, "生成的原句与字幕不一致，已阻止保存。请选取较短的完整片段重试。"),
    "generation_failed": (502, "这次场景生成失败，请重试。"),
}


class GenerationError(Exception):
    def __init__(self, code: str, request_id: str):
        self.code = code if code in ERRORS else "generation_failed"
        self.request_id = request_id
        self.status, message = ERRORS[self.code]
        self.message = f"{message}（查询编号：{request_id}）"
        super().__init__(self.message)


class SourceMismatch(ValueError):
    pass


class TextModel(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)


class Line(TextModel):
    speaker: str = Field(default="", max_length=80)
    text: str = Field(min_length=1, max_length=1000)
    translation: str = Field(min_length=1, max_length=1000)
    timestamp: str = Field(default="", max_length=60)


class Word(TextModel):
    word: str = Field(min_length=1, max_length=100)
    meaning: str = Field(min_length=1, max_length=500)
    usage: str = Field(min_length=1, max_length=1500)
    contrast: str = Field(default="", max_length=1500)


class Check(TextModel):
    stem: str = Field(min_length=1, max_length=800)
    options: list[str] = Field(min_length=4, max_length=4)
    answer: str = Field(pattern="^[ABCD]$")
    explanation: str = Field(min_length=1, max_length=2000)

    @field_validator("answer", mode="before")
    @classmethod
    def answer_letter(cls, value):
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("options")
    @classmethod
    def distinct_options(cls, values):
        values = [v.strip() for v in values]
        if any(not v or len(v) > 500 for v in values) or len({v.casefold() for v in values}) != 4:
            raise ValueError("four distinct nonempty options required")
        return values


class SceneCore(TextModel):
    title: str = Field(min_length=1, max_length=200)
    lines: list[Line] = Field(min_length=1, max_length=30)
    vocabulary: list[Word] = Field(min_length=1, max_length=25)
    notes: str = Field(min_length=1, max_length=20000)


def status(question: dict | None) -> dict:
    return {"status": "completed" if question else "partial",
            "question_status": "ready" if question else "unavailable",
            "message": "" if question else "对话和词汇笔记已保存，可以先学习；练习暂未就绪，可单独补生成。"}


def _read_scene(raw: str, values: dict) -> dict:
    data = parse_json(raw)
    result = SceneCore.model_validate(data).model_dump()
    # No verified mnemonic source exists in this short scene workflow.
    # Ignore the model field rather than presenting invented pronunciation or etymology.
    for word in result["vocabulary"]:
        word["memory"] = ""
    subtitles = values.get("subtitles", "")
    if subtitles.strip():
        try:
            result["lines"] = source_lines(result["lines"], subtitles)
            for line in result["lines"]:
                line["speaker"] = ""  # Any supplied speaker label stays in the original text.
        except ValueError:
            raise SourceMismatch() from None
    else:
        for line in result["lines"]:
            line["timestamp"] = ""
    result["provenance"] = "用户字幕整理；释义与练习为 AI 补充" if subtitles.strip() else "原创教学场景，非真实影视台词"
    try:
        question = Check.model_validate(data.get("question")).model_dump()
    except (ValidationError, TypeError, ValueError):
        question = None
    return {**result, "question": question, "generation": status(question), "source_text": subtitles,
            "request": {key: values[key] for key in ("words", "scene", "goal", "level")}, "mode": "live"}


async def _run(capability: str, values: dict, read, max_tokens: int) -> dict:
    call = invoke_learning_prompt(capability, **values)
    identifier = uuid.uuid4().hex[:12]

    async def attempts():
        prompt = call.prompt
        for attempt in range(2):
            code = "generation_failed"
            try:
                raw = await llm_complete(prompt, system=call.system, json_object=True, max_tokens=max_tokens,
                                         reasoning_mode="disabled", allow_mock_fallback=False, allow_model_fallback=False)
                return read(raw)
            except SourceMismatch:
                code = "source_mismatch"
            except (ValidationError, ValueError, TypeError):
                code = "invalid_structure"
            except (RuntimeError, TimeoutError) as exc:
                code = failure_code(exc)
            # Only classified metadata: no credentials, input subtitles, response bodies or exception strings.
            log.warning("english_generation request=%s capability=%s attempt=%s code=%s", identifier, capability, attempt + 1, code)
            if attempt or code not in RETRYABLE:
                raise GenerationError(code, identifier)
            if code in {"invalid_structure", "truncated", "source_mismatch"}:
                prompt = call.prompt + "\n\n上次结果未通过检查。请重新输出完整、精简的 JSON，逐项核对字段类型、原句来源及四个不同选项；不要在 JSON 外附解释。"
            else:
                await asyncio.sleep(0.6)
        raise GenerationError("generation_failed", identifier)

    try:
        return await asyncio.wait_for(attempts(), timeout=GENERATION_TIMEOUT)
    except TimeoutError:
        # A cancelled transport may still be completing: do not launch a second overlapping paid request.
        log.warning("english_generation request=%s capability=%s code=timeout", identifier, capability)
        raise GenerationError("timeout", identifier) from None


async def generate_scene(values: dict) -> dict:
    return await _run("english.scene", values, lambda raw: _read_scene(raw, values), 6000)


async def generate_question(scene: dict) -> dict:
    context = json.dumps({key: scene[key] for key in ("title", "lines", "vocabulary")}, ensure_ascii=False)
    return await _run("english.question", {"context": context},
                      lambda raw: Check.model_validate(parse_json(raw)).model_dump(), 1800)


def archive(scene: dict) -> dict:
    parts = [f"# {scene['title']}", scene["provenance"], "## 场景原句"]
    parts.extend(f"{line['speaker']} {line['timestamp']}\n\n{line['text']}\n\n{line['translation']}" for line in scene["lines"])
    parts.append("## 词汇与搭配")
    parts.extend(f"### {word['word']}\n\n{word['meaning']}\n\n{word['usage']}\n\n{word['contrast']}\n\n{word['memory']}" for word in scene["vocabulary"])
    parts.append(scene["notes"])
    if not scene.get("question"):
        parts.append("## 练习状态\n\n练习暂未生成；对话与笔记已保留。")
    return {"template": "english_scene", "markdown": "\n\n".join(parts), "english_scene": scene}

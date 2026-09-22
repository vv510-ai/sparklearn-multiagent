"""Explicit learning actions using the shared model gateway and Markdown prompts."""
from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, ValidationError

from ..auth import require_current_user_id
from ..config import is_demo
from ..llm.spark_client import llm_complete, parse_json
from ..models.db import session
from ..models.entities import Resource
from ..prompt_templates import invoke_learning_prompt
from ..services.conversation_service import get_session_messages
from ..services.model_preferences import resolve
from ..services.learning_scope import scoped_endpoint
from ..services.notebook_service import ensure_notebook_owner
from ..services.study_research import research
from ..services.subtitle_service import source_lines

router = APIRouter(prefix="/api/learning", tags=["learning"])


class SceneRequest(BaseModel):
    words: str = Field(min_length=1, max_length=400)
    scene: str = Field(default="日常交流", max_length=300)
    level: str = Field(default="中等", max_length=40)
    goal: str = Field(default="影视理解与日常交流", max_length=80)
    subtitles: str = Field(default="", max_length=16000)
    notebook_id: str = Field(default="", max_length=64)


class Line(BaseModel):
    speaker: str = Field(default="", max_length=80)
    text: str = Field(min_length=1, max_length=1000)
    translation: str = Field(default="", max_length=1000)
    timestamp: str = Field(default="", max_length=60)


class Word(BaseModel):
    word: str = Field(max_length=100)
    meaning: str = Field(max_length=500)
    usage: str = Field(default="", max_length=1500)
    memory: str = Field(default="", max_length=800)
    contrast: str = Field(default="", max_length=1500)


class Check(BaseModel):
    stem: str = Field(min_length=1, max_length=800)
    options: list[str] = Field(min_length=4, max_length=4)
    answer: str = Field(pattern="^[ABCD]$")
    explanation: str = Field(max_length=2000)


class Scene(BaseModel):
    title: str = Field(max_length=200)
    provenance: str = Field(max_length=200)
    lines: list[Line] = Field(min_length=1, max_length=30)
    vocabulary: list[Word] = Field(min_length=1, max_length=25)
    notes: str = Field(max_length=20000)
    question: Check


class ResearchRequest(BaseModel):
    question: str = Field(min_length=3, max_length=600)
    notebook_id: str = Field(default="", max_length=64)


class FollowupRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=64)
    notebook_id: str = Field(default="", max_length=64)


def _scope(notebook: str) -> str:
    user = require_current_user_id()
    if notebook:
        ensure_notebook_owner(user, notebook)
    return user


def _persist(user: str, notebook: str, title: str, payload: dict) -> str:
    identifier = "r_" + uuid.uuid4().hex
    with session() as db:
        db.add(Resource(id=identifier, user_id=user, kind="doc", title=title,
                        payload={**payload, "notebook_id": notebook}, citations=[], safety={}))
        db.commit()
    return identifier


@router.post("/english/scene")
@scoped_endpoint
async def english_scene(req: SceneRequest):
    body = req
    user = _scope(body.notebook_id)
    call = invoke_learning_prompt("english.scene", **body.model_dump(exclude={"notebook_id"}))
    if is_demo() and not resolve(call.prompt):
        raise HTTPException(503, "英语场景学习需要可用模型，请在模型设置中连接 API")
    try:
        raw = await llm_complete(call.prompt, system=call.system, json_object=True, max_tokens=6000,
                                 allow_mock_fallback=False, allow_model_fallback=False)
        result = Scene.model_validate(parse_json(raw)).model_dump()
    except (RuntimeError, ValueError, ValidationError, TypeError):
        raise HTTPException(502, "英语场景未生成完整，请检查模型设置后重试") from None
    # Provenance is a product fact, never delegated to a generative model.
    result["provenance"] = "用户字幕整理；释义与练习为 AI 补充" if body.subtitles.strip() else "原创教学场景，非真实影视台词"
    if body.subtitles.strip():
        try:
            result["lines"] = source_lines(result["lines"], body.subtitles)
        except ValueError:
            raise HTTPException(502, "生成的台词与原字幕不一致，已阻止保存，请重试")
    if not body.subtitles.strip():
        for line in result["lines"]:
            line["timestamp"] = ""
    result["source_text"] = body.subtitles
    result["mode"] = "live"
    archive = [f"# {result['title']}", result["provenance"], "## 场景原句"]
    archive.extend(f"{line['speaker']} {line['timestamp']}\n\n{line['text']}\n\n{line['translation']}" for line in result["lines"])
    archive.append("## 词汇与搭配")
    archive.extend(f"### {word['word']}\n\n{word['meaning']}\n\n{word['usage']}\n\n{word['contrast']}\n\n{word['memory']}" for word in result["vocabulary"])
    archive.append(result["notes"])
    result["resource_id"] = _persist(user, body.notebook_id, result["title"], {
        "template": "english_scene", "markdown": "\n\n".join(archive), "english_scene": result})
    return result


@router.post("/research")
@scoped_endpoint
async def deep_research(req: ResearchRequest):
    body = req
    user = _scope(body.notebook_id)
    offline = is_demo() and not resolve("CAPABILITY=research.plan\n")
    try:
        result = await asyncio.wait_for(research(body.question, offline=offline), timeout=170)
    except asyncio.TimeoutError:
        raise HTTPException(504, "研究超时，请缩小问题范围后重试") from None
    result["question"] = body.question
    archive = result["markdown"] + "\n\n## 可核对的来源\n\n" + "\n\n".join(
        f"[{s['id']}] [{s['title'].replace('[', '').replace(']', '')}]({s['url']})\n\n{s.get('kind', '')} · {s.get('published_at') or '日期未提供'}\n\n{s['excerpt'] or '仅有题录，未取得摘要'}"
        for s in result["sources"])
    archive += "\n\n## 本次研究范围\n\n" + "\n".join("* " + item for item in result["limitations"])
    result["resource_id"] = _persist(user, body.notebook_id, "研究 · " + body.question[:100],
                                    {"template": "research", "markdown": archive, "research": result})
    return result


@router.post("/followups")
@scoped_endpoint
async def followups(req: FollowupRequest):
    body = req
    user = _scope(body.notebook_id)
    if body.notebook_id:
        notebook = ensure_notebook_owner(user, body.notebook_id)
        if notebook.session_id != body.session_id:
            raise HTTPException(409, "当前对话已切换，请使用当前书本的最新对话")
    history = get_session_messages(user, body.session_id)
    # Wait for the pending turn instead of pairing its question with an older answer.
    if not history or history[-1].get("role") != "assistant":
        return {"suggestions": [], "mode": "empty"}
    answer = history[-1].get("content", "")
    question = next((m.get("content", "") for m in reversed(history[:-1]) if m.get("role") == "user"), "")
    if not answer or not question:
        return {"suggestions": [], "mode": "empty"}
    call = invoke_learning_prompt("tutor.next_step", question=question[:2000], answer=answer[:7000])
    if is_demo() and not resolve(call.prompt):
        return {"suggestions": ["请用一个最小例子说明刚才的概念", "刚才的结论有什么适用条件？", "给我一道关于刚才内容的单选题"], "mode": "offline"}
    try:
        raw = await llm_complete(call.prompt, system=call.system, json_object=True, max_tokens=600,
                                 reasoning_mode="disabled", allow_mock_fallback=False, allow_model_fallback=False)
        data = parse_json(raw)
        items = data.get("suggestions", [])
        suggestions = list(dict.fromkeys(s.strip() for s in items if isinstance(s, str) and 3 <= len(s.strip()) <= 80))[:3]
        return {"suggestions": suggestions, "mode": "live"}
    except (RuntimeError, ValueError, TypeError, AttributeError):
        return {"suggestions": [], "mode": "unavailable"}

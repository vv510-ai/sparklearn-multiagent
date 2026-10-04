"""Bounded excerpt explanation through the existing model gateway; no answer keys."""
import asyncio
import logging

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from ..config import is_demo
from ..llm.spark_client import llm_complete, parse_json
from ..prompt_templates import invoke_learning_prompt
from . import cet6_learning as learning
from .cet6_exams import _pack


class Clause(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    quote: str = Field(min_length=1, max_length=1500)
    role: str = Field(min_length=1, max_length=100)
    explanation: str = Field(min_length=1, max_length=500)


class SentenceExplanation(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    main_clause: str = Field(min_length=1, max_length=1500)
    clauses: list[Clause] = Field(min_length=1, max_length=8)
    translation: str = Field(min_length=1, max_length=1500)
    connection: str = Field(min_length=1, max_length=800)
    check_question: str = Field(min_length=1, max_length=400)
    check_answer: str = Field(min_length=1, max_length=800)


async def explain(user, notebook, paper_id, kind, req):
    learning.check(user, notebook)
    paper, block = _pack(paper_id, kind)
    if not kind.startswith("reading") or req.question not in {q["number"] for q in block["questions"]}:
        raise HTTPException(422, "请选择阅读板块中的题号。")
    if req.version != paper["version"]:
        raise HTTPException(409, "原卷版本已变化，请重新打开。")
    normalize = lambda value: " ".join(value.split())
    if normalize(req.sentence) not in normalize(req.paragraph):
        raise HTTPException(422, "请选择当前段落中的原句，不要改写原文。")
    if is_demo():
        raise HTTPException(503, "当前演示环境未启用 AI 拆句；查词、保存与复习仍可使用。")
    call = invoke_learning_prompt("english.exam_sentence", sentence=req.sentence, paragraph=req.paragraph)
    try:
        raw = await asyncio.wait_for(llm_complete(call.prompt, system=call.system, temperature=.2,
            json_mode=True, max_tokens=10000, allow_model_fallback=False, allow_mock_fallback=False), timeout=90)
        result = SentenceExplanation.model_validate(parse_json(raw))
        if any(normalize(c.quote) not in normalize(req.sentence) for c in result.clauses):
            raise ValueError("clause quote absent from selected sentence")
        return {"content": result.model_dump(), "note": "AI 句子讲解，请对照原文；理解自查不计入考试成绩。"}
    except Exception as exc:
        logging.getLogger(__name__).warning("Sentence explanation rejected: %s", type(exc).__name__)
        raise HTTPException(503, "本次拆句未完成或未通过原文检查，请重试。作答与生词记录不受影响。") from None

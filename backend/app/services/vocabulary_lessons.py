"""Skill-shaped vocabulary explanations, cached independently of recall state."""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
from functools import lru_cache
from pathlib import Path
from weakref import WeakValueDictionary

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError

from ..models.db import session
from ..models.entities import VocabularyLesson
from ..llm.spark_client import llm_complete, parse_json, is_demo
from ..prompt_templates import invoke_learning_prompt
from .english_learning import Check
from . import cet6_learning as learning

LESSON_VERSION = "word-lesson-v2"
_locks: WeakValueDictionary = WeakValueDictionary()


class Example(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    text: str = Field(min_length=5, max_length=500)
    translation: str = Field(min_length=2, max_length=500)
    note: str = Field(min_length=2, max_length=600)


class Lesson(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    focus: str = Field(min_length=2, max_length=150)
    explanation: str = Field(min_length=10, max_length=1500)
    usage: list[str] = Field(min_length=1, max_length=4)
    example: Example
    contrast: str = Field(min_length=5, max_length=800)
    memory: str = Field(min_length=5, max_length=600)
    check: Check


@lru_cache(maxsize=1)
def curated():
    return json.loads((Path(__file__).parents[1] / "data" / "cet6_word_lessons_v1.json").read_text(encoding="utf-8"))


def curated_words():
    return {e["word"].casefold() for e in curated()["entries"]}


def preferred_sense(entry):
    row = next((e for e in curated()["entries"] if e["word"].casefold() == entry["word"].casefold()), None)
    index = row["sense_index"] if row else 0
    return entry["senses"][min(index, len(entry["senses"]) - 1)]["id"] if entry["senses"] else ""


def _identity(item, sense_id):
    from .cet6_vocabulary import corpus, entry
    e = entry(item)
    sense = next((s for s in e["senses"] if s["id"] == sense_id), None)
    if not sense:
        raise HTTPException(404, "词义已变化，请重新打开词卡。")
    key = hashlib.sha256(f"{LESSON_VERSION}:{corpus()['version']}:{item}:{sense_id}".encode()).hexdigest()
    return key, e, sense


def _ready(entry, sense_id):
    row = next((e for e in curated()["entries"] if e["word"].casefold() == entry["word"].casefold()), None)
    if not row or preferred_sense(entry) != sense_id:
        return None
    payload = {k: v for k, v in row.items() if k not in {"word", "sense_index", "exam_occurrences", "sense_definition"}}
    result = Lesson.model_validate(payload).model_dump()
    return {**result, "status": "ready", "origin": "curated", "version": curated()["version"],
        "source_note": "词典基本义已核对；本站编写讲解，例句与应用题为自编。",
        "sources": [{"title": f"Merriam-Webster · {entry['word']}",
            "url": f"https://www.merriam-webster.com/dictionary/{entry['word']}",
            "supports": "基本词义与词性；例句、助记和应用题不是词典原文。", "checked_on": curated()["checked_on"]}],
        "exam_occurrences": row.get("exam_occurrences", [])}


def get(user, notebook, item, sense_id):
    learning.check(user, notebook)
    key, entry, _ = _identity(item, sense_id)
    ready = _ready(entry, sense_id)
    if ready:
        return ready
    with session() as db:
        row = db.get(VocabularyLesson, key)
        return copy.deepcopy(row.data) if row else {"status": "missing"}


async def generate(user, notebook, item, sense_id):
    existing = get(user, notebook, item, sense_id)
    if existing["status"] == "ready":
        return existing
    key, entry, sense = _identity(item, sense_id)
    lock = _locks.setdefault(key, asyncio.Lock())
    async with lock:
        existing = get(user, notebook, item, sense_id)
        if existing["status"] == "ready":
            return existing
        if is_demo():
            raise HTTPException(503, "当前演示环境未连接词汇讲解服务。可先学习已整理词条，或稍后重试。")
        # No learner notes or conversation enter this globally shared cache.
        call = invoke_learning_prompt("english.word_lesson", word=entry["word"], definition=sense["definition"])
        async def build_and_review():
            async def complete(invocation):
                raw = await llm_complete(invocation.prompt, system=invocation.system, json_object=True,
                    max_tokens=2300, reasoning_mode="disabled", allow_mock_fallback=False,
                    allow_model_fallback=False)
                return Lesson.model_validate(parse_json(raw)).model_dump()

            draft = await complete(call)
            review = invoke_learning_prompt("english.word_lesson_review", word=entry["word"],
                definition=sense["definition"], draft=json.dumps(draft, ensure_ascii=False))
            return await complete(review)

        try:
            lesson = await asyncio.wait_for(build_and_review(), timeout=110)
            if any(not u.strip() or len(u) > 600 for u in lesson["usage"]):
                raise ValueError("invalid usage")
        except asyncio.CancelledError:
            raise
        except Exception:
            raise HTTPException(503, "这次精讲暂未生成完整，释义与复习记录仍保留，请重试。") from None
        result = {**lesson, "status": "ready", "origin": "generated", "version": LESSON_VERSION,
            "source_note": "AI生成并自动复核的学习讲解，尚未人工校核；例句与练习为自编，助记不是真实词源。",
            "sources": [{"title": "ECDICT 社区词典", "url": entry["dictionary_url"],
                "supports": "本次输入的词义记录；不证明生成讲解已经逐项核验。"}], "exam_occurrences": []}
        with session() as db:
            db.add(VocabularyLesson(id=key, data=result))
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                result = copy.deepcopy(db.get(VocabularyLesson, key).data)
        return result

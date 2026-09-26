"""Explicit learning actions using the shared model gateway and Markdown prompts."""
from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

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
from ..services import english_learning as english

router = APIRouter(prefix="/api/learning", tags=["learning"])


class SceneRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    words: str = Field(min_length=1, max_length=400)
    scene: str = Field(default="日常交流", max_length=300)
    level: str = Field(default="中等", max_length=40)
    goal: str = Field(default="影视理解与日常交流", max_length=80)
    subtitles: str = Field(default="", max_length=16000)
    notebook_id: str = Field(default="", max_length=64)


class SceneQuestionRequest(BaseModel):
    resource_id: str = Field(min_length=1, max_length=64)
    notebook_id: str = Field(default="", max_length=64)


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
    user = _scope(req.notebook_id)
    _english_available()
    try:
        result = await english.generate_scene(req.model_dump(exclude={"notebook_id"}))
    except english.GenerationError as exc:
        raise _english_error(exc) from None
    result["resource_id"] = _persist(user, req.notebook_id, result["title"], english.archive(result))
    return result


def _english_available():
    if is_demo() and not resolve("CAPABILITY=english.scene\n"):
        raise HTTPException(503, "英语场景生成需要可用模型。请先使用已准备好的场景课程，或联系管理员。")


def _english_error(exc: english.GenerationError) -> HTTPException:
    return HTTPException(exc.status, exc.message, headers={"X-English-Error": exc.code, "X-Request-ID": exc.request_id})


def _owned_scene(db, user: str, resource_id: str, notebook: str, *, lock=False):
    row = db.get(Resource, resource_id, with_for_update=lock)
    payload = row.payload if row else {}
    if (not row or row.user_id != user or (payload or {}).get("template") != "english_scene"
            or str(payload.get("notebook_id") or "") != notebook or not payload.get("english_scene")):
        raise HTTPException(404, "当前课程中没有这份英语场景")
    return row


@router.get("/english/scene/latest")
@scoped_endpoint
async def latest_english_scene(notebook_id: str = ""):
    user = _scope(notebook_id)
    with session() as db:
        row = (db.query(Resource).filter(Resource.user_id == user,
            Resource.payload["template"].as_string() == "english_scene",
            Resource.payload["notebook_id"].as_string() == notebook_id)
            .order_by(Resource.created_at.desc(), Resource.id.desc()).first())
        return {**english.with_sources(row.payload["english_scene"]), "resource_id": row.id} if row else None


@router.post("/english/scene/question")
@scoped_endpoint
async def english_scene_question(req: SceneQuestionRequest):
    user = _scope(req.notebook_id)
    with session() as db:
        row = _owned_scene(db, user, req.resource_id, req.notebook_id)
        scene = dict(row.payload["english_scene"])
    # Refreshes and duplicate clicks do not regenerate an already available exercise.
    if scene.get("question"):
        return {"question": scene["question"], "generation": english.status(scene["question"])}
    _english_available()
    try:
        question = await english.generate_question(scene)
    except english.GenerationError as exc:
        raise _english_error(exc) from None
    with session() as db:
        row = _owned_scene(db, user, req.resource_id, req.notebook_id, lock=True)
        current = dict(row.payload["english_scene"])
        question = current.get("question") or question
        current.update(question=question, generation=english.status(question))
        row.payload = {**row.payload, **english.archive(current)}
        db.commit()
    return {"question": question, "generation": english.status(question)}


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

"""资源 API:
POST /api/resources/generate —— 显式资源生成(SSE 全流水线,intent 固定 generate);
GET  /api/resources           —— 我的资源列表(支持 kind/kp 过滤);
GET  /api/resources/{rid}     —— 资源详情;
GET  /api/resources/video/task/{task_id} —— 小云雀视频任务状态轮询。"""
from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, HTTPException, Query

from ..agents import doc_agent
from ..agents.graph import run_with_events
from ..llm import multimodal_gateway
from ..models.db import session
from ..models.entities import Resource
from ..rag.ingest import validate_source_scope
from ..schemas.core import AudioRetryRequest, GenerateRequest
from ..services.conversation_service import get_session_messages
from ..services.knowledge_graph import collect_conversation_topics, resolve_conversation_topic
from ..services.notebook_service import ensure_notebook_owner, touch_notebook
from ..services.profile_service import ensure_user, log_event
from ..services.ownership_service import (
    sync_resource_ownership,
    task_belongs_to_user,
    task_resource_id,
)
from ..auth import require_current_user_id
from .sse import sse_response

router = APIRouter(prefix="/api/resources", tags=["resources"])


@router.post("/generate")
async def generate(req: GenerateRequest):
    ensure_user(req.user_id)
    notebook = ensure_notebook_owner(req.user_id, req.notebook_id) if req.notebook_id else None
    try:
        source_ids = (
            validate_source_scope(req.user_id, req.source_ids, req.notebook_id)
            if req.notebook_id else validate_source_scope(req.user_id, req.source_ids)
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    session_id = notebook.session_id if notebook else req.session_id or uuid.uuid4().hex[:8]
    touch_notebook(req.user_id, req.notebook_id)
    conversation_map = (
        "mindmap" in req.kinds
        and (req.artifact_scope == "conversation" or req.prompt_template == "framework")
    )
    if req.session_id:
        history = (
            get_session_messages(req.user_id, session_id, limit=80)
            if conversation_map else
            get_session_messages(req.user_id, session_id)
        )
    else:
        history = []
    topic_kp, topic_name, custom_topic = resolve_conversation_topic(
        req.conversation_focus or req.goal,
        history,
        knowledge_points=req.knowledge_points,
        topic_label=req.topic_label,
    )
    msg = req.goal or f"请为我生成 {topic_name} 的学习资源"
    conversation_topics = (
        collect_conversation_topics(history, req.conversation_focus)
        if conversation_map else []
    )
    state = {
        "user_id": req.user_id,
        "session_id": session_id,
        "notebook_id": req.notebook_id,
        "messages": [{"role": "user", "content": msg}],
        "conversation": history,
        "learning_goal": req.goal,
        "topic_label": topic_name,
        "custom_topic": custom_topic,
        "knowledge_points": [topic_kp],
        "kinds": req.kinds,
        "source_ids": source_ids,
        "prompt_template": req.prompt_template,
        "artifact_scope": "conversation" if conversation_map else req.artifact_scope,
        "conversation_topics": conversation_topics,
        "intent": "generate",                  # 显式生成,Orchestrator 将尊重该意图
    }
    return sse_response(run_with_events(state))


def _as_json(v, default):
    if isinstance(v, (dict, list)):
        return v
    try:
        return json.loads(v) if v else default
    except Exception:
        return default


def _row_to_dict(r: Resource) -> dict:
    return {"id": r.id, "kind": r.kind, "kp": r.kp, "title": r.title,
            "payload": _as_json(r.payload, {}),
            "citations": _as_json(r.citations, []),
            "created_at": r.created_at.isoformat() if r.created_at else None}


@router.get("")
async def list_resources(user_id: str = Query("demo_user"),
                         kind: str | None = None, kp: str | None = None,
                         notebook_id: str | None = None, limit: int = 50):
    ensure_user(user_id)
    if notebook_id:
        ensure_notebook_owner(user_id, notebook_id)
    with session() as s:
        q = s.query(Resource).filter(Resource.user_id == user_id)
        if kind:
            q = q.filter(Resource.kind == kind)
        if kp:
            q = q.filter(Resource.kp == kp)
        fetch_limit = min(max(limit * 5, 50), 500) if notebook_id else limit
        rows = q.order_by(Resource.created_at.desc()).limit(fetch_limit).all()
        if notebook_id:
            rows = [
                row for row in rows
                if str(_as_json(row.payload, {}).get("notebook_id") or "") == notebook_id
            ][:limit]
        return {"items": [_row_to_dict(r) for r in rows]}


@router.post("/{rid}/audio")
async def retry_audio(rid: str, req: AudioRetryRequest):
    """Retry cloud TTS while keeping browser speech as a visible fallback."""
    ensure_user(req.user_id)
    with session() as s:
        resource = s.get(Resource, rid)
        if not resource or resource.user_id != req.user_id:
            raise HTTPException(404, "resource not found")
        if resource.kind != "doc":
            raise HTTPException(400, "only document resources support audio narration")
        payload = dict(_as_json(resource.payload, {}))
        markdown = str(payload.get("markdown") or "").strip()
        if not markdown:
            raise HTTPException(409, "resource has no narration content")
        narration = str(payload.get("audio_narration") or "").strip()
        if not narration:
            narration = doc_agent._narration_text(resource.title, markdown)  # noqa: SLF001
            payload["audio_narration"] = narration
    result = await multimodal_gateway.tts(narration, trace_id=f"audio-retry-{rid}")
    if isinstance(result, dict) and result.get("ok"):
        payload["audio_url"] = str((result.get("data") or {}).get("audio_url") or "")
        payload["audio"] = {
            "status": "ready",
            "provider": str((result.get("data") or {}).get("provider") or "spark_tts"),
            "error": "",
            "retryable": False,
        }
    else:
        payload.pop("audio_url", None)
        error = (
            str(result.get("error") or "云端语音暂时不可用")
            if isinstance(result, dict) else "云端语音暂时不可用"
        )
        payload["audio"] = {
            "status": "fallback",
            "provider": "browser_speech",
            "error": error[:240],
            "retryable": True,
        }

    with session() as s:
        resource = s.get(Resource, rid)
        if not resource or resource.user_id != req.user_id:
            raise HTTPException(404, "resource not found")
        resource.payload = payload
        if payload["audio"]["status"] == "ready":
            safety = dict(_as_json(resource.safety, {}))
            safety["flags"] = [
                flag for flag in safety.get("flags", [])
                if not isinstance(flag, dict) or flag.get("type") != "audio_degraded"
            ]
            resource.safety = safety
        s.commit()
        s.refresh(resource)
        response_resource = _row_to_dict(resource)

    sync_resource_ownership(req.user_id, rid, payload)

    log_event(req.user_id, "audio_retry", {
        "resource_id": rid,
        "status": payload["audio"]["status"],
        "provider": payload["audio"]["provider"],
    })
    return {"resource": response_resource, "audio": payload["audio"], "reused": False}


@router.get("/video/task/{task_id}")
async def video_task(task_id: str):
    user_id = require_current_user_id()
    if not task_belongs_to_user(user_id, task_id):
        raise HTTPException(404, "video task not found")
    resource_id = task_resource_id(user_id, task_id)
    state = await multimodal_gateway.video_poll(
        task_id,
        trace_id=f"video-poll-{task_id[:12]}",
    )
    if not resource_id:
        return state

    updated_payload: dict | None = None
    with session() as db:
        resource = db.get(Resource, resource_id)
        if resource and resource.user_id == user_id and resource.kind == "video":
            payload = dict(_as_json(resource.payload, {}))
            previous_video = dict(payload.get("video") or {})
            if str(state.get("url") or "").startswith("/static/gen/"):
                previous_video.pop("urls", None)
            payload["video"] = {**previous_video, **state}
            resource.payload = payload
            db.commit()
            db.refresh(resource)
            updated_payload = payload
    if state.get("url") and updated_payload:
        sync_resource_ownership(user_id, resource_id, updated_payload)
    return state


@router.get("/ppt/task/{task_id}")
async def ppt_task(task_id: str):
    user_id = require_current_user_id()
    if not task_belongs_to_user(user_id, task_id):
        raise HTTPException(404, "PPT task not found")
    resource_id = task_resource_id(user_id, task_id)
    state = await multimodal_gateway.ppt_poll(task_id, trace_id=f"ppt-poll-{task_id[:12]}")
    if not resource_id:
        return state

    updated_payload: dict | None = None
    with session() as db:
        resource = db.get(Resource, resource_id)
        if resource and resource.user_id == user_id and resource.kind == "ppt":
            payload = dict(_as_json(resource.payload, {}))
            payload["ppt"] = {**dict(payload.get("ppt") or {}), **state}
            resource.payload = payload
            db.commit()
            db.refresh(resource)
            updated_payload = payload
    if state.get("url") and updated_payload:
        sync_resource_ownership(user_id, resource_id, updated_payload)
    return state


@router.get("/{rid}")
async def get_resource(rid: str):
    from ..auth import current_user_id

    with session() as s:
        r = s.get(Resource, rid)
        if not r or (current_user_id() and r.user_id != current_user_id()):
            raise HTTPException(404, "resource not found")
        return _row_to_dict(r)

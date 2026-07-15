"""资源 API:
POST /api/resources/generate —— 显式资源生成(SSE 全流水线,intent 固定 generate);
GET  /api/resources           —— 我的资源列表(支持 kind/kp 过滤);
GET  /api/resources/{rid}     —— 资源详情;
GET  /api/resources/video/task/{task_id} —— Seedance 视频任务状态轮询。"""
from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, HTTPException, Query

from ..agents.graph import run_with_events
from ..llm import multimodal_gateway
from ..models.db import session
from ..models.entities import Resource
from ..rag.ingest import validate_source_scope
from ..schemas.core import GenerateRequest
from ..services.profile_service import ensure_user
from .sse import sse_response

router = APIRouter(prefix="/api/resources", tags=["resources"])


@router.post("/generate")
async def generate(req: GenerateRequest):
    ensure_user(req.user_id)
    try:
        source_ids = validate_source_scope(req.user_id, req.source_ids)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    msg = req.goal or f"请为我生成 {','.join(req.knowledge_points) or '推荐知识点'} 的学习资源"
    state = {
        "user_id": req.user_id,
        "session_id": uuid.uuid4().hex[:8],
        "messages": [{"role": "user", "content": msg}],
        "learning_goal": req.goal,
        "topic_label": req.topic_label,
        "knowledge_points": req.knowledge_points,
        "kinds": req.kinds,
        "source_ids": source_ids,
        "prompt_template": req.prompt_template,
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
                         limit: int = 50):
    with session() as s:
        q = s.query(Resource).filter(Resource.user_id == user_id)
        if kind:
            q = q.filter(Resource.kind == kind)
        if kp:
            q = q.filter(Resource.kp == kp)
        rows = q.order_by(Resource.created_at.desc()).limit(limit).all()
        return {"items": [_row_to_dict(r) for r in rows]}


@router.get("/video/task/{task_id}")
async def video_task(task_id: str):
    return await multimodal_gateway.video_poll(task_id)


@router.get("/{rid}")
async def get_resource(rid: str):
    with session() as s:
        r = s.get(Resource, rid)
        if not r:
            raise HTTPException(404, "resource not found")
        return _row_to_dict(r)

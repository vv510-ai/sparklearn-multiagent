"""POST /api/chat —— 统一对话入口(SSE)。
任意自然语言进入编排图:Orchestrator 意图识别后路由到 闲聊/答疑/生成/评估 分支,
事件流包含 agent_start/agent_token/token/resource/path/profile/citations/done。"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException

from ..agents.graph import run_with_events
from ..rag.ingest import validate_source_scope
from ..schemas.core import ChatRequest
from ..services.profile_service import ensure_user
from .sse import sse_response

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat")
async def chat(req: ChatRequest):
    ensure_user(req.user_id)
    try:
        source_ids = validate_source_scope(req.user_id, req.source_ids)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    state = {
        "user_id": req.user_id,
        "session_id": req.session_id or uuid.uuid4().hex[:8],
        "messages": [{"role": "user", "content": req.message}],
        "source_ids": source_ids,
    }
    return sse_response(run_with_events(state))

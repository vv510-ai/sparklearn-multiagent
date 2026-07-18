"""POST /api/chat —— 统一对话入口(SSE)。
任意自然语言进入编排图:Orchestrator 意图识别后路由到 闲聊/答疑/生成/评估 分支,
事件流包含 agent_start/agent_token/token/resource/path/profile/citations/done。"""
from __future__ import annotations

import uuid
from typing import AsyncIterator

from fastapi import APIRouter, HTTPException

from ..agents.graph import run_with_events
from ..rag.ingest import validate_source_scope
from ..schemas.core import ChatRequest
from ..services.conversation_service import append_message, get_session_messages
from ..services.notebook_service import ensure_notebook_owner, touch_notebook
from ..services.profile_service import ensure_user
from .sse import sse_response

router = APIRouter(prefix="/api", tags=["chat"])


async def _persisted_events(
    events: AsyncIterator[dict],
    *,
    user_id: str,
    session_id: str,
) -> AsyncIterator[dict]:
    answer_parts: list[str] = []
    resource_titles: list[str] = []
    summary_text = ""
    completed = False
    async for event in events:
        if event.get("type") == "token":
            answer_parts.append(str(event.get("delta") or ""))
        elif event.get("type") == "resource" and isinstance(event.get("resource"), dict):
            title = str(event["resource"].get("title") or "").strip()
            if title:
                resource_titles.append(title)
        elif event.get("type") == "summary":
            summary_text = str(event.get("text") or "").strip()
        elif event.get("type") == "done":
            completed = True
        yield event

    if completed:
        answer = "".join(answer_parts).strip()
        if not answer and resource_titles:
            answer = summary_text or f"已整理学习资源：{'、'.join(resource_titles)}"
        append_message(user_id, session_id, "assistant", answer)


@router.post("/chat")
async def chat(req: ChatRequest):
    ensure_user(req.user_id)
    notebook = ensure_notebook_owner(req.user_id, req.notebook_id) if req.notebook_id else None
    session_id = notebook.session_id if notebook else req.session_id or uuid.uuid4().hex[:8]
    try:
        source_ids = (
            validate_source_scope(req.user_id, req.source_ids, req.notebook_id)
            if req.notebook_id else validate_source_scope(req.user_id, req.source_ids)
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    history = get_session_messages(req.user_id, session_id)
    current = {"role": "user", "content": req.message}
    append_message(req.user_id, session_id, "user", req.message)
    touch_notebook(req.user_id, req.notebook_id)
    state = {
        "user_id": req.user_id,
        "session_id": session_id,
        "notebook_id": req.notebook_id,
        "messages": [current],
        "conversation": [*history, current],
        "topic_label": req.topic_label,
        "source_ids": source_ids,
    }
    events = _persisted_events(
        run_with_events(state),
        user_id=req.user_id,
        session_id=session_id,
    )
    return sse_response(events)

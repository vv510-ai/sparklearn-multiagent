"""路径 API:
GET  /api/path?user_id=  —— 当前个性化学习路径(无则按画像即时规划);
POST /api/path/replan    —— 主动重排(评估后 / 目标变化时)。"""
from __future__ import annotations

from fastapi import APIRouter, Query

from ..schemas.core import ReplanRequest
from ..services.conversation_service import get_session_messages
from ..services.knowledge_graph import collect_conversation_topics
from ..services.notebook_service import ensure_notebook_owner
from ..services.path_service import (
    get_path,
    is_current_course_path,
    list_decisions,
    plan_conversation_path,
    plan_path,
    save_path,
)
from ..services.profile_service import ensure_user, get_profile, log_event

router = APIRouter(prefix="/api/path", tags=["path"])


@router.get("/decisions")
async def read_decisions(user_id: str = Query("demo_user"), limit: int = 20):
    ensure_user(user_id)
    return {"items": list_decisions(user_id, limit)}


@router.get("")
async def read_path(
    user_id: str = Query("demo_user"),
    notebook_id: str = Query(""),
):
    ensure_user(user_id)
    if notebook_id:
        notebook = ensure_notebook_owner(user_id, notebook_id)
        history = get_session_messages(user_id, notebook.session_id, limit=200)
        topics = collect_conversation_topics(history, max_topics=24)
        if topics:
            path = plan_conversation_path(get_profile(user_id), topics)
            save_path(user_id, path)
            return path
    path = get_path(user_id)
    if not is_current_course_path(path):
        path = plan_path(get_profile(user_id))
        save_path(user_id, path)
    return path


@router.post("/replan")
async def replan(req: ReplanRequest):
    ensure_user(req.user_id)
    path = plan_path(get_profile(req.user_id))
    save_path(req.user_id, path)
    log_event(req.user_id, "path_replan", {"reason": req.reason})
    return path

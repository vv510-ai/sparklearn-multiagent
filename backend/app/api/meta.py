"""元数据 API:
GET /api/kg                 —— 课程知识图谱(节点 + 先修边,前端路径页渲染 DAG);
GET /api/profile/{user_id}  —— 8 维学生画像;
GET /api/health             —— 健康检查(含运行模式)。"""
from __future__ import annotations

from fastapi import APIRouter

from ..auth import require_current_user_id
from ..config import COURSE_NAME, is_demo
from ..llm.spark_client import active_llm_label, active_provider
from ..rag.embedding import embedding_status
from ..rag.reranker import reranker_status
from ..schemas.core import OnboardingRequest
from ..services.knowledge_graph import load_kg
from ..services.path_service import get_path, is_current_course_path, plan_path, save_path
from ..services.profile_service import complete_onboarding, ensure_user, get_profile

router = APIRouter(prefix="/api", tags=["meta"])


@router.get("/model-status")
async def model_status():
    from ..llm.multimodal_gateway import capability_status
    return {"demo_mode": is_demo(), "text": active_llm_label(),
            "provider": active_provider(), "capabilities": capability_status()}


@router.get("/kg")
async def knowledge_graph():
    kg = load_kg()
    return {"course": COURSE_NAME, **kg}


@router.get("/profile/{user_id}")
async def profile(user_id: str):
    ensure_user(user_id)
    return get_profile(user_id)


@router.get("/onboarding")
async def onboarding_status():
    """Return whether the current account still needs first-use setup."""
    user_id = require_current_user_id()
    profile_data = get_profile(user_id)
    required = profile_data.get("onboarding_completed") is not True
    path = get_path(user_id)
    if path and not is_current_course_path(path):
        path = None
    return {"required": required, "profile": profile_data, "path": path}


@router.post("/onboarding")
async def save_onboarding(req: OnboardingRequest):
    """Persist first-use answers and immediately recalculate the first path."""
    user_id = require_current_user_id()
    profile_data = complete_onboarding(user_id, req.model_dump())
    if req.survey is not None:
        from ..services.assessment_service import save_intake_context
        profile_data = save_intake_context(user_id, req.survey.model_dump(mode="json"))
    path = plan_path(profile_data, generated_by="onboarding")
    save_path(user_id, path)
    next_node = next(
        (node for node in path.get("nodes", []) if node.get("id") == path.get("next_kp")),
        {},
    )
    return {
        "required": False,
        "profile": profile_data,
        "path": path,
        "recommendation": {
            "knowledge_point": path.get("next_kp"),
            "title": next_node.get("name") or "课程基础",
            "reason": next_node.get("reason") or "从当前画像的下一项开始",
        },
    }


@router.get("/health")
async def health():
    return {"status": "ok", "demo_mode": is_demo(),
            "course": COURSE_NAME,
            "llm": active_llm_label(),
            "llm_provider": "mock" if is_demo() else active_provider(),
            "embedding": embedding_status(),
            "reranker": reranker_status(),
            "app": "知行循证 LearnLoop"}

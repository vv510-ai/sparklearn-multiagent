"""元数据 API:
GET /api/kg                 —— 课程知识图谱(节点 + 先修边,前端路径页渲染 DAG);
GET /api/profile/{user_id}  —— 8 维学生画像;
GET /api/health             —— 健康检查(含运行模式)。"""
from __future__ import annotations

from fastapi import APIRouter

from ..config import COURSE_NAME, is_demo
from ..llm.spark_client import active_llm_label, active_provider
from ..rag.embedding import embedding_status
from ..rag.reranker import reranker_status
from ..services.knowledge_graph import load_kg
from ..services.profile_service import ensure_user, get_profile

router = APIRouter(prefix="/api", tags=["meta"])


@router.get("/kg")
async def knowledge_graph():
    kg = load_kg()
    return {"course": COURSE_NAME, **kg}


@router.get("/profile/{user_id}")
async def profile(user_id: str):
    ensure_user(user_id)
    return get_profile(user_id)


@router.get("/health")
async def health():
    return {"status": "ok", "demo_mode": is_demo(),
            "course": COURSE_NAME,
            "llm": active_llm_label(),
            "llm_provider": "mock" if is_demo() else active_provider(),
            "embedding": embedding_status(),
            "reranker": reranker_status(),
            "app": "SparkLearn 星火学伴"}

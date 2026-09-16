"""路径规划智能体(Path Agent):知识图谱依赖 + BKT 掌握度 → 动态个性化学习路径(DAG),
随评估结果重排(闭环);算法详见 services/path_service.plan_path。"""
from __future__ import annotations

import datetime as dt

from ..services.path_service import plan_path, save_path
from ..services.knowledge_graph import CUSTOM_TOPIC_KP, kp_name, resolve_topic
from .emitter import agent_end, agent_start, emit


async def run(state: dict) -> dict:
    await agent_start("path", "路径规划智能体", "BKT 掌握度 × 图谱依赖 × 难度偏好 → 路径 DAG")
    profile = state.get("student_profile", {})
    goal_kps = state.get("knowledge_points") or []
    topic_kp, topic_name, custom_topic = resolve_topic(
        goal_kps, state.get("learning_goal"), state.get("topic_label")
    )
    if custom_topic:
        path = {
            "nodes": [{
                "id": CUSTOM_TOPIC_KP,
                "name": topic_name,
                "mastery": 0.3,
                "status": "ready",
                "difficulty": 1,
                "score": 1.0,
                "order": 1,
                "reason": "当前笔记本的自定义学习主题",
            }],
            "edges": [],
            "next_kp": CUSTOM_TOPIC_KP,
            "generated_by": "path_agent_custom_topic",
            "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        }
        from ..services.learning_scope import current_space
        if current_space() and current_space()["graph"]["nodes"]:
            path = plan_path(profile, generated_by="course_learning_space")
    else:
        path = plan_path(profile, goal_kps=[topic_kp], generated_by="path_agent")
    save_path(state.get("user_id", "demo_user"), path)
    await emit({"type": "path", "path": path})
    nxt = path.get("next_kp")
    ready = [n for n in path["nodes"] if n["status"] == "ready"]
    nxt_name = topic_name if nxt == CUSTOM_TOPIC_KP else kp_name(nxt) if nxt else "-"
    await agent_end("path",
                    f"{len(path['nodes'])} 个知识点入图,{len(ready)} 个就绪,"
                    f"下一步推荐「{nxt_name}」",
                    {"next_kp": nxt})
    return {"path_plan": path}

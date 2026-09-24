"""确定性资源规划：按用户点名 kinds 与已解析知识点生成计划，禁止模型扩产物；
意图兜底识别在 Orchestrator。"""
from __future__ import annotations

from ..services.knowledge_graph import all_kp_ids, infer_kp_id, resolve_topic
from ..config import is_demo
from ..llm.spark_client import llm_complete
from ..services.one_page_topic import resolve_scope
from .emitter import agent_end, agent_start

def _kp_from_goal(goal: str, kp_ids: list[str]) -> str | None:
    """Prefer an explicitly mentioned course concept over a generic model plan."""
    return infer_kp_id(goal, kp_ids)


async def run(state: dict) -> dict:
    await agent_start("planner", "资源规划智能体", "显式资源类型 + 已解析知识点 → 确定性生成计划")
    goal = state.get("learning_goal") or (state.get("messages") or [{}])[-1].get("content", "")
    kinds = state.get("kinds") or ["doc", "mindmap", "quiz", "video"]
    target_kp, topic_name, is_custom = resolve_topic(
        state.get("knowledge_points"),
        str(goal),
        str(state.get("topic_label") or ""),
    )

    one_page_scope = None
    if state.get("prompt_template") == "one_page":
        one_page_scope = await resolve_scope(str(goal), state.get("conversation") or [],
            str(state.get("topic_label") or ""), complete=llm_complete, demo=is_demo())
        target_kp, topic_name = one_page_scope["kp"], one_page_scope["topic"]
        is_custom = target_kp == "custom_topic"

    plan: dict = {
        "resources": [
            {"kind": kind, "kp": target_kp, "reason": "按当前学习主题生成，禁止模型改换知识点"}
            for kind in kinds
        ],
        "order": "讲解→" + "→".join(kinds),
    }

    items = plan.get("resources") if isinstance(plan, dict) else None
    items = [item for item in items or [] if isinstance(item, dict)]
    if not items:
        items = [{"kind": k, "kp": target_kp, "reason": "按已识别知识点生成"} for k in kinds]
        plan = {"resources": items, "order": "→".join(kinds)}

    normalized_items = []
    for item in items:
        kp = target_kp
        if item.get("kind") not in set(kinds) | {"reading"}:
            continue
        normalized_items.append({**item, "kp": kp})
    if not normalized_items:
        normalized_items = [
            {"kind": kind, "kp": target_kp, "reason": "按已识别知识点生成"}
            for kind in kinds
        ]
    plan["resources"] = normalized_items
    kp0 = normalized_items[0]["kp"]
    await agent_end("planner",
                    f"目标主题「{topic_name}」,计划 {len(plan['resources'])} 项:"
                    + plan.get("order", ""), {"plan": plan})
    return {
        "learning_goal": goal,
        "plan": plan,
        "knowledge_points": [kp0],
        "topic_label": topic_name,
        "custom_topic": is_custom,
        **({"one_page_scope": one_page_scope} if one_page_scope else {}),
    }

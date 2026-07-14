"""资源规划智能体(Planner Agent):画像 + 学习目标 + 知识图谱 → 星火 X2 推理
生成资源清单与生成顺序(结构化生成计划),驱动后续并行 fan-out。"""
from __future__ import annotations

import json
import logging

from ..llm.spark_client import llm_complete, parse_json
from ..services.knowledge_graph import all_kp_ids, canonical_kp_id, kp_name
from .emitter import agent_end, agent_start

log = logging.getLogger("sparklearn.planner")

_PROMPT = (
    "TASK=plan\n"
    "你是个性化学习资源规划师。课程《数据结构与算法》。\n"
    "基于【学生画像】与【学习目标】,从知识点列表中选定 1 个目标知识点(kp 用 id),"
    "并规划资源清单(kind ∈ doc|mindmap|quiz|code|reading|video),每项给 reason "
    "说明与画像维度的对应关系(如视觉型→video/mindmap 优先,易错点→quiz 针对出题)。\n"
    "输出 JSON:{{\"resources\": [{{\"kind\": \"...\", \"kp\": \"...\", \"reason\": \"...\"}}], "
    "\"order\": \"用→连接的生成顺序\"}}\n\n"
    "知识点列表:{kps}\n【学生画像】{profile}\n【学习目标】{goal}\n【期望类型】{kinds}\n"
)


def _kp_from_goal(goal: str, kp_ids: list[str]) -> str | None:
    """Prefer an explicitly mentioned course concept over a generic model plan."""
    text = str(goal or "").casefold()
    matches: list[tuple[int, int, str]] = []
    for kp in kp_ids:
        for label in {kp.replace("_", " "), kp_name(kp)}:
            normalized = str(label or "").casefold().strip()
            if not normalized:
                continue
            position = text.find(normalized)
            if position >= 0:
                matches.append((position, -len(normalized), kp))
    return min(matches)[2] if matches else None


async def run(state: dict) -> dict:
    await agent_start("planner", "资源规划智能体", "画像+目标 → 结构化生成计划(星火 X2)")
    profile = state.get("student_profile", {})
    goal = state.get("learning_goal") or (state.get("messages") or [{}])[-1].get("content", "")
    kinds = state.get("kinds") or ["doc", "mindmap", "quiz", "code", "video"]
    kp_ids = all_kp_ids()
    kps = json.dumps([{"id": k, "name": kp_name(k)} for k in kp_ids], ensure_ascii=False)

    slim = {k: v for k, v in profile.items()
            if k in ("cognitive_style", "goal", "difficulty_pref", "error_prone", "resource_pref")}
    plan: dict = {}
    try:
        raw = await llm_complete(
            _PROMPT.format(kps=kps, profile=json.dumps(slim, ensure_ascii=False),
                           goal=goal, kinds=kinds),
            role="reasoner", temperature=0.3, json_mode=True)
        plan = parse_json(raw)
    except Exception as e:  # noqa: BLE001
        log.warning("规划失败,使用兜底计划:%s", e)

    items = plan.get("resources") if isinstance(plan, dict) else None
    items = [item for item in items or [] if isinstance(item, dict)]
    explicit_kp = canonical_kp_id((state.get("knowledge_points") or [None])[0])
    goal_kp = _kp_from_goal(str(goal), kp_ids)
    target_kp = explicit_kp or goal_kp
    fallback_kp = target_kp or "binary_tree"
    if not items:
        items = [{"kind": k, "kp": fallback_kp, "reason": "兜底默认计划"} for k in kinds]
        plan = {"resources": items, "order": "→".join(kinds)}

    for item in items:
        item["kp"] = target_kp or canonical_kp_id(item.get("kp")) or fallback_kp
    plan["resources"] = [it for it in items if it.get("kind") in set(kinds) | {"reading"}]
    kp0 = plan["resources"][0]["kp"] if plan["resources"] else "binary_tree"
    await agent_end("planner",
                    f"目标知识点「{kp_name(kp0)}」,计划 {len(plan['resources'])} 项:"
                    + plan.get("order", ""), {"plan": plan})
    return {"plan": plan, "knowledge_points": [kp0]}

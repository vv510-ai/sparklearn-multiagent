"""资源规划智能体(Planner Agent):画像 + 学习目标 + 知识图谱 → 星火 X2 推理
生成资源清单与生成顺序(结构化生成计划),驱动后续并行 fan-out。"""
from __future__ import annotations

import json
import logging

from ..llm.spark_client import llm_complete, parse_json
from ..prompt_templates import invoke_learning_prompt
from ..services.knowledge_graph import all_kp_ids, canonical_kp_id, infer_kp_id, kp_name
from .emitter import agent_end, agent_start

log = logging.getLogger("sparklearn.planner")

def _kp_from_goal(goal: str, kp_ids: list[str]) -> str | None:
    """Prefer an explicitly mentioned course concept over a generic model plan."""
    return infer_kp_id(goal, kp_ids)


async def run(state: dict) -> dict:
    await agent_start("planner", "资源规划智能体", "画像+目标 → 结构化生成计划(星火 X2)")
    profile = state.get("student_profile", {})
    goal = state.get("learning_goal") or (state.get("messages") or [{}])[-1].get("content", "")
    kinds = state.get("kinds") or ["doc", "mindmap", "quiz", "code", "video"]
    kp_ids = all_kp_ids()
    kps = json.dumps([{"id": k, "name": kp_name(k)} for k in kp_ids], ensure_ascii=False)
    explicit_kp = canonical_kp_id((state.get("knowledge_points") or [None])[0])
    goal_kp = _kp_from_goal(str(goal), kp_ids)
    target_kp = explicit_kp or goal_kp

    slim = {k: v for k, v in profile.items()
            if k in ("cognitive_style", "goal", "difficulty_pref", "error_prone", "resource_pref")}
    plan: dict = {}
    if (state.get("guided_learning") or state.get("intent") == "summary") and target_kp:
        plan = {
            "resources": [
                {"kind": kind, "kp": target_kp, "reason": "零基础首轮：先建立框架，再用基础题巩固"}
                for kind in kinds
            ],
            "order": "讲解→" + "→".join(kinds),
        }
    else:
        try:
            prompt_call = invoke_learning_prompt(
                "planner.resources",
                knowledge_points=kps,
                profile=json.dumps(slim, ensure_ascii=False),
                goal=goal,
                kinds=kinds,
            )
            raw = await llm_complete(
                prompt_call.prompt,
                system=prompt_call.system,
                role="reasoner",
                temperature=0.3,
                json_mode=True,
            )
            plan = parse_json(raw)
        except Exception as e:  # noqa: BLE001
            log.warning("规划失败,使用兜底计划:%s", e)

    items = plan.get("resources") if isinstance(plan, dict) else None
    items = [item for item in items or [] if isinstance(item, dict)]
    if not items:
        if not target_kp:
            raise ValueError("未能从学习目标识别课程知识点，请明确要学习的主题")
        items = [{"kind": k, "kp": target_kp, "reason": "按已识别知识点生成"} for k in kinds]
        plan = {"resources": items, "order": "→".join(kinds)}

    normalized_items = []
    for item in items:
        kp = target_kp or canonical_kp_id(item.get("kp"))
        if not kp or item.get("kind") not in set(kinds) | {"reading"}:
            continue
        normalized_items.append({**item, "kp": kp})
    if not normalized_items:
        if not target_kp:
            raise ValueError("资源规划没有返回可验证的课程知识点")
        normalized_items = [
            {"kind": kind, "kp": target_kp, "reason": "按已识别知识点生成"}
            for kind in kinds
        ]
    plan["resources"] = normalized_items
    kp0 = normalized_items[0]["kp"]
    await agent_end("planner",
                    f"目标知识点「{kp_name(kp0)}」,计划 {len(plan['resources'])} 项:"
                    + plan.get("order", ""), {"plan": plan})
    return {"plan": plan, "knowledge_points": [kp0]}

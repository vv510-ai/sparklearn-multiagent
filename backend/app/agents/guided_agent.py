"""引导式学习编排：先回答当前需求，学习产物一律按需生成。"""
from __future__ import annotations

from . import tutor_agent


async def run(state: dict) -> dict:
    working = dict(state)
    working["guided_learning"] = True
    working["artifact_policy"] = "on_demand"
    if not working.get("learning_goal"):
        working["learning_goal"] = (working.get("messages") or [{}])[-1].get("content", "")

    output = await tutor_agent.run(working)
    return {
        **output,
        "guided_learning": True,
        "artifact_policy": "on_demand",
    }

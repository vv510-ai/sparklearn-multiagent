"""引导式学习编排：定位知识点后，先讲解，再给小图与基础练习。"""
from __future__ import annotations

import asyncio
import traceback

from . import eval_agent, mindmap_agent, path_agent, planner_agent, quiz_agent, tutor_agent

_LIST_FIELDS = {"messages", "retrieval_context", "citations", "safety_flags", "progress_events"}
_DICT_FIELDS = {"generated_resources"}


def _absorber(state: dict, output: dict):
    def absorb(patch: dict | None) -> None:
        for key, value in (patch or {}).items():
            if key in _DICT_FIELDS:
                state[key] = {**(state.get(key) or {}), **(value or {})}
                output[key] = {**(output.get(key) or {}), **(value or {})}
            elif key in _LIST_FIELDS:
                state[key] = [*(state.get(key) or []), *(value or [])]
                output[key] = [*(output.get(key) or []), *(value or [])]
            else:
                state[key] = value
                output[key] = value
    return absorb


async def run(state: dict) -> dict:
    working = dict(state)
    output: dict = {}
    absorb = _absorber(working, output)
    working["guided_learning"] = True
    working["kinds"] = ["mindmap", "quiz"]
    if not working.get("learning_goal"):
        working["learning_goal"] = (working.get("messages") or [{}])[-1].get("content", "")

    absorb(await planner_agent.run(working))
    absorb(await path_agent.run(working))
    absorb(await tutor_agent.run(working))

    results = await asyncio.gather(
        mindmap_agent.run(working),
        quiz_agent.run(working),
        return_exceptions=True,
    )
    for result in results:
        if isinstance(result, Exception):
            absorb({
                "safety_flags": [{
                    "agent": "guided",
                    "type": "resource_error",
                    "detail": "".join(traceback.format_exception_only(result)).strip(),
                }],
            })
        else:
            absorb(result)

    absorb(await eval_agent.run(working))
    output["guided_learning"] = True
    return output

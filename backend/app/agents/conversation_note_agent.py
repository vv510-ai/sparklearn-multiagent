"""把持久化学习对话整理成可复用的个人笔记资源。"""
from __future__ import annotations

from . import doc_agent, eval_agent, planner_agent

_LIST_FIELDS = {"messages", "retrieval_context", "citations", "safety_flags", "progress_events"}


def _dialog_goal(conversation: list[dict]) -> str:
    user_turns = [
        str(item.get("content") or "").strip()
        for item in conversation
        if item.get("role") == "user"
        and str(item.get("content") or "").strip()
        and "整理" not in str(item.get("content") or "")
        and "总结" not in str(item.get("content") or "")
    ]
    return "；".join(user_turns[-6:]) or "整理本次学习对话"


async def run(state: dict) -> dict:
    working = dict(state)
    output: dict = {}

    def absorb(patch: dict | None) -> None:
        for key, value in (patch or {}).items():
            if key == "generated_resources":
                working[key] = {**(working.get(key) or {}), **(value or {})}
                output[key] = {**(output.get(key) or {}), **(value or {})}
            elif key in _LIST_FIELDS:
                working[key] = [*(working.get(key) or []), *(value or [])]
                output[key] = [*(output.get(key) or []), *(value or [])]
            else:
                working[key] = value
                output[key] = value

    conversation = working.get("conversation") or working.get("messages") or []
    topic_goal = _dialog_goal(conversation)
    if not working.get("knowledge_points"):
        working["learning_goal"] = topic_goal
        working["kinds"] = ["doc"]
        absorb(await planner_agent.run(working))

    working.update({
        "conversation": conversation,
        "learning_goal": f"根据完整学习对话整理个人复习笔记。对话主题：{topic_goal}",
        "kinds": ["doc"],
        "prompt_template": "conversation_notes",
    })
    absorb(await doc_agent.run(working))
    absorb(await eval_agent.run(working))
    return output

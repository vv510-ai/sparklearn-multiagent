"""Request-first infographic scope and semantic draft checks, independent of course taxonomies."""
from __future__ import annotations
import asyncio
import re
from ..llm.spark_client import parse_json
from ..prompt_templates import invoke_learning_prompt
from .knowledge_graph import clean_topic_label, load_kg
from .learning_scope import current_space


def _tool_only(text: str) -> bool:
    # Match complete sequences of request words; never remove syllables from a
    # subject and accidentally turn it into a context-free command.
    return bool(re.fullmatch(
        r"(?:一[图页]看懂|知识图谱?|信息图|请|帮我|给我|帮忙|麻烦|可以|能不能|能|你|我|"
        r"把|将|用|生成|制作|整理|画出|画成|画|做成|做|一下|一个|一张|一份|功能|"
        r"刚才|上面|前面|这些|这个|那个|这部分|它|当前|本次|内容|知识|对话|总结|继续|"
        r"的|再|吧|吗|好|[\s，,。！？?!：:])*", text))



def _scope(topic: str, overview: bool, **extra) -> dict:
    # Exact whole-label matches only: a multi-concept overview must not collapse
    # to the first incidental node in the active course graph.
    kp = "custom_topic"
    if not overview:
        compact = re.sub(r"\s+", "", topic).casefold()
        for key, node in load_kg()["nodes"].items():
            labels = [key, node.get("name", ""), *node.get("aliases", [])]
            if compact in {re.sub(r"\s+", "", str(value)).casefold() for value in labels}:
                kp = key
                break
    course_title = str(((current_space() or {}).get("course") or {}).get("title") or "")
    compact = re.sub(r"[\s（）()·-]+", "", topic).casefold()
    current = re.sub(r"[\s（）()·-]+", "", course_title).casefold()
    # Course-specific exam records are optional enrichment. When the scope is
    # not confidently the current course, omit them instead of injecting old
    # exam requirements into a different subject. This never limits generation.
    use_course_reference = kp != "custom_topic" or bool(len(compact) >= 2 and compact in current)
    return {"topic": topic, "overview": overview, "kp": kp,
            "use_course_reference": use_course_reference, **extra}


async def resolve_scope(goal: str, conversation: list[dict], previous_topic: str, *, complete, demo: bool) -> dict:
    history = [{"role": item.get("role"), "content": str(item.get("content") or "")[:1800]}
               for item in conversation[-8:] if item.get("role") in {"user", "assistant"}]
    if not demo:
        call = invoke_learning_prompt("doc.one_page_scope", goal=goal,
            conversation=str(history), previous_topic=previous_topic)
        try:
            raw = await asyncio.wait_for(complete(call.prompt, system=call.system, role="reasoner",
                temperature=0, max_tokens=450, json_object=True, reasoning_mode="disabled",
                allow_mock_fallback=False, allow_model_fallback=False), timeout=20)
            value = parse_json(raw)
            topic = value.get("topic") if isinstance(value, dict) else None
            if topic == "" and type(value.get("overview")) is bool:
                return _scope("当前主题", False, resolution="semantic", missing=True)
            if isinstance(topic, str) and 1 <= len(topic.strip()) <= 60 and type(value.get("overview")) is bool:
                if not _tool_only(topic) and topic not in {"当前主题", "未指定", "未知"}:
                    return _scope(topic.strip(), value["overview"], resolution="semantic")
        except Exception:
            pass
    # The tool button appends its current question after a fixed separator.
    # Preserve that question during outages instead of using the long tool
    # instructions as a course title (or clipping off the actual question).
    goal = goal.rsplit("\n\n请以最近学习对话中的实际问题为准：", 1)[-1].strip()
    # Never restore a stale KP merely because semantic extraction is unavailable.
    if _tool_only(goal):
        earlier = [item for item in history if item.get("role") == "user" and not _tool_only(item["content"])]
        focus = earlier[-1]["content"] if earlier else previous_topic
        if _tool_only(focus) or focus in {"当前主题", "未知", "未指定"}:
            focus = ""
    else:
        focus = goal
    topic = clean_topic_label(focus) if focus else "当前主题"
    return _scope(clean_topic_label(topic), bool(re.search(r"整体|框架|概览|总览|全书|全章|整门|全课程", focus or "")),
                  resolution="request_fallback", missing=not bool(focus) or topic == "当前主题")


async def check_draft(topic: str, goal: str, conversation: str, draft: str, *, complete) -> dict:
    call = invoke_learning_prompt("doc.one_page_topic_check", topic=topic, goal=goal,
                                  conversation=conversation[-6000:], draft=draft)
    try:
        raw = await asyncio.wait_for(complete(call.prompt, system=call.system, role="reasoner",
            temperature=0, max_tokens=700, json_object=True, reasoning_mode="disabled",
            allow_mock_fallback=False, allow_model_fallback=False), timeout=30)
        value = parse_json(raw)
        if not isinstance(value, dict) or value.get("status") not in {"matched", "mismatch", "uncertain"}:
            raise ValueError("missing semantic verdict")
        if not isinstance(value.get("reason"), str) or not value["reason"].strip():
            raise ValueError("missing semantic evidence")
        return {"status": value["status"], "reason": value["reason"][:600], "prompt_skill": call.metadata()}
    except Exception:
        # A failed checker is not evidence of an off-topic draft.
        return {"status": "uncertain", "reason": "主题自动核对暂未完成，请结合本次问题检查内容。"}

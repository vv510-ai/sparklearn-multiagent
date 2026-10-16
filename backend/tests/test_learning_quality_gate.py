"""Deterministic golden cases for the source-grounded learning loop."""
from __future__ import annotations

import asyncio

from app.agents import orchestrator, tutor_agent
from app.prompt_templates import invoke_learning_prompt, render_tutor_prompt


def test_guided_lesson_stays_beginner_first_and_inside_the_source_boundary():
    call = render_tutor_prompt(
        "从零学习二叉树",
        {"difficulty_pref": "循序渐进"},
        "[^1] 二叉树由结点和边组成。",
        ["source-a"],
        guided=True,
    )

    assert call.capability == "tutor.guided"
    assert "一句没有专业术语的话" in call.prompt
    assert "最小例子" in call.prompt
    assert "不要把当前主题偷换成更特殊的概念" in call.prompt
    assert "资料不足" in call.system
    assert "仅使用本次选中的学习资料" in call.prompt


def test_conversation_note_is_a_reusable_source_grounded_artifact():
    call = invoke_learning_prompt(
        "doc.conversation_notes",
        topic="递归",
        goal="整理本次学习",
        persona="零基础",
        conversation="学习者：我不理解终止条件。\n小知：先看最小例子。",
        context="[^1] 递归必须有终止条件。",
    )

    assert "学习对话用于还原学习者问过什么" in call.prompt
    assert "参考资料用于支撑知识事实" in call.prompt
    assert "三分钟复习清单" in call.prompt
    assert "不得编造学习者没有说过的问题" in call.prompt


def test_small_talk_skips_rag_even_when_a_source_is_selected(monkeypatch):
    def fail_retrieve(*args, **kwargs):
        raise AssertionError("small talk must not call retrieve")

    monkeypatch.setattr(tutor_agent, "retrieve", fail_retrieve)
    result = asyncio.run(tutor_agent.run({
        "user_id": "demo_user",
        "session_id": "quality-small-talk",
        "messages": [{"role": "user", "content": "你好"}],
        "source_ids": ["source-a"],
        "student_profile": {},
    }))

    assert "小知" in result["answer"]
    assert result["citations"] == []
    assert result["safety_flags"] == []


def test_small_talk_routes_to_tutor_without_calling_intent_llm(monkeypatch):
    async def fail_complete(*args, **kwargs):
        raise AssertionError("deterministic small talk must not call the intent model")

    monkeypatch.setattr(orchestrator, "llm_complete", fail_complete)
    result = asyncio.run(orchestrator.run({
        "messages": [{"role": "user", "content": "你好"}],
    }))

    assert result["intent"] == "chat"
    assert orchestrator.route_task(result) == "tutor"


def test_learning_strategy_recognizes_natural_starting_questions():
    assert tutor_agent._is_learning_strategy_question("外贸函电怎么开始学")  # noqa: SLF001
    assert tutor_agent._is_learning_strategy_question("数据结构从哪里入门")  # noqa: SLF001


def test_tutor_answer_blocks_internal_prompt_echo():
    leaked = """```\nTASK=tutor\nMODE=followup\n当前问题：外贸函电怎么学\n教学策略：先解释\n输出自检：不要输出内部分析\n```"""
    assert tutor_agent._normalize_tutor_answer(  # noqa: SLF001
        leaked,
        "外贸函电怎么学",
        has_context=False,
    ) == ""


def test_selected_source_gap_is_explicit_and_never_calls_the_model(monkeypatch):
    monkeypatch.setattr(tutor_agent, "retrieve", lambda *args, **kwargs: [])

    async def fail_stream(*args, **kwargs):
        raise AssertionError("missing selected-source evidence must block model generation")
        yield "unreachable"

    monkeypatch.setattr(tutor_agent, "llm_stream", fail_stream)
    result = asyncio.run(tutor_agent.run({
        "user_id": "demo_user",
        "session_id": "quality-source-gap",
        "messages": [{"role": "user", "content": "根据资料解释红黑树"}],
        "source_ids": ["source-a"],
        "student_profile": {},
    }))

    assert "当前选中的资料中没有检索到" in result["answer"]
    assert result["citations"] == []
    assert result["safety_flags"][0]["type"] == "source_scope_empty"


def test_failed_grounding_replaces_the_model_answer_before_it_is_returned(monkeypatch):
    chunks = [{
        "text": "二叉树中的叶节点是没有孩子的节点。",
        "source": "课程讲义",
        "source_id": "source-a",
        "chapter": "二叉树",
        "page": 1,
        "citation": "课程讲义 · 二叉树 p.1",
    }]
    monkeypatch.setattr(tutor_agent, "retrieve", lambda *args, **kwargs: chunks)
    monkeypatch.setattr(tutor_agent, "is_demo", lambda: False)

    async def hallucinated_stream(*args, **kwargs):
        yield "没有孩子的节点叫根节点。"

    async def failed_grounding(*args, **kwargs):
        return {"grounded": False, "unsupported": ["根节点"], "verdict": "定义与资料冲突"}

    monkeypatch.setattr(tutor_agent, "llm_stream", hallucinated_stream)
    monkeypatch.setattr(tutor_agent, "grounding_check", failed_grounding)
    result = asyncio.run(tutor_agent.run({
        "user_id": "demo_user",
        "session_id": "quality-grounding-fallback",
        "messages": [{"role": "user", "content": "什么是叶节点？"}],
        "source_ids": ["source-a"],
        "student_profile": {},
    }))

    assert "没有孩子的节点叫根节点" not in result["answer"]
    assert "叶节点是没有孩子的节点" not in result["answer"]  # No source dump as a substitute answer.
    assert "重试" in result["answer"]
    assert result["safety_flags"][0]["type"] == "grounding_fallback"

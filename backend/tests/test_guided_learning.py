"""引导式学习、对话笔记与笔记复用的离线回归测试。"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tests._stubs import install  # noqa: E402

install()

from app.agents.graph import run_with_events  # noqa: E402
from app.agents.orchestrator import requested_resource_kinds, route_task, run as route_intent  # noqa: E402
from app.agents.tutor_agent import _build_prompt  # noqa: E402, SLF001
from app.llm.spark_client import MockEngine  # noqa: E402
from app.models.db import init_db  # noqa: E402
from app.prompt_templates import render_learning_prompt  # noqa: E402
from app.rag.ingest import ingest_corpus  # noqa: E402
from app.services.note_service import recent_note_chunks  # noqa: E402
from app.services.profile_service import ensure_user  # noqa: E402


async def _collect(state: dict) -> list[dict]:
    return [event async for event in run_with_events(state)]


def test_beginner_prompt_is_complete_and_contains_conversation():
    prompt = _build_prompt(
        "我想从零开始学习二叉树",
        {"difficulty_pref": "循序渐进", "cognitive_style": "视觉型"},
        "[1] 二叉树由节点组成",
        [],
        conversation=[{"role": "user", "content": "我总分不清左右子树"}],
        guided=True,
    )
    for required in ("学习方法/路线", "只给完成当前目标所需的最少内容", "建议顺序", "现在只做什么"):
        assert required in prompt
    assert "下方会出现基础练习卡" not in prompt
    assert "我总分不清左右子树" in prompt
    assert "二叉树不等于" in prompt or "不要把当前主题偷换" in prompt
    assert "TASK=tutor" in prompt


def test_guided_mock_keeps_binary_tree_and_bst_boundaries_clear():
    lesson = MockEngine.complete("TASK=tutor\nMODE=guided\n我想学习二叉树")
    questions = MockEngine.complete("TASK=quiz\nMODE=guided\n二叉树")
    assert "普通二叉树没有大小顺序" in lesson
    assert "左小右大" in lesson
    assert len(__import__("json").loads(questions)) == 5


def test_learning_and_summary_intents_are_deterministic():
    learning = asyncio.run(route_intent({
        "messages": [{"role": "user", "content": "我想从零开始学习二叉树"}],
    }))
    summary = asyncio.run(route_intent({
        "messages": [{"role": "user", "content": "请把本次学习对话整理成一份可复习、可继续使用的个人笔记。"}],
    }))
    assert learning["intent"] == "learn"
    assert route_task(learning) == "learn"
    assert summary["intent"] == "summary"
    assert route_task(summary) == "summary"


def test_learning_strategy_is_not_misclassified_as_resource_generation():
    learning = asyncio.run(route_intent({
        "messages": [{"role": "user", "content": "数据结构怎么学？请通俗易懂地教我"}],
    }))
    assert learning["intent"] == "learn"
    assert learning["artifact_policy"] == "on_demand"
    assert not learning.get("kinds")


def test_only_explicitly_named_artifacts_are_selected():
    assert requested_resource_kinds("数据结构怎么学？") == []
    assert requested_resource_kinds("请画一张数据结构思维导图") == ["mindmap"]
    assert requested_resource_kinds("请给我出题，不需要导图") == ["quiz"]
    assert requested_resource_kinds("只讲怎么学，不要题目和思维导图") == []


def test_learning_strategy_sse_answers_without_resource_cards():
    init_db()
    ingest_corpus()
    ensure_user("strategy-stu")
    events = asyncio.run(_collect({
        "user_id": "strategy-stu",
        "session_id": "strategy-flow-1",
        "messages": [{"role": "user", "content": "数据结构怎么学？请通俗易懂地教我"}],
        "conversation": [{"role": "user", "content": "数据结构怎么学？请通俗易懂地教我"}],
        "topic_label": "数据结构",
    }))
    starts = [event.get("agent") for event in events if event.get("type") == "agent_start"]
    assert "tutor" in starts
    assert not {"planner", "path", "mindmap", "quiz", "media", "eval"}.intersection(starts)
    assert any(event.get("type") == "token" for event in events)
    assert not any(event.get("type") == "resource" for event in events)


def test_conversation_note_template_keeps_dialogue_and_beginner_structure():
    prompt = render_learning_prompt(
        "conversation_notes",
        topic="二叉树",
        goal="整理本次学习",
        persona="循序渐进",
        context="[1] 课程资料",
        conversation="用户：什么是根节点？\n学伴：先把它想成家谱的第一位成员。",
    )
    assert "什么是根节点" in prompt
    assert "我问过的问题与已经澄清的地方" in prompt
    assert "记忆钩子" in prompt


def test_guided_answer_has_no_automatic_artifacts_then_conversation_note_is_reusable():
    init_db()
    ingest_corpus()
    ensure_user("guided-stu")

    learning_events = asyncio.run(_collect({
        "user_id": "guided-stu",
        "session_id": "guided-flow-1",
        "messages": [{"role": "user", "content": "我想从零开始学习二叉树"}],
        "conversation": [{"role": "user", "content": "我想从零开始学习二叉树"}],
        "knowledge_points": ["binary_tree"],
        "intent": "learn",
    }))
    starts = [event.get("agent") for event in learning_events if event.get("type") == "agent_start"]
    assert "tutor" in starts
    assert not {"planner", "path", "mindmap", "quiz", "media", "eval"}.intersection(starts)
    resources = [event["resource"] for event in learning_events if event.get("type") == "resource"]
    assert resources == []

    conversation = [
        {"role": "user", "content": "我想从零开始学习二叉树"},
        {"role": "assistant", "content": "可以先把二叉树想成一张家谱。"},
        {"role": "user", "content": "根节点是什么意思？"},
        {"role": "assistant", "content": "根节点是最上面的起点。"},
    ]
    note_events = asyncio.run(_collect({
        "user_id": "guided-stu",
        "session_id": "guided-flow-1",
        "messages": [{"role": "user", "content": "请把本次学习对话整理成一份可复习的个人笔记"}],
        "conversation": conversation,
        "knowledge_points": ["binary_tree"],
    }))
    note = next(
        event["resource"] for event in note_events
        if event.get("type") == "resource" and event["resource"]["kind"] == "doc"
    )
    assert note["payload"]["reusable_note"] is True
    assert "根节点是什么意思" in note["payload"]["markdown"]
    assert recent_note_chunks(
        "guided-stu", "二叉树根节点", limit=1, knowledge_point="binary_tree"
    )
    assert not recent_note_chunks(
        "guided-stu", "图是什么", limit=1, knowledge_point="graph_basic"
    )

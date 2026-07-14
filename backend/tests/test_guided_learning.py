"""引导式学习、对话笔记与笔记复用的离线回归测试。"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tests._stubs import install  # noqa: E402

install()

from app.agents.graph import run_with_events  # noqa: E402
from app.agents.orchestrator import route_task, run as route_intent  # noqa: E402
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
    for required in ("一句话先懂", "生活里的它", "最小例子", "一张小图", "记忆钩子", "接下来怎么练"):
        assert required in prompt
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


def test_guided_pipeline_then_conversation_note_is_reusable():
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
    assert starts.index("tutor") < starts.index("mindmap")
    resources = [event["resource"] for event in learning_events if event.get("type") == "resource"]
    assert {"mindmap", "quiz"} <= {resource["kind"] for resource in resources}
    guided_quiz = next(resource for resource in resources if resource["kind"] == "quiz")
    assert len(guided_quiz["payload"]["questions"]) <= 5

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
    assert recent_note_chunks("guided-stu", "二叉树根节点", limit=1)

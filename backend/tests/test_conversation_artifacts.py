from __future__ import annotations

import asyncio

from app.agents.eval_agent import _learner_summary
from app.api import resources as resources_api
from app.schemas.core import GenerateRequest
from app.services.knowledge_graph import clean_topic_label, resolve_conversation_topic


def test_conversation_focus_ignores_opening_help_title_and_recognizes_graph():
    topic = resolve_conversation_topic(
        "我想学习图 怎么办",
        [
            {"role": "user", "content": "你能帮助我干嘛"},
            {"role": "assistant", "content": "你可以问一个想学的内容。"},
            {"role": "user", "content": "我想学习图 怎么办"},
        ],
        topic_label="你能帮助我干嘛",
    )

    assert topic == ("graph_basic", "图的基础", False)


def test_custom_conversation_focus_keeps_subject_and_removes_learning_request_words():
    assert clean_topic_label("我想学习量子纠缠 怎么入门") == "量子纠缠"
    topic = resolve_conversation_topic(
        "我想学习量子纠缠 怎么入门",
        topic_label="你能帮助我干嘛",
    )
    assert topic == ("custom_topic", "量子纠缠", True)


def test_resource_generation_uses_chat_session_and_latest_real_focus(monkeypatch):
    captured: dict = {}
    history = [
        {"role": "user", "content": "你能帮助我干嘛"},
        {"role": "assistant", "content": "告诉我你想学什么。"},
        {"role": "user", "content": "我想学习图 怎么办"},
    ]

    async def empty_events():
        if False:
            yield {}

    def fake_run(state: dict):
        captured.update(state)
        return empty_events()

    monkeypatch.setattr(resources_api, "ensure_user", lambda _user_id: None)
    monkeypatch.setattr(resources_api, "validate_source_scope", lambda _user_id, source_ids: source_ids)
    monkeypatch.setattr(resources_api, "get_session_messages", lambda _user_id, _session_id: history)
    monkeypatch.setattr(resources_api, "run_with_events", fake_run)

    response = asyncio.run(resources_api.generate(GenerateRequest(
        user_id="conversation-user",
        session_id="same-chat-session",
        goal="请根据最近对话生成互动讲解",
        conversation_focus="我想学习图 怎么办",
        topic_label="你能帮助我干嘛",
        kinds=["doc"],
        prompt_template="interactive_audio",
    )))

    assert response.media_type == "text/event-stream"
    assert captured["session_id"] == "same-chat-session"
    assert captured["conversation"] == history
    assert captured["knowledge_points"] == ["graph_basic"]
    assert captured["topic_label"] == "图的基础"
    assert captured["prompt_template"] == "interactive_audio"


def test_resource_generation_keeps_legacy_goal_topic_detection(monkeypatch):
    captured: dict = {}

    async def empty_events():
        if False:
            yield {}

    def fake_run(state: dict):
        captured.update(state)
        return empty_events()

    monkeypatch.setattr(resources_api, "ensure_user", lambda _user_id: None)
    monkeypatch.setattr(resources_api, "validate_source_scope", lambda _user_id, source_ids: source_ids)
    monkeypatch.setattr(resources_api, "run_with_events", fake_run)

    asyncio.run(resources_api.generate(GenerateRequest(
        user_id="legacy-user",
        goal="请生成队列的学习笔记",
        kinds=["doc"],
    )))

    assert captured["knowledge_points"] == ["queue"]
    assert captured["topic_label"] == "队列"


def test_generation_summary_talks_to_the_learner_not_the_pipeline():
    resources = {"r1": {"kind": "doc"}}
    summary = _learner_summary(resources, [], "interactive_audio")

    assert summary == "互动讲解已经准备好了，点开下面的卡片就能边听边问。"
    assert "个性化资源" not in summary
    assert "双层校验" not in summary
    assert "入库" not in summary

from __future__ import annotations

import asyncio

from app.agents import mindmap_agent
from app.agents.eval_agent import _ARTIFACT_READY_TEXT, _learner_summary
from app.api import resources as resources_api
from app.prompt_templates import PromptCall
from app.schemas.core import GenerateRequest
from app.services.knowledge_graph import (
    clean_topic_label,
    collect_conversation_topics,
    infer_kp_ids,
    kp_name,
    resolve_conversation_topic,
)


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


def test_one_page_ready_message_uses_one_image_name():
    assert _ARTIFACT_READY_TEXT["one_page"].startswith("一图看懂")
    assert "一页" not in _ARTIFACT_READY_TEXT["one_page"]


def test_custom_conversation_focus_keeps_subject_and_removes_learning_request_words():
    assert clean_topic_label("我想学习量子纠缠 怎么入门") == "量子纠缠"
    topic = resolve_conversation_topic(
        "我想学习量子纠缠 怎么入门",
        topic_label="你能帮助我干嘛",
    )
    assert topic == ("custom_topic", "量子纠缠", True)


def test_conversation_topics_collect_all_questions_and_ignore_product_help():
    topics = collect_conversation_topics([
        {"role": "user", "content": "你能帮助我干嘛"},
        {"role": "assistant", "content": "告诉我你想学什么。"},
        {"role": "user", "content": "什么是完全二叉树"},
        {"role": "user", "content": "什么是队列"},
        {"role": "user", "content": "我想学习图 怎么办"},
        {"role": "user", "content": "把上面内容整理成框架导图"},
    ])

    assert [topic["id"] for topic in topics] == ["binary_tree", "queue", "graph_basic"]
    assert topics[0]["questions"] == ["什么是完全二叉树"]
    assert infer_kp_ids("堆与优先队列怎么实现") == ["heap"]


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


def test_framework_generation_receives_the_whole_conversation(monkeypatch):
    captured: dict = {}
    history_limit: dict = {}
    history = [
        {"role": "user", "content": "什么是完全二叉树"},
        {"role": "assistant", "content": "完全二叉树按层从左到右排列。"},
        {"role": "user", "content": "什么是队列"},
        {"role": "assistant", "content": "队列遵循先进先出。"},
        {"role": "user", "content": "我想学习图 怎么办"},
    ]

    async def empty_events():
        if False:
            yield {}

    def fake_history(_user_id: str, _session_id: str, *, limit: int = 24):
        history_limit["value"] = limit
        return history

    def fake_run(state: dict):
        captured.update(state)
        return empty_events()

    monkeypatch.setattr(resources_api, "ensure_user", lambda _user_id: None)
    monkeypatch.setattr(resources_api, "validate_source_scope", lambda _user_id, source_ids: source_ids)
    monkeypatch.setattr(resources_api, "get_session_messages", fake_history)
    monkeypatch.setattr(resources_api, "run_with_events", fake_run)

    asyncio.run(resources_api.generate(GenerateRequest(
        user_id="conversation-map-user",
        session_id="conversation-map-session",
        goal="请整合本次学习对话中的全部知识点",
        conversation_focus="我想学习图 怎么办",
        kinds=["mindmap"],
        prompt_template="framework",
        artifact_scope="conversation",
    )))

    assert history_limit["value"] == 80
    assert captured["artifact_scope"] == "conversation"
    assert [topic["id"] for topic in captured["conversation_topics"]] == [
        "binary_tree", "queue", "graph_basic",
    ]


def test_framework_mindmap_integrates_topics_in_prerequisite_order(monkeypatch):
    async def fake_expand(node_id: str, **kwargs):
        name = kwargs.get("topic_name") or kp_name(node_id)
        return [f"{name}的核心定义", f"{name}的最小例子"], [], PromptCall(
            capability="mindmap.leaf",
            prompt=f"expand {name}",
            system="system",
            version="test",
        )

    async def no_event(*args, **kwargs):
        return None

    monkeypatch.setattr(mindmap_agent, "_expand_node", fake_expand)
    monkeypatch.setattr(mindmap_agent, "agent_start", no_event)
    monkeypatch.setattr(mindmap_agent, "agent_end", no_event)
    monkeypatch.setattr(mindmap_agent, "emit", no_event)

    result = asyncio.run(mindmap_agent.run({
        "user_id": "conversation-map-user",
        "learning_goal": "不要把这段内部指令当成导图主题",
        "topic_label": "图的基础",
        "knowledge_points": ["graph_basic"],
        "kinds": ["mindmap"],
        "source_ids": [],
        "student_profile": {},
        "artifact_scope": "conversation",
        "conversation_topics": [
            {"id": "binary_tree", "name": "二叉树", "custom": False, "questions": ["什么是完全二叉树"], "first_index": 0},
            {"id": "queue", "name": "队列", "custom": False, "questions": ["什么是队列"], "first_index": 1},
            {"id": "graph_basic", "name": "图的基础", "custom": False, "questions": ["我想学习图 怎么办"], "first_index": 2},
        ],
    }))
    resource = next(iter(result["generated_resources"].values()))
    markmap = resource["payload"]["markmap"]

    assert resource["title"] == "本次对话·知识全景导图"
    assert resource["payload"]["topic_count"] == 3
    assert "# 本次对话学习全景（3 个知识点）" in markmap
    assert all(name in markmap for name in ("队列", "二叉树", "图的基础"))
    assert markmap.index("## 第 1 步:队列") < markmap.index("## 第 3 步:图的基础")
    assert markmap.index("## 第 2 步:二叉树") < markmap.index("## 第 3 步:图的基础")
    assert "后续关联：图的基础" in markmap
    assert "不要把这段内部指令当成导图主题" not in markmap


def test_generation_summary_talks_to_the_learner_not_the_pipeline():
    resources = {"r1": {"kind": "doc"}}
    summary = _learner_summary(resources, [], "interactive_audio")

    assert summary == "互动讲解已经准备好了，点开下面的卡片就能边听边问。"
    assert "个性化资源" not in summary
    assert "双层校验" not in summary
    assert "入库" not in summary

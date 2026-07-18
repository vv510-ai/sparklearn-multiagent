from __future__ import annotations

import asyncio

from app import config
from app.agents import doc_agent, tutor_agent
from app.api import chat
from app.llm import spark_client
from app.prompt_templates import _dialog_text
from app.services.knowledge_graph import collect_conversation_topics
from app.services.path_service import plan_conversation_path


def test_colloquial_product_actions_are_understood_before_rag():
    assert chat._product_action("能不能帮我清空聊天记录") == "clear_chat"
    assert chat._product_action("把这段对话删掉，我们重新来") == "clear_chat"
    assert chat._product_action("你能看的到我添加的学习资料是什么吗") == "list_sources"


def test_long_term_context_keeps_more_than_ten_turns():
    conversation = [
        {"role": "user" if index % 2 == 0 else "assistant", "content": f"第{index}轮内容"}
        for index in range(30)
    ]
    rendered = _dialog_text(conversation)
    assert "第0轮内容" in rendered
    assert "第29轮内容" in rendered


def test_quick_audio_actions_do_not_become_knowledge_nodes():
    topics = collect_conversation_topics([
        {"role": "user", "content": "什么是二叉树"},
        {"role": "assistant", "content": "二叉树每个节点最多有两个孩子。"},
        {"role": "user", "content": "换种说法"},
        {"role": "user", "content": "举个例子"},
        {"role": "user", "content": "考考我"},
    ])
    assert [topic["id"] for topic in topics] == ["binary_tree"]


def test_conversation_path_accumulates_all_topics():
    path = plan_conversation_path(
        {"knowledge_mastery": {"binary_tree": 0.7}},
        [
            {"id": "binary_tree", "name": "二叉树", "custom": False, "questions": ["什么是二叉树"]},
            {"id": "custom_topic", "name": "农业知识图谱", "custom": True, "questions": ["怎么建立农业知识图谱", "实体怎么选"]},
            {"id": "sql_basic", "name": "SQL 基础", "custom": False, "questions": ["SELECT 怎么用"]},
        ],
    )
    assert [node["name"] for node in path["nodes"]] == ["二叉树", "农业知识图谱", "SQL 基础"]
    assert len(path["edges"]) == 2
    assert path["generated_by"] == "conversation_history"


def test_interactive_actions_have_distinct_teaching_contracts():
    rephrase = tutor_agent._interaction_request("rephrase", "换种说法", "二叉树互动讲解")
    example = tutor_agent._interaction_request("example", "举个例子", "二叉树互动讲解")
    quiz = tutor_agent._interaction_request("quiz", "考考我", "二叉树互动讲解")
    assert "不得复述原句" in rephrase and "全新的贴切类比" in rephrase
    assert "逐步指出" in example and "不能推出什么" in example
    assert "不要给答案" in quiz and "你先回答" in quiz


def test_answer_scope_allows_a_needed_neighbouring_concept_but_rejects_drift():
    assert tutor_agent._answer_matches_current_question(
        "二叉树中每个节点最多两个孩子；二叉搜索树还额外要求左小右大。",
        "什么是二叉树？",
        "binary_tree",
    )
    assert not tutor_agent._answer_matches_current_question(
        "SQL 的 SELECT 用来选择结果列。",
        "什么是二叉树？",
        "binary_tree",
    )


def test_interactive_narration_is_not_truncated_to_old_320_character_limit():
    markdown = "这是讲解正文。" * 80
    narration = doc_agent._narration_text("测试主题", markdown)
    assert len(narration) > 320
    assert len(narration) <= 900


def test_deepseek_v4_pro_is_the_primary_openai_compatible_model(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-v4-pro")
    config.get_settings.cache_clear()
    captured = {}

    class Message:
        content = "ok"

    class Choice:
        message = Message()

    class Response:
        choices = [Choice()]

    class Completions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return Response()

    class Client:
        chat = type("Chat", (), {"completions": Completions()})()

    monkeypatch.setattr(spark_client, "_deepseek_client", lambda: Client())
    try:
        result = asyncio.run(spark_client.llm_complete("解释知识图谱", role="reasoner"))
    finally:
        config.get_settings.cache_clear()

    assert result == "ok"
    assert captured["model"] == "deepseek-v4-pro"
    assert captured["extra_body"]["thinking"] == {"type": "enabled"}
    assert captured["extra_body"]["reasoning_effort"] == "high"

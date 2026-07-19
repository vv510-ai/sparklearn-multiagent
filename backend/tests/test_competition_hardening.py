from __future__ import annotations

import asyncio
import json
import uuid
from collections import Counter
from pathlib import Path

import pytest

from app.agents import doc_agent, media_agent, mindmap_agent, planner_agent, profile_agent, quiz_agent, tutor_agent
from app.llm import spark_client
from app.safety.guard import safety_filter
from app.services.profile_service import get_profile, merge_profile


def test_guided_tutor_retrieval_uses_planned_kp_and_ignores_old_notes(monkeypatch):
    captured: dict[str, object] = {}

    def fake_retrieve(query: str, **kwargs):
        captured.update(kwargs)
        return [{
            "text": "二叉树遍历包括前序（根左右）、中序（左根右）和后序（左右根）。",
            "source": "《数据结构与算法》讲义",
            "source_id": "seed-binary-tree",
            "chapter": "二叉树",
            "page": 1,
            "citation": "《数据结构与算法》讲义 · 二叉树 p.1",
        }]

    def fail_notes(*args, **kwargs):
        raise AssertionError("first guided lesson must not mix in previous conversation notes")

    monkeypatch.setattr(tutor_agent, "retrieve", fake_retrieve)
    monkeypatch.setattr(tutor_agent, "recent_note_chunks", fail_notes)
    result = asyncio.run(tutor_agent.run({
        "user_id": "demo_user",
        "session_id": "guided-focus",
        "messages": [{"role": "user", "content": "我完全不会二叉树，请从零开始教我前序遍历"}],
        "source_ids": [],
        "knowledge_points": ["binary_tree"],
        "guided_learning": True,
        "student_profile": {},
    }))

    assert captured["kp"] == "binary_tree"
    assert "根 → 左 → 右" in result["answer"]
    assert "工具箱" not in result["answer"]
    assert result["citations"] == ["《数据结构与算法》讲义 · 二叉树 p.1"]


def test_short_graph_question_uses_graph_scope_and_rejects_binary_tree_notes(monkeypatch):
    captured: dict[str, object] = {}

    def fake_retrieve(query: str, **kwargs):
        captured["query"] = query
        captured["retrieve"] = kwargs
        return [{
            "text": "图是一种描述对象及其关系的非线性数据结构，写成 G=(V,E)，V 是顶点集合，E 是边集合。",
            "source": "《数据结构与算法》讲义",
            "source_id": "seed-graph",
            "chapter": "第9章 图",
            "page": 1,
            "kp": "graph_basic,graph_traverse,shortest_path",
            "citation": "《数据结构与算法》讲义 · 第9章 图 p.1",
        }]

    def fake_notes(user_id: str, query: str, **kwargs):
        captured["notes"] = kwargs
        return []

    monkeypatch.setattr(tutor_agent, "retrieve", fake_retrieve)
    monkeypatch.setattr(tutor_agent, "recent_note_chunks", fake_notes)
    monkeypatch.setattr(tutor_agent, "is_demo", lambda: True)
    result = asyncio.run(tutor_agent.run({
        "user_id": "demo_user",
        "session_id": "graph-definition",
        "messages": [{"role": "user", "content": "图是什么"}],
        "source_ids": [],
        "student_profile": {},
    }))

    assert captured["retrieve"]["kp"] == "graph_basic"
    assert captured["notes"]["knowledge_point"] == "graph_basic"
    assert "邻接矩阵" in str(captured["query"])
    assert "G=(V,E)" in result["answer"]
    assert "二叉树" not in result["answer"]
    assert "Dijkstra" not in result["answer"]


def test_studio_graph_quiz_template_resolves_graph_without_model_guessing():
    goal = "请根据当前学习主题、学习者薄弱点和所选资料生成一组巩固测验。\n\n当前学习主题：图是什么"
    result = asyncio.run(planner_agent.run({
        "learning_goal": goal,
        "knowledge_points": [],
        "kinds": ["quiz"],
    }))

    assert result["knowledge_points"] == ["graph_basic"]
    assert result["plan"]["resources"] == [{
        "kind": "quiz",
        "kp": "graph_basic",
        "reason": "按当前学习主题生成，禁止模型改换知识点",
    }]


def test_sql_quiz_uses_sql_seed_questions_and_rejects_binary_tree(monkeypatch):
    sql_chunk = {
        "text": "SELECT 选择列，WHERE 过滤行，GROUP BY 分组，JOIN 按关联键连接表。",
        "source": "《SQL 入门》讲义",
        "chapter": "第12章 SQL 基础",
        "kp": "sql_basic",
        "citation": "《SQL 入门》讲义 · 第12章 SQL 基础 p.1",
    }
    monkeypatch.setattr(quiz_agent, "retrieve", lambda *args, **kwargs: [sql_chunk])
    monkeypatch.setattr(quiz_agent, "is_demo", lambda: True)
    goal = "我刚开始学习 SQL，请讲解 SELECT、WHERE、ORDER BY、GROUP BY 和多表连接。"
    plan = asyncio.run(planner_agent.run({
        "learning_goal": goal,
        "knowledge_points": [],
        "kinds": ["quiz"],
    }))
    state = {
        **plan,
        "learning_goal": goal,
        "kinds": ["quiz"],
        "student_profile": {},
        "source_ids": [],
    }

    result = asyncio.run(quiz_agent.run(state))
    resource = next(iter(result["generated_resources"].values()))
    stems = [question["stem"] for question in resource["payload"]["questions"]]

    assert resource["kp"] == "sql_basic"
    assert len(stems) == 8
    assert any("SQL" in stem or "WHERE" in stem for stem in stems)
    assert all("二叉树" not in stem for stem in stems)


def test_custom_topic_uses_general_topic_mode_without_retrieving_binary_tree(monkeypatch):
    monkeypatch.setattr(
        tutor_agent,
        "retrieve",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not retrieve")),
    )
    monkeypatch.setattr(tutor_agent, "is_demo", lambda: True)

    result = asyncio.run(tutor_agent.run({
        "user_id": "unknown-topic",
        "session_id": "unknown-topic",
        "messages": [{"role": "user", "content": "请从零讲解 Rust 所有权"}],
        "source_ids": [],
        "student_profile": {},
    }))

    assert "Rust 所有权" in result["answer"]
    assert "主题已锁定" not in result["answer"]
    assert "旧主题" not in result["answer"]
    assert result["safety_flags"] == []


def test_tutor_switches_from_binary_tree_to_queue_without_reopening(monkeypatch):
    captured: dict[str, object] = {}

    def fake_retrieve(query: str, **kwargs):
        captured["query"] = query
        captured.update(kwargs)
        return [{
            "text": "队列是一种先进先出（FIFO）的线性数据结构。",
            "source": "《数据结构与算法》讲义",
            "source_id": "seed-queue",
            "chapter": "第3章 栈与队列",
            "page": 2,
            "kp": "queue",
            "citation": "《数据结构与算法》讲义 · 第3章 栈与队列 p.2",
        }]

    monkeypatch.setattr(tutor_agent, "retrieve", fake_retrieve)
    monkeypatch.setattr(tutor_agent, "recent_note_chunks", lambda *args, **kwargs: [])
    monkeypatch.setattr(tutor_agent, "is_demo", lambda: True)
    result = asyncio.run(tutor_agent.run({
        "user_id": "topic-switch-user",
        "session_id": "same-page",
        "messages": [{"role": "user", "content": "什么是队列"}],
        "conversation": [
            {"role": "user", "content": "什么是完全二叉树"},
            {"role": "assistant", "content": "完全二叉树按层从左到右排列节点。"},
            {"role": "user", "content": "什么是队列"},
        ],
        "topic_label": "完全二叉树",
        "source_ids": [],
        "student_profile": {},
    }))

    assert captured["kp"] == "queue"
    assert "课程知识点：队列" in str(captured["query"])
    assert "先进先出" in result["answer"]
    assert "完全二叉树" not in result["answer"]


def test_referential_followup_uses_most_recent_switched_topic(monkeypatch):
    captured: dict[str, object] = {}

    def fake_retrieve(query: str, **kwargs):
        captured.update(kwargs)
        return [{
            "text": "队列从队尾加入元素，从队头移除元素，因此保持先进先出。",
            "source": "《数据结构与算法》讲义",
            "source_id": "seed-queue",
            "chapter": "第3章 栈与队列",
            "page": 2,
            "kp": "queue",
            "citation": "《数据结构与算法》讲义 · 第3章 栈与队列 p.2",
        }]

    monkeypatch.setattr(tutor_agent, "retrieve", fake_retrieve)
    monkeypatch.setattr(tutor_agent, "recent_note_chunks", lambda *args, **kwargs: [])
    monkeypatch.setattr(tutor_agent, "is_demo", lambda: True)
    asyncio.run(tutor_agent.run({
        "user_id": "topic-switch-user",
        "session_id": "same-page",
        "messages": [{"role": "user", "content": "它为什么这样工作？"}],
        "conversation": [
            {"role": "user", "content": "什么是完全二叉树"},
            {"role": "assistant", "content": "完全二叉树按层从左到右排列节点。"},
            {"role": "user", "content": "什么是队列"},
            {"role": "assistant", "content": "队列遵循先进先出。"},
            {"role": "user", "content": "它为什么这样工作？"},
        ],
        "topic_label": "完全二叉树",
        "source_ids": [],
        "student_profile": {},
    }))

    assert captured["kp"] == "queue"


def test_custom_topic_switch_does_not_fall_back_to_notebook_topic(monkeypatch):
    monkeypatch.setattr(
        tutor_agent,
        "retrieve",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("custom topic must not retrieve old course topic")),
    )
    monkeypatch.setattr(tutor_agent, "is_demo", lambda: True)

    result = asyncio.run(tutor_agent.run({
        "user_id": "topic-switch-user",
        "session_id": "same-page",
        "messages": [{"role": "user", "content": "什么是量子纠缠"}],
        "conversation": [
            {"role": "user", "content": "什么是完全二叉树"},
            {"role": "assistant", "content": "完全二叉树按层从左到右排列节点。"},
            {"role": "user", "content": "什么是量子纠缠"},
        ],
        "topic_label": "完全二叉树",
        "source_ids": [],
        "student_profile": {},
    }))

    assert "量子纠缠" in result["answer"]
    assert "完全二叉树" not in result["answer"]
    assert "锁定" not in result["answer"]


def test_foreign_trade_topic_plans_as_custom_topic_for_every_studio_tool():
    result = asyncio.run(planner_agent.run({
        "learning_goal": "请根据当前学习主题生成资源。当前学习主题：我想学外贸函电的知识",
        "topic_label": "我想学外贸函电的知识",
        "knowledge_points": [],
        "kinds": ["doc", "mindmap", "quiz", "video"],
    }))

    assert result["knowledge_points"] == ["custom_topic"]
    assert result["topic_label"] == "外贸函电"
    assert result["custom_topic"] is True
    assert {item["kp"] for item in result["plan"]["resources"]} == {"custom_topic"}
    assert all("二叉树" not in str(item) for item in result["plan"]["resources"])


def test_custom_topic_quiz_offline_fallback_stays_on_topic(monkeypatch):
    monkeypatch.setattr(
        quiz_agent,
        "retrieve",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("custom topic must not query course RAG")),
    )
    monkeypatch.setattr(quiz_agent, "is_demo", lambda: True)

    result = asyncio.run(quiz_agent.run({
        "learning_goal": "我想学外贸函电的知识",
        "topic_label": "我想学外贸函电的知识",
        "knowledge_points": ["custom_topic"],
        "kinds": ["quiz"],
        "source_ids": [],
        "student_profile": {},
    }))
    resource = next(iter(result["generated_resources"].values()))
    combined = " ".join(question["stem"] for question in resource["payload"]["questions"])

    assert resource["title"].startswith("外贸函电·")
    assert len(resource["payload"]["questions"]) == 8
    assert "外贸函电" in combined
    assert "二叉树" not in combined


def test_custom_topic_doc_and_mindmap_stay_on_topic_without_course_rag(monkeypatch):
    def fail_retrieve(*args, **kwargs):
        raise AssertionError("custom topic must not query course RAG")

    monkeypatch.setattr(doc_agent, "retrieve", fail_retrieve)
    monkeypatch.setattr(mindmap_agent, "retrieve", fail_retrieve)
    monkeypatch.setattr(doc_agent, "is_demo", lambda: True)
    monkeypatch.setattr(mindmap_agent, "is_demo", lambda: True)
    state = {
        "learning_goal": "我想学外贸函电的知识",
        "topic_label": "我想学外贸函电的知识",
        "knowledge_points": ["custom_topic"],
        "source_ids": [],
        "student_profile": {},
        "skip_multimodal": True,
    }

    doc_result = asyncio.run(doc_agent.run({**state, "kinds": ["doc"]}))
    map_result = asyncio.run(mindmap_agent.run({**state, "kinds": ["mindmap"]}))
    doc = next(iter(doc_result["generated_resources"].values()))
    mindmap = next(iter(map_result["generated_resources"].values()))

    assert doc["title"].startswith("外贸函电·")
    assert mindmap["title"].startswith("外贸函电·")
    assert "外贸函电" in doc["payload"]["markdown"]
    assert "外贸函电" in mindmap["payload"]["markmap"]
    assert "二叉树" not in doc["payload"]["markdown"] + mindmap["payload"]["markmap"]


def test_custom_topic_video_uses_generic_fallback_visual_not_binary_tree(monkeypatch):
    async def unavailable(*args, **kwargs):
        return {"ok": False, "degraded": True, "data": {}, "error": "disabled"}

    monkeypatch.setattr(media_agent, "retrieve", lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("custom topic must not query course RAG")
    ))
    monkeypatch.setattr(media_agent, "is_demo", lambda: True)
    monkeypatch.setattr(media_agent.multimodal_gateway, "video_create", unavailable)
    monkeypatch.setattr(media_agent.multimodal_gateway, "tts", unavailable)
    monkeypatch.setattr(media_agent.multimodal_gateway, "text_to_image", unavailable)

    result = asyncio.run(media_agent.run({
        "learning_goal": "我想学外贸函电的知识",
        "topic_label": "我想学外贸函电的知识",
        "knowledge_points": ["custom_topic"],
        "kinds": ["video"],
        "source_ids": [],
        "session_id": "foreign-trade-video",
    }))
    video = next(iter(result["generated_resources"].values()))
    rendered = video["title"] + str(video["payload"])

    assert video["title"].startswith("外贸函电")
    assert "外贸函电" in rendered
    assert "二叉树" not in rendered


def test_short_definition_unwraps_model_json_self_check():
    answer = tutor_agent._normalize_tutor_answer(  # noqa: SLF001
        """```json
        {"是什么":"图由顶点和边组成。","为什么":"不应出现在短定义回答里。","易错表现":"不应展开。"}
        ```""",
        "图是什么",
        has_context=True,
    )

    assert answer == "图由顶点和边组成。 [^1]"


def test_stream_can_disable_generic_mock_fallback(monkeypatch):
    class BrokenCompletions:
        def create(self, **kwargs):
            raise RuntimeError("model unavailable")

    class BrokenClient:
        def __init__(self):
            self.chat = type("Chat", (), {"completions": BrokenCompletions()})()

    monkeypatch.setattr(spark_client, "is_demo", lambda: False)
    monkeypatch.setattr(spark_client, "_client", lambda x2=False: BrokenClient())

    async def collect():
        return [
            token async for token in spark_client.llm_stream(
                "TASK=tutor\n图是什么",
                allow_model_fallback=False,
                allow_mock_fallback=False,
            )
        ]

    with pytest.raises(RuntimeError, match="model unavailable"):
        asyncio.run(collect())


def test_guided_mindmap_only_expands_the_current_topic():
    assert mindmap_agent._outline_for_scope("binary_tree", [], guided=True) == [
        ("当前主题", "binary_tree")
    ]
    assert len(mindmap_agent._outline_for_scope("binary_tree", [])) > 1


def test_guided_mindmap_points_follow_the_requested_traversal():
    points = mindmap_agent._guided_goal_points(
        "我完全不会二叉树，请从零开始教我前序遍历",
        [{"text": "前序遍历采用根左右顺序。"}],
    )
    assert points[0] == "顺序：根 → 左 → 右"
    assert not any("BST" in point or "删除" in point for point in points)


def test_profile_patch_rejects_inferred_traits_without_evidence():
    patch = profile_agent._gate_profile_patch(
        {
            "cognitive_style": "视觉型",
            "goal": "应试",
            "error_prone": ["遍历顺序混淆"],
            "difficulty_pref": "循序渐进",
            "metacognition": 0.2,
            "evidence": "模型推断",
        },
        "user: 我完全不会二叉树，请从零开始教我前序遍历",
        [],
    )

    assert patch == {"difficulty_pref": "循序渐进", "evidence": "模型推断"}


def test_noop_profile_evidence_does_not_increment_version():
    user_id = f"profile-noop-{uuid.uuid4().hex}"
    before = get_profile(user_id)
    after = merge_profile(user_id, {
        "difficulty_pref": before["difficulty_pref"],
        "evidence": "零基础表述",
    })

    assert after["_version"] == before["_version"]
    assert after["evidence"] == before["evidence"]


def test_safety_filter_exposes_consistent_passed_and_safe_fields():
    result = safety_filter("请帮我考试作弊")
    assert result["passed"] is False
    assert result["safe"] is False


def test_local_blocklist_is_loaded_from_versioned_file():
    result = safety_filter("不要购买作弊工具，也不要找人替考")
    assert result["passed"] is False
    assert {"作弊工具", "替考"}.issubset(set(result["hits"]))


def test_seed_quiz_meets_final_course_coverage_floor():
    path = Path(__file__).resolve().parents[1] / "app" / "data" / "seed_quiz.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    questions = payload["questions"]
    counts = Counter(question["kp"] for question in questions)

    assert len(questions) == 49
    assert counts["graph_basic"] >= 3
    assert counts["graph_traverse"] >= 3
    for kp in ("binary_tree", "bst", "heap", "sorting_adv"):
        assert counts[kp] >= 5
    assert all(
        len(question.get("options", [])) == 4
        for question in questions
        if question["type"] == "single"
    )

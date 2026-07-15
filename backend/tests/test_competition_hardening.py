from __future__ import annotations

import asyncio
import uuid

import pytest

from app.agents import mindmap_agent, profile_agent, tutor_agent
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

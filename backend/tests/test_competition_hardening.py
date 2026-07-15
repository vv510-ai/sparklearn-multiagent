from __future__ import annotations

import asyncio
import uuid

from app.agents import mindmap_agent, profile_agent, tutor_agent
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

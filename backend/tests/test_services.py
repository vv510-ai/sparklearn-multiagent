"""单元测试:BKT / 知识图谱 / 路径规划(离线可跑,无外部依赖)。"""
import asyncio
import os
import sys
import json
import re
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tests._stubs import install  # noqa: E402

install()

from app.services.bkt import bkt_update, mastery_level  # noqa: E402
from app.services.knowledge_graph import (all_kp_ids, load_kg, prerequisites,  # noqa: E402
                                          canonical_kp_id, topological_order, unlockable)
from app.services.path_service import (  # noqa: E402
    is_current_course_path,
    plan_conversation_path,
    plan_path,
)
from app.services.profile_service import default_profile, onboarding_patch, sanitize_profile_patch  # noqa: E402
from app.rag.ingest import ingest_corpus, load_all_chunks  # noqa: E402
from app.rag.retriever import _format_citation  # noqa: E402
from app.rag.vector_store import get_store  # noqa: E402
from app.agents.planner_agent import _kp_from_goal  # noqa: E402
from app.api import path as path_api  # noqa: E402


def test_bkt_monotonic():
    p = 0.3
    for _ in range(6):
        p2 = bkt_update(p, True)
        assert p2 > p, "连续答对掌握度应单调上升"
        p = p2
    assert p > 0.8 and mastery_level(p) == "掌握"
    q = bkt_update(0.9, False)
    assert q < 0.9, "答错应下降"
    assert 0.0 <= q <= 1.0


def test_kg_topology():
    ids = all_kp_ids()
    assert len(ids) >= 12
    order = topological_order()
    pos = {kp: i for i, kp in enumerate(order)}
    for kp in ids:
        for pre in prerequisites(kp):
            assert pos[pre] < pos[kp], f"先修 {pre} 必须排在 {kp} 之前"
    # complexity 无先修,任何画像下都应可解锁
    mastery = {k: 0.0 for k in ids}
    assert "complexity" in unlockable(mastery)


def test_course_assets_share_one_knowledge_taxonomy():
    """A course-only graph must not silently absorb another course's assets."""
    kg = load_kg()
    ids = set(all_kp_ids())
    assert kg["course_id"] == "data_structures_algorithms"
    assert kg["course"] == "数据结构与算法"
    assert "sql_basic" not in ids
    detail_nodes = [
        detail
        for node in kg["nodes"].values()
        for detail in node.get("subtopics") or []
    ]
    detail_ids = {detail["id"] for detail in detail_nodes}
    assert len(detail_nodes) >= 50
    assert len(detail_ids) == len(detail_nodes)
    assert all(edge["from"] in ids | detail_ids for edge in kg["detail_edges"])
    assert all(edge["to"] in ids | detail_ids for edge in kg["detail_edges"])

    quiz_file = Path(__file__).parents[1] / "app" / "data" / "seed_quiz.json"
    quiz_rows = json.loads(quiz_file.read_text(encoding="utf-8"))["questions"]
    assert {str(row.get("kp") or "") for row in quiz_rows} <= ids

    corpus_dir = Path(__file__).parents[1] / "app" / "data" / "seed_corpus"
    corpus_kps = set()
    for source in corpus_dir.glob("*.md"):
        match = re.search(r"(?m)^kp:\s*([^\r\n]+)", source.read_text(encoding="utf-8"))
        if match:
            corpus_kps.update(
                kp.strip() for kp in match.group(1).split(",") if kp.strip()
            )
    assert corpus_kps <= ids


def test_planner_prefers_course_concept_named_in_goal():
    ids = all_kp_ids()
    assert _kp_from_goal("我想系统掌握递归与分治", ids) == "recursion"
    assert _kp_from_goal("先学习复杂度分析，再看排序", ids) == "complexity"
    assert _kp_from_goal("图是什么？", ids) == "graph_basic"
    assert _kp_from_goal("什么是图", ids) == "graph_basic"
    assert _kp_from_goal("请解释 Dijkstra 算法", ids) == "shortest_path"
    assert _kp_from_goal("生成一张二叉树思维导图", ids) == "binary_tree"
    assert _kp_from_goal(
        "请根据当前学习主题生成巩固测验。当前学习主题：图是什么", ids
    ) == "graph_basic"
    assert _kp_from_goal(
        "我刚开始学习 SQL，请依次讲解 SELECT、WHERE、GROUP BY 和多表连接", ids
    ) is None


def test_plan_path_thresholds():
    prof = default_profile()
    prof["knowledge_mastery"]["complexity"] = 0.95          # 已掌握
    prof["knowledge_mastery"]["array"] = 0.65               # 先修达标
    path = plan_path(prof, goal_kps=["binary_tree"])
    by = {n["id"]: n for n in path["nodes"]}
    assert by["complexity"]["status"] == "done"
    assert by["array"]["status"] in ("ready", "done")
    assert path.get("next_kp") in by, "应推荐一个存在的下一知识点"
    assert by[path["next_kp"]]["status"] == "ready"
    # 边与节点一致
    kp_set = set(by)
    for e in path["edges"]:
        assert e["from"] in kp_set and e["to"] in kp_set
    assert path["course"] == "数据结构与算法"
    assert path["course_id"] == "data_structures_algorithms"
    assert sum(len(node.get("subtopics") or []) for node in path["nodes"]) >= 50
    assert path["detail_edges"]
    assert is_current_course_path(path)
    stale = {**path, "nodes": [*path["nodes"], {"id": "sql_basic"}]}
    assert not is_current_course_path(stale)


def test_conversation_topic_map_is_not_a_complete_course_path():
    conversation_path = plan_conversation_path(
        default_profile(),
        [
            {
                "id": "binary_tree",
                "name": "二叉树",
                "custom": False,
                "questions": ["什么是二叉树？"],
            },
            {
                "id": "advanced_sort",
                "name": "高级排序",
                "custom": False,
                "questions": ["高级排序有哪些？"],
            },
        ],
    )
    assert len(conversation_path["nodes"]) == 2
    assert conversation_path["course_id"] == "conversation_history"
    assert not is_current_course_path(conversation_path)


def test_path_api_replaces_a_saved_conversation_map_with_the_full_course(monkeypatch):
    conversation_path = plan_conversation_path(
        default_profile(),
        [{
            "id": "binary_tree",
            "name": "二叉树",
            "custom": False,
            "questions": ["什么是二叉树？"],
        }],
    )
    saved: list[dict] = []
    monkeypatch.setattr(path_api, "ensure_user", lambda _user_id: None)
    monkeypatch.setattr(path_api, "get_path", lambda _user_id: conversation_path)
    monkeypatch.setattr(path_api, "get_profile", lambda _user_id: default_profile())
    monkeypatch.setattr(path_api, "save_path", lambda _user_id, path: saved.append(path))

    # The unscoped legacy course retains its full graph. Notebook requests now
    # require real ownership and use their own graph (covered by learning-space tests).
    result = asyncio.run(path_api.read_path(user_id="learner", notebook_id=""))

    assert result["course_id"] == "data_structures_algorithms"
    assert len(result["nodes"]) == len(all_kp_ids())
    assert set(node["id"] for node in result["nodes"]) == set(all_kp_ids())
    assert saved == [result]


def test_profile_patch_and_kp_normalization():
    assert canonical_kp_id("complexity") == "complexity"
    assert canonical_kp_id("complexity(复杂度分析)") == "complexity"
    assert canonical_kp_id("degree_of_a_node") is None

    patch = sanitize_profile_patch({
        "knowledge_mastery": {"complexity(复杂度分析)": 1.2, "unknown": 0.9},
        "error_prone": "概念混淆",
        "difficulty_pref": "挑战型",
        "resource_pref": {"mindmap": 31, "quiz": -1},
        "metacognition": 2,
        "unexpected": "drop me",
    })
    assert patch["knowledge_mastery"] == {"complexity": 1.0}
    assert patch["error_prone"] == ["概念混淆"]
    assert patch["difficulty_pref"] == "挑战式"
    assert patch["resource_pref"] == {"mindmap": 1.0, "quiz": 0.0}
    assert patch["metacognition"] == 1.0
    assert "unexpected" not in patch


def test_onboarding_answers_change_starting_path():
    beginner = onboarding_patch({
        "topic": "树与图",
        "current_level": "刚开始接触",
        "goal": "兴趣",
        "weekly_minutes": 60,
        "style": "图示和例子",
        "materials_status": "暂时没有",
    })
    experienced = onboarding_patch({
        "topic": "树与图",
        "current_level": "能做基础题",
        "goal": "竞赛",
        "weekly_minutes": 420,
        "style": "先做题再讲解",
        "materials_status": "已有资料",
    })
    beginner_path = plan_path(beginner, generated_by="onboarding")
    experienced_path = plan_path(experienced, generated_by="onboarding")
    assert beginner["onboarding_completed"] is True
    assert beginner["focus_kps"] == ["binary_tree", "bst", "graph_basic", "graph_traverse"]
    assert "knowledge_mastery" not in beginner and "knowledge_mastery" not in experienced
    assert "cognitive_style" not in beginner and "focus" not in beginner["pace"]
    assert beginner["resource_pref"] != experienced["resource_pref"]
    assert beginner["pace"]["weekly_minutes"] == 60
    assert experienced["pace"]["weekly_minutes"] == 420
    assert beginner_path["nodes"] and experienced_path["nodes"]


def test_extra_sources_ingest_and_citation(monkeypatch):
    from app.rag import ingest
    monkeypatch.setattr(ingest, "EXTRA_SOURCES_DIR", Path(__file__).parent / "fixtures")
    chunks = load_all_chunks()
    sample = next((c for c in chunks if c.get("source_id") == "video_binary_tree_intro"), None)
    assert sample is not None, "应读取 extra_sources 里的视频链接样例"
    assert sample["source_type"] == "video_link"
    assert sample["kp"] == "binary_tree"
    assert sample["url"].endswith("/binary-tree-intro")
    assert "video_link" in _format_citation(sample)
    assert "https://example.com/resources/binary-tree-intro" in _format_citation(sample)

    total = ingest_corpus(force=True)
    assert total >= len(chunks)
    assert get_store().count() == total


if __name__ == "__main__":
    for fn in (
        test_bkt_monotonic,
        test_kg_topology,
        test_plan_path_thresholds,
        test_extra_sources_ingest_and_citation,
    ):
        fn()
        print(f"{fn.__name__} ... ok")
    print("ALL SERVICE TESTS PASSED")

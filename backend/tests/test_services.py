"""单元测试:BKT / 知识图谱 / 路径规划(离线可跑,无外部依赖)。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tests._stubs import install  # noqa: E402

install()

from app.services.bkt import bkt_update, mastery_level  # noqa: E402
from app.services.knowledge_graph import (all_kp_ids, prerequisites,  # noqa: E402
                                          canonical_kp_id, topological_order, unlockable)
from app.services.path_service import plan_path  # noqa: E402
from app.services.profile_service import default_profile, sanitize_profile_patch  # noqa: E402
from app.rag.ingest import ingest_corpus, load_all_chunks  # noqa: E402
from app.rag.retriever import _format_citation  # noqa: E402
from app.rag.vector_store import get_store  # noqa: E402
from app.agents.planner_agent import _kp_from_goal  # noqa: E402


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


def test_planner_prefers_course_concept_named_in_goal():
    ids = all_kp_ids()
    assert _kp_from_goal("我想系统掌握递归与分治", ids) == "recursion"
    assert _kp_from_goal("先学习复杂度分析，再看排序", ids) == "complexity"
    assert _kp_from_goal("图是什么？", ids) == "graph_basic"
    assert _kp_from_goal("什么是图", ids) == "graph_basic"
    assert _kp_from_goal("请解释 Dijkstra 算法", ids) == "shortest_path"
    assert _kp_from_goal("生成一张二叉树思维导图", ids) == "binary_tree"


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


def test_extra_sources_ingest_and_citation():
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

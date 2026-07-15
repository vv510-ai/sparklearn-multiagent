"""《数据结构与算法》知识图谱:手工构建的知识点节点 + 先修依赖边(DAG)。

用途:① Path Agent 拓扑排序生成个性化路径;② 画像 knowledge_mastery 的键空间;
③ 前端 /path 页面可视化。数据文件 data/knowledge_graph.json 可由教研侧维护。
"""
from __future__ import annotations

import json
import re
from functools import lru_cache

from ..config import DATA_DIR

KG_FILE = DATA_DIR / "knowledge_graph.json"

_KP_ALIASES: dict[str, tuple[str, ...]] = {
    "complexity": ("时间复杂度", "空间复杂度", "大O", "复杂度"),
    "array": ("数组", "顺序表"),
    "linked_list": ("链表",),
    "stack": ("栈",),
    "queue": ("队列",),
    "recursion": ("递归", "分治"),
    "sorting_basic": ("基础排序", "冒泡排序", "插入排序", "选择排序"),
    "sorting_adv": ("高级排序", "归并排序", "快速排序", "快排", "堆排序"),
    "binary_tree": ("二叉树",),
    "bst": ("二叉搜索树", "二叉查找树", "BST"),
    "heap": ("优先队列", "堆"),
    "hash": ("哈希表", "散列表", "哈希"),
    "graph_basic": (
        "数据结构中的图", "图的基础", "图结构", "图论", "有向图", "无向图", "邻接矩阵", "邻接表",
    ),
    "graph_traverse": ("图遍历", "广度优先", "深度优先", "BFS", "DFS"),
    "shortest_path": ("最短路径", "Dijkstra", "Bellman-Ford", "Floyd"),
    "dp": ("动态规划", "DP"),
}

_STANDALONE_GRAPH_RE = re.compile(
    r"(?:^|请问|什么是|学习|了解|讲讲|解释|教我)图"
    r"(?:是什么|的定义|的概念|怎么表示|如何表示|有哪些|[？?。！!]|$)",
    re.IGNORECASE,
)


@lru_cache
def load_kg() -> dict:
    data = json.loads(KG_FILE.read_text(encoding="utf-8"))
    nodes = {n["id"]: n for n in data["nodes"]}
    indeg = {nid: 0 for nid in nodes}
    adj: dict[str, list[str]] = {nid: [] for nid in nodes}
    for e in data["edges"]:
        adj[e["from"]].append(e["to"])
        indeg[e["to"]] += 1
    return {"nodes": nodes, "edges": data["edges"], "adj": adj, "indeg": indeg}


def all_kp_ids() -> list[str]:
    return list(load_kg()["nodes"].keys())


def kp_name(kp_id: str) -> str:
    return load_kg()["nodes"].get(kp_id, {}).get("name", kp_id)


def canonical_kp_id(value: str | None) -> str | None:
    """Return a knowledge-graph id, accepting the legacy ``id(name)`` form."""
    raw = str(value or "").strip().replace("（", "(").replace("）", ")")
    nodes = load_kg()["nodes"]
    if raw in nodes:
        return raw
    if raw.endswith(")") and "(" in raw:
        kp_id, label = raw[:-1].split("(", 1)
        kp_id, label = kp_id.strip(), label.strip()
        if kp_id in nodes and label == str(nodes[kp_id].get("name", "")).strip():
            return kp_id
    return None


def infer_kp_id(text: str, kp_ids: list[str] | None = None) -> str | None:
    """从自然语言中识别课程知识点，短词只在明确的学习语境中命中。"""
    raw = str(text or "").casefold()
    compact = re.sub(r"\s+", "", raw)
    candidates = set(kp_ids or all_kp_ids())
    matches: list[tuple[int, int, str]] = []

    for kp in candidates:
        node = load_kg()["nodes"].get(kp, {})
        labels = {
            kp.replace("_", " "),
            str(node.get("name") or ""),
            *_KP_ALIASES.get(kp, ()),
        }
        for label in labels:
            normalized = re.sub(r"\s+", "", str(label or "").casefold())
            if not normalized:
                continue
            position = compact.find(normalized)
            if position >= 0:
                matches.append((position, -len(normalized), kp))

    if "graph_basic" in candidates:
        graph_match = _STANDALONE_GRAPH_RE.search(compact)
        if graph_match:
            matches.append((graph_match.start(), -1, "graph_basic"))

    return min(matches)[2] if matches else None


def kp_retrieval_text(kp_id: str) -> str:
    """用于短问题检索扩展，避免单字概念在 hash embedding 中丢失。"""
    node = load_kg()["nodes"].get(kp_id, {})
    parts = [str(node.get("name") or ""), str(node.get("desc") or "")]
    parts.extend(_KP_ALIASES.get(kp_id, ()))
    return " ".join(part for part in parts if part).strip()


def prerequisites(kp_id: str) -> list[str]:
    kg = load_kg()
    return [e["from"] for e in kg["edges"] if e["to"] == kp_id]


def topological_order() -> list[str]:
    """Kahn 拓扑排序;同层按 difficulty 升序,保证"循序渐进"默认顺序。"""
    kg = load_kg()
    indeg = dict(kg["indeg"])
    ready = sorted([n for n, d in indeg.items() if d == 0],
                   key=lambda x: kg["nodes"][x].get("difficulty", 1))
    order: list[str] = []
    while ready:
        cur = ready.pop(0)
        order.append(cur)
        for nxt in kg["adj"][cur]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                ready.append(nxt)
        ready.sort(key=lambda x: kg["nodes"][x].get("difficulty", 1))
    return order


def unlockable(mastery: dict[str, float], threshold: float = 0.6) -> list[str]:
    """先修均达标即解锁(供路径规划筛选 ready 节点)。"""
    out = []
    for kp in all_kp_ids():
        pres = prerequisites(kp)
        if all(mastery.get(p, 0.0) >= threshold for p in pres):
            out.append(kp)
    return out

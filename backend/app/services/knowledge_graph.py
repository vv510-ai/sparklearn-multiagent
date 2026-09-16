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
CUSTOM_TOPIC_KP = "custom_topic"

_KP_ALIASES: dict[str, tuple[str, ...]] = {
    "complexity": ("时间复杂度", "空间复杂度", "大O", "复杂度"),
    "array": ("数组", "顺序表"),
    "linked_list": ("链表",),
    "stack": ("栈",),
    "queue": ("队列",),
    "recursion": ("递归", "分治"),
    "sorting_basic": ("排序", "基础排序", "冒泡排序", "插入排序", "选择排序"),
    "sorting_adv": ("高级排序", "归并排序", "快速排序", "快排", "堆排序", "pivot", "基准", "三数取中"),
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
    r"(?:^|请问|什么是|学习|了解|讲讲|解释|教我|(?:当前)?(?:学习)?主题[：:]?)图"
    r"(?:是什么|的定义|的概念|怎么(?:表示|学|学习|入门|开始|办)|"
    r"如何(?:表示|学|学习|入门|开始)|从哪里开始|有哪些|[？?。！!]|$)",
    re.IGNORECASE,
)

_TOPIC_INTRO_PATTERNS = (
    re.compile(r"^(?:请|能否|可以)?(?:先)?(?:给我)?(?:解释|介绍|讲解|讲讲|说说|教我|学习|了解)(?:一下)?\s*(?P<topic>[^，。！？?\n]+)", re.IGNORECASE),
    re.compile(r"^(?:什么是|何为)\s*(?P<topic>[^，。！？?\n]+)", re.IGNORECASE),
    re.compile(
        r"^(?P<topic>[^，。！？?\n]{2,60}?)(?:是什么|的定义(?:是什么)?|怎么(?:工作|运行|实现|使用|学习|理解)?|如何(?:工作|运行|实现|使用|学习|理解)?|为什么)",
        re.IGNORECASE,
    ),
)
_CONTEXT_DEPENDENT_TOPIC_RE = re.compile(
    r"^(?:它|这个|这(?:个|种)?|那个|那(?:个|种)?|其|上面|前面|刚才|继续|再|然后|为什么(?:会|要)?(?:这样)?[？?]?$|怎么(?:会)?(?:这样)?[？?]?$)",
    re.IGNORECASE,
)
_PRODUCT_HELP_RE = re.compile(
    r"(?:你能|可以)(?:帮助我|帮我)?(?:(?:做|干)什么|干嘛)|怎么使用|如何使用|^help$"
    r"|(?:清空|清除|删除|重置).*(?:聊天|对话|记录)"
    r"|(?:看见|看(?:得|的)?到|读取|知道|识别).*(?:上传|添加|选中|选择).*(?:资料|文件)",
    re.IGNORECASE,
)
_INTERACTION_ACTION_RE = re.compile(
    r"^(?:换种说法|换个说法|换一种说法|举个例子|再举个例子|考考我|出道题)$",
    re.IGNORECASE,
)
_ARTIFACT_REQUEST_RE = re.compile(
    r"^(?:请)?(?:把|将)?(?:上面|前面|刚才|本次|当前|这些)?[^。！？?]{0,24}"
    r"(?:生成|整理|制作|做成|画|创建)[^。！？?]{0,24}"
    r"(?:思维导图|框架导图|知识导图|学习笔记|笔记|测验|PPT|课件|视频|讲解)",
    re.IGNORECASE,
)


@lru_cache
def _load_builtin_kg() -> dict:
    data = json.loads(KG_FILE.read_text(encoding="utf-8"))
    nodes = {n["id"]: n for n in data["nodes"]}
    if len(nodes) != len(data["nodes"]):
        raise ValueError("knowledge graph contains duplicate node ids")
    detail_ids: set[str] = set()
    for node in data["nodes"]:
        for detail in node.get("subtopics") or []:
            detail_id = str(detail.get("id") or "").strip()
            if not detail_id or detail_id in nodes or detail_id in detail_ids:
                raise ValueError(f"knowledge graph contains invalid detail node id: {detail_id}")
            detail_ids.add(detail_id)
    indeg = {nid: 0 for nid in nodes}
    adj: dict[str, list[str]] = {nid: [] for nid in nodes}
    for e in data["edges"]:
        if e["from"] not in nodes or e["to"] not in nodes:
            raise ValueError(f"knowledge graph edge references unknown node: {e}")
        adj[e["from"]].append(e["to"])
        indeg[e["to"]] += 1
    detail_edges = data.get("detail_edges") or []
    known_display_ids = set(nodes) | detail_ids
    for edge in detail_edges:
        if edge.get("from") not in known_display_ids or edge.get("to") not in known_display_ids:
            raise ValueError(f"knowledge graph detail edge references unknown node: {edge}")
    return {
        "course_id": str(data.get("course_id") or "").strip(),
        "course": str(data.get("course") or "").strip(),
        "version": int(data.get("version") or 1),
        "nodes": nodes,
        "edges": data["edges"],
        "detail_edges": detail_edges,
        "detail_node_count": len(detail_ids),
        "adj": adj,
        "indeg": indeg,
    }


def load_kg() -> dict:
    from .learning_scope import current_space
    space = current_space()
    return space["graph"] if space else _load_builtin_kg()


load_kg.cache_clear = _load_builtin_kg.cache_clear


def all_kp_ids() -> list[str]:
    return list(load_kg()["nodes"].keys())


def kp_name(kp_id: str) -> str:
    if kp_id == CUSTOM_TOPIC_KP:
        return "自定义主题"
    return load_kg()["nodes"].get(kp_id, {}).get("name", kp_id)


def canonical_kp_id(value: str | None) -> str | None:
    """Return a knowledge-graph id, accepting the legacy ``id(name)`` form."""
    raw = str(value or "").strip().replace("（", "(").replace("）", ")")
    if raw == CUSTOM_TOPIC_KP:
        return CUSTOM_TOPIC_KP
    nodes = load_kg()["nodes"]
    if raw in nodes:
        return raw
    if raw.endswith(")") and "(" in raw:
        kp_id, label = raw[:-1].split("(", 1)
        kp_id, label = kp_id.strip(), label.strip()
        if kp_id in nodes and label == str(nodes[kp_id].get("name", "")).strip():
            return kp_id
    return None


_TOPIC_MARKER_RE = re.compile(r"当前学习主题\s*[：:]\s*([^\r\n]+)", re.IGNORECASE)
_TOPIC_PREFIXES = (
    "请用完全零基础、由浅入深的方式教我", "请从零开始教我", "请从零讲解",
    "我刚开始学习", "我想要学习", "我想学习", "我想学", "想学习", "学习", "了解",
)
_TOPIC_SUFFIXES = (
    "从哪里开始", "怎么学习", "如何学习", "怎么入门", "如何入门",
    "怎么开始", "如何开始", "怎么学", "如何学", "怎么办",
    "方面的知识", "相关知识", "的知识", "是什么", "入门",
)


def clean_topic_label(value: str | None) -> str:
    """Extract a short notebook topic without silently mapping it to a course KP."""
    raw = " ".join(str(value or "").strip().split())
    marker = _TOPIC_MARKER_RE.search(raw)
    if marker:
        raw = marker.group(1).strip()
    raw = raw.strip("【】[]《》<>：:，,。.!！?？;； \t\r\n")
    changed = True
    while changed and raw:
        changed = False
        for prefix in _TOPIC_PREFIXES:
            if raw.startswith(prefix):
                raw = raw[len(prefix):].strip("【】[]：:，,。.!！?？ ")
                changed = True
                break
    for suffix in _TOPIC_SUFFIXES:
        if raw.endswith(suffix) and len(raw) > len(suffix):
            raw = raw[:-len(suffix)].strip("【】[]：:，,。.!！?？ ")
            break
    return raw[:80] or "当前主题"


def resolve_topic(
    knowledge_points: list[str] | None = None,
    learning_goal: str | None = None,
    topic_label: str | None = None,
) -> tuple[str, str, bool]:
    """Resolve a request to either a known course KP or a first-class custom topic."""
    explicit = canonical_kp_id((knowledge_points or [None])[0])
    combined = "\n".join(part for part in (str(topic_label or ""), str(learning_goal or "")) if part)
    inferred = infer_kp_id(combined)
    kp = explicit if explicit and explicit != CUSTOM_TOPIC_KP else inferred
    if kp and kp != CUSTOM_TOPIC_KP:
        from .learning_scope import current_space
        space = current_space()
        return kp, kp_name(kp), bool(space and space["course"].get("kind") != "ds_algo")
    label = clean_topic_label(topic_label or learning_goal)
    return CUSTOM_TOPIC_KP, label, True


def explicit_topic_label(question: str | None) -> str | None:
    """Extract a self-contained topic while rejecting help and pronoun-only turns."""
    text = " ".join(str(question or "").strip().split())
    probe = re.sub(r"^(?:请问|我想问一下|能问一下)\s*", "", text).strip()
    if not probe or _PRODUCT_HELP_RE.search(probe) or _CONTEXT_DEPENDENT_TOPIC_RE.match(probe):
        return None
    for pattern in _TOPIC_INTRO_PATTERNS:
        match = pattern.search(probe)
        if not match:
            continue
        label = clean_topic_label(match.group("topic"))
        if label not in {"当前主题", "这个主题", "这个", "那个", "为什么", "怎么", "如何"}:
            return label
    return clean_topic_label(probe) if len(probe) >= 2 else None


def resolve_conversation_topic(
    current_text: str | None,
    conversation: list[dict] | None = None,
    *,
    knowledge_points: list[str] | None = None,
    topic_label: str | None = None,
) -> tuple[str, str, bool]:
    """Resolve the current conversational focus without binding it to the opening title."""
    current = str(current_text or "").strip()
    current_kp = infer_kp_id(current)
    if current_kp:
        return resolve_topic([current_kp], current, "")

    current_label = explicit_topic_label(current)
    if current_label:
        return resolve_topic([], current_label, "")

    skipped_current = False
    for item in reversed(conversation or []):
        if item.get("role") != "user":
            continue
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        if not skipped_current and current and content == current:
            skipped_current = True
            continue
        recent_kp = infer_kp_id(content)
        if recent_kp:
            return resolve_topic([recent_kp], content, "")
        recent_label = explicit_topic_label(content)
        if recent_label:
            return resolve_topic([], recent_label, "")

    return resolve_topic(knowledge_points, current, topic_label)


def infer_kp_ids(text: str, kp_ids: list[str] | None = None) -> list[str]:
    """按出现顺序识别文本中的全部课程知识点，并避免短别名重复命中。"""
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
                matches.append((position, position + len(normalized), kp))

    if "graph_basic" in candidates:
        graph_match = _STANDALONE_GRAPH_RE.search(compact)
        if graph_match:
            graph_position = compact.find("图", graph_match.start(), graph_match.end())
            if graph_position >= 0:
                matches.append((graph_position, graph_position + 1, "graph_basic"))

    selected: list[tuple[int, int, str]] = []
    for start, end, kp in sorted(matches, key=lambda item: (item[0], -(item[1] - item[0]))):
        if any(existing_kp == kp for _, _, existing_kp in selected):
            continue
        if any(start < existing_end and end > existing_start for existing_start, existing_end, _ in selected):
            continue
        selected.append((start, end, kp))
    return [kp for _, _, kp in sorted(selected)]


def infer_kp_id(text: str, kp_ids: list[str] | None = None) -> str | None:
    """从自然语言中识别第一个课程知识点，兼容原有单主题调用。"""
    matches = infer_kp_ids(text, kp_ids)
    return matches[0] if matches else None


def collect_conversation_topics(
    conversation: list[dict] | None,
    current_text: str | None = None,
    *,
    max_topics: int = 24,
) -> list[dict]:
    """提取整段学习会话中的知识点，而不是只取最后一轮主题。

    已知课程知识点使用稳定的知识图谱 id；课外主题保留学习者原话。
    寒暄、上下文依赖追问和生成工具指令不会被误当成知识点。
    """
    messages = [dict(item) for item in (conversation or []) if isinstance(item, dict)]
    current = str(current_text or "").strip()
    if current and not any(
        item.get("role") == "user" and str(item.get("content") or "").strip() == current
        for item in messages
    ):
        messages.append({"role": "user", "content": current})

    topics: dict[str, dict] = {}
    for index, item in enumerate(messages):
        if item.get("role") != "user":
            continue
        content = " ".join(str(item.get("content") or "").strip().split())
        if not content or _PRODUCT_HELP_RE.search(content) or _INTERACTION_ACTION_RE.fullmatch(content):
            continue

        known_ids = infer_kp_ids(content)
        if known_ids:
            for kp in known_ids:
                key = f"kp:{kp}"
                topic = topics.setdefault(key, {
                    "id": kp,
                    "name": kp_name(kp),
                    "custom": False,
                    "questions": [],
                    "first_index": index,
                })
                if content not in topic["questions"] and len(topic["questions"]) < 4:
                    topic["questions"].append(content)
            continue

        if _ARTIFACT_REQUEST_RE.search(content) or _CONTEXT_DEPENDENT_TOPIC_RE.match(content):
            continue
        label = explicit_topic_label(content)
        if not label or label == "当前主题":
            continue
        key = f"custom:{label.casefold()}"
        topic = topics.setdefault(key, {
            "id": CUSTOM_TOPIC_KP,
            "name": label,
            "custom": True,
            "questions": [],
            "first_index": index,
        })
        if content not in topic["questions"] and len(topic["questions"]) < 4:
            topic["questions"].append(content)

    ordered = sorted(topics.values(), key=lambda topic: int(topic.get("first_index", 0)))
    return ordered[:max(1, min(max_topics, 24))]


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

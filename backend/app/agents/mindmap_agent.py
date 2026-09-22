"""思维导图智能体(Mindmap Agent):知识点 → markmap Markdown 层级语法,
前端 markmap-view 渲染交互式脑图;同时附 Mermaid mindmap 备选语法。"""
from __future__ import annotations

from ..services.model_preferences import resolve

import re
import uuid

from ..config import is_demo
from ..llm.spark_client import llm_complete
from ..prompt_templates import PromptCall, render_mindmap_prompt_call
from ..rag.citation import build_context
from ..rag.ingest import load_all_chunks
from ..rag.retriever import retrieve
from ..services.bkt import mastery_level
from ..services.knowledge_graph import (
    kp_name,
    load_kg,
    prerequisites,
    resolve_topic,
    topological_order,
    unlockable,
)
from ..services.learner_content import looks_like_source_code, without_source_code
from .emitter import agent_end, agent_start, emit

def _clean_point(line: str) -> str:
    line = without_source_code(line)
    line = re.sub(r"^\s*[-*+]\s*", "", line.strip())
    line = re.sub(r"^\s*\d+[.)、]\s*", "", line)
    line = line.strip(" `#\t\r\n")
    if looks_like_source_code(line):
        return ""
    return line[:24].strip()


def _points_from_text(text: str) -> list[str]:
    points: list[str] = []
    for raw in text.splitlines():
        point = _clean_point(raw)
        if point and not point.startswith("```") and point not in points:
            points.append(point)
        if len(points) >= 5:
            break
    return points


def _fallback_points(chunks: list[dict]) -> list[str]:
    text = " ".join((c.get("text") or "")[:240] for c in chunks)
    parts = re.split(r"[。；;.!?\n]", text)
    points: list[str] = []
    for part in parts:
        point = _clean_point(part)
        if 4 <= len(point) <= 24 and point not in points:
            points.append(point)
        if len(points) >= 5:
            break
    return points or ["资料片段不足"]


def _complete_learning_branches(points: list[str], *, has_sources: bool) -> list[str]:
    if not has_sources:
        return points
    scaffolds = [
        "关键步骤：按资料顺序走一遍",
        "最小例子：把概念落到具体过程",
        "复杂度：核对时间与空间代价",
        "易错边界：区分成立与不成立条件",
        "核心定义：先说清对象与目标",
    ]
    return list(dict.fromkeys([*points, *scaffolds]))[:5]


def _guided_goal_points(goal: str, chunks: list[dict]) -> list[str]:
    """Use a source-backed deterministic outline for common traversal first lessons."""
    if not chunks:
        return []
    compact = re.sub(r"\s+", "", goal)
    traversal = next((name for name in ("前序", "中序", "后序", "层序") if name in compact), "")
    orders = {
        "前序": ["顺序：根 → 左 → 右", "先记录当前节点", "再遍历左子树", "最后遍历右子树", "最小例子：A → B → C"],
        "中序": ["顺序：左 → 根 → 右", "先遍历左子树", "再记录当前节点", "最后遍历右子树", "最小例子：B → A → C"],
        "后序": ["顺序：左 → 右 → 根", "先遍历左子树", "再遍历右子树", "最后记录当前节点", "最小例子：B → C → A"],
        "层序": ["顺序：从上到下", "同层从左到右", "使用队列记录待访问节点", "访问后加入孩子", "最小例子：A → B → C"],
    }
    return orders.get(traversal, [])


def _outline_nodes(kp: str) -> list[tuple[str, str]]:
    kg = load_kg()
    children = kg["adj"].get(kp, [])
    ordered = [("先修", p) for p in prerequisites(kp)]
    ordered.append(("当前", kp))
    ordered.extend(("后续", c) for c in children)

    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for rel, node_id in ordered:
        if node_id in kg["nodes"] and node_id not in seen:
            out.append((rel, node_id))
            seen.add(node_id)
    return out


def _outline_for_scope(
    kp: str,
    source_ids: list[str],
    *,
    guided: bool = False,
) -> list[tuple[str, str]]:
    """Keep source-bound and first-lesson maps focused on the current concept."""
    if source_ids:
        return [("资料要点", kp)]
    if guided:
        return [("当前主题", kp)]
    return _outline_nodes(kp)


def _label_context(profile: dict | None) -> tuple[dict | None, set[str] | None]:
    if not isinstance(profile, dict):
        return None, None
    mastery = profile.get("knowledge_mastery")
    if not isinstance(mastery, dict):
        return None, None
    try:
        return mastery, set(unlockable(mastery))
    except Exception:
        return None, None


def _node_label(node_id: str, mastery: dict | None, unlocked: set[str] | None) -> str:
    name = kp_name(node_id)
    if not mastery or unlocked is None or node_id not in mastery:
        return name
    try:
        if node_id not in unlocked:
            return f"{name} 🔒"
        return f"{name} ✅" if mastery_level(float(mastery[node_id])) == "掌握" else f"{name} ⚠️"
    except Exception:
        return name


def _has_kp(hit: dict, kp: str) -> bool:
    values = [x.strip() for x in str(hit.get("kp") or "").split(",") if x.strip()]
    return kp in values


def _allowed_source(hit: dict, source_ids: list[str]) -> bool:
    if source_ids:
        return True
    return hit.get("source") == "《数据结构与算法》讲义"


def _with_citation(hit: dict) -> dict:
    out = dict(hit)
    if not out.get("citation"):
        source = out.get("source") or "未知来源"
        chapter = out.get("chapter") or ""
        page = out.get("page") or 0
        out["citation"] = f"{source} · {chapter} p.{page}"
    out.setdefault("score", 0)
    return out


def _seed_chunks_by_kp(node_id: str, limit: int = 3) -> list[dict]:
    chunks: list[dict] = []
    for hit in load_all_chunks():
        if _has_kp(hit, node_id) and _allowed_source(hit, []):
            chunks.append(_with_citation(hit))
        if len(chunks) >= limit:
            break
    return chunks


def _retrieve_node_chunks(
    query: str,
    node_id: str,
    source_ids: list[str],
    user_id: str,
) -> list[dict]:
    hits = retrieve(
        query,
        top_k=80,
        final_k=50,
        source_ids=source_ids,
        user_id=user_id,
    )
    strict = [_with_citation(hit) for hit in hits if _has_kp(hit, node_id) and _allowed_source(hit, source_ids)]
    if not source_ids and len(strict) < 2:
        seen = {(hit.get("source_id"), hit.get("page"), hit.get("text")) for hit in strict}
        for hit in _seed_chunks_by_kp(node_id):
            key = (hit.get("source_id"), hit.get("page"), hit.get("text"))
            if key not in seen:
                strict.append(hit)
                seen.add(key)
            if len(strict) >= 3:
                break
    if strict:
        return strict[:3]
    if source_ids:
        return [_with_citation(hit) for hit in hits[:3]]
    return []


async def _expand_node(
    node_id: str, *, source_ids: list[str], goal: str, guided: bool = False,
    topic_name: str = "", custom_topic: bool = False, user_id: str = "demo_user",
) -> tuple[list[str], list[dict], PromptCall]:
    name = topic_name or kp_name(node_id)
    node_desc = load_kg()["nodes"].get(node_id, {}).get("desc", "")
    query = (
        f"{name} {goal} 定义 最小例子 步骤"
        if guided else
        f"{name} {node_desc} 概念 性质 操作 算法 复杂度 易错点 {goal}"
    )
    chunks = (
        [] if custom_topic and not source_ids
        else _retrieve_node_chunks(query, node_id, source_ids, user_id)
    )
    ctx, citations = build_context(chunks)
    prompt_call = render_mindmap_prompt_call(
        kp=name,
        context=ctx or "(无)",
        general_knowledge=custom_topic and not source_ids,
    )

    points: list[str] = _guided_goal_points(goal, chunks) if guided else []
    if (chunks or custom_topic) and not points and not (is_demo() and resolve("CAPABILITY=mindmap.leaf") is None):
        try:
            raw = await llm_complete(
                prompt_call.prompt,
                system=prompt_call.system,
                role="reasoner",
                temperature=0.2,
                max_tokens=260,
            )
            points = _points_from_text(raw)
        except Exception:
            points = []
    if not points and custom_topic:
        points = ["一句话定义", "典型使用场景", "关键组成", "基本流程", "常见误区"]
    elif not points:
        points = _fallback_points(chunks)
    points = _complete_learning_branches(points, has_sources=bool(chunks))
    return points[:5], citations, prompt_call


def _render_markmap(root_name: str, expanded: list[tuple[str, str, list[str]]]) -> str:
    lines = [f"# {root_name}"]
    for relation, node_name, points in expanded:
        lines.append(f"## {relation}:{node_name}")
        for point in points:
            lines.append(f"### {point}")
    return "\n".join(lines)


def _ordered_conversation_topics(raw_topics: list | None) -> list[dict]:
    """Normalize and order conversation topics by the course prerequisite graph."""
    kg = load_kg()
    rank = {node_id: index for index, node_id in enumerate(topological_order())}
    normalized: list[dict] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_topics or []):
        if not isinstance(item, dict):
            continue
        node_id = str(item.get("id") or "").strip()
        custom = bool(item.get("custom")) or node_id not in kg["nodes"]
        name = str(item.get("name") or (kp_name(node_id) if not custom else "")).strip()
        if not name:
            continue
        key = f"custom:{name.casefold()}" if custom else f"kp:{node_id}"
        if key in seen:
            continue
        seen.add(key)
        questions = [
            str(question).strip() for question in (item.get("questions") or [])
            if str(question).strip()
        ][:4]
        normalized.append({
            "id": node_id or "custom_topic",
            "name": name[:80],
            "custom": custom,
            "questions": questions,
            "first_index": int(item.get("first_index", index)),
        })

    return sorted(
        normalized,
        key=lambda topic: (
            1 if topic["custom"] else 0,
            topic["first_index"] if topic["custom"] else rank.get(topic["id"], 10_000),
            topic["first_index"],
        ),
    )


def _conversation_relation_points(
    node_id: str,
    selected_ids: set[str],
    position: int,
) -> list[str]:
    points = [f"建议顺序：第 {position} 个"]
    if node_id not in selected_ids:
        return points
    edges = load_kg()["edges"]
    before = [kp_name(edge["from"]) for edge in edges if edge["to"] == node_id and edge["from"] in selected_ids]
    after = [kp_name(edge["to"]) for edge in edges if edge["from"] == node_id and edge["to"] in selected_ids]
    if before:
        points.append(f"先修关联：{'、'.join(before)}")
    if after:
        points.append(f"后续关联：{'、'.join(after)}")
    return points


def _render_conversation_markmap(expanded: list[tuple[str, str, list[str]]]) -> str:
    return _render_markmap(f"本次对话学习全景（{len(expanded)} 个知识点）", expanded)


def _outline_from_meta(kp: str, outline_node_ids: list | None) -> list[tuple[str, str]]:
    if isinstance(outline_node_ids, list):
        out: list[tuple[str, str]] = []
        for item in outline_node_ids:
            if isinstance(item, dict) and item.get("id"):
                out.append((str(item.get("relation") or ""), str(item["id"])))
            elif isinstance(item, str):
                out.append(("", item))
        if out:
            return out
    return _outline_nodes(kp)


def refresh_markmap_labels(
    markdown: str,
    kp: str,
    profile: dict,
    *,
    outline_node_ids: list | None = None,
) -> tuple[str, bool]:
    """Relabel existing markmap Markdown from exact KG node ids.

    Existing resources may not carry outline metadata, so the fallback derives
    the same node id sequence from resource.kp and the knowledge graph.
    """
    mastery, unlocked = _label_context(profile)
    if not mastery or unlocked is None:
        return markdown, False

    outline = _outline_from_meta(kp, outline_node_ids)
    lines = markdown.splitlines()
    changed = False
    outline_idx = 0
    new_lines: list[str] = []

    for line in lines:
        if line.startswith("# ") and not line.startswith("## "):
            new_line = f"# {_node_label(kp, mastery, unlocked)}"
        elif line.startswith("## "):
            relation = ""
            node_id = ""
            if outline_idx < len(outline):
                relation, node_id = outline[outline_idx]
            outline_idx += 1
            if node_id:
                current_relation, sep, _ = line[3:].partition(":")
                label_relation = current_relation if sep else relation
                prefix = f"## {label_relation}:" if label_relation else "## "
                new_line = f"{prefix}{_node_label(node_id, mastery, unlocked)}"
            else:
                new_line = line
        else:
            new_line = line
        if new_line != line:
            changed = True
        new_lines.append(new_line)
    return "\n".join(new_lines), changed


async def run(state: dict) -> dict:
    requested = state.get("kinds") or []
    if requested and "mindmap" not in requested:
        return {}
    kp, name, custom_topic = resolve_topic(
        state.get("knowledge_points"),
        state.get("learning_goal"),
        state.get("topic_label"),
    )
    source_ids = [str(x) for x in (state.get("source_ids") or []) if str(x).strip()]
    goal = state.get("learning_goal") or ""
    mastery, unlocked = _label_context(state.get("student_profile"))
    conversation_topics = (
        _ordered_conversation_topics(state.get("conversation_topics"))
        if state.get("artifact_scope") == "conversation" else []
    )
    if conversation_topics:
        await agent_start(
            "mindmap",
            "思维导图智能体",
            f"整合本次会话的 {len(conversation_topics)} 个知识点",
        )
        selected_ids = {
            topic["id"] for topic in conversation_topics if not topic["custom"]
        }
        expanded: list[tuple[str, str, list[str]]] = []
        citations: list[dict] = []
        outline_meta: list[dict] = []
        prompt_samples: list[str] = []
        prompt_meta: dict[str, str] = {}
        for position, topic in enumerate(conversation_topics, start=1):
            topic_goal = "；".join(topic["questions"]) or goal
            points, node_citations, prompt_call = await _expand_node(
                topic["id"],
                source_ids=source_ids,
                goal=topic_goal,
                topic_name=topic["name"] if topic["custom"] else "",
                custom_topic=topic["custom"],
                user_id=state.get("user_id", "demo_user"),
            )
            relation_points = _conversation_relation_points(
                topic["id"], selected_ids, position,
            )
            if topic["questions"]:
                relation_points.insert(0, f"你问过：{topic['questions'][-1][:36]}")
            combined_points = list(dict.fromkeys([*points, *relation_points]))[:8]
            node_label = (
                topic["name"] if topic["custom"]
                else _node_label(topic["id"], mastery, unlocked)
            )
            relation = f"第 {position} 步"
            expanded.append((relation, node_label, combined_points))
            citations.extend(node_citations)
            outline_meta.append({
                "relation": relation,
                "id": topic["id"],
                "label": topic["name"],
            })
            prompt_meta = prompt_call.metadata()
            if not prompt_samples:
                prompt_samples.append(prompt_call.prompt[:600])

        md = _render_conversation_markmap(expanded)
        rid = uuid.uuid4().hex[:12]
        resource = {
            "id": rid,
            "kind": "mindmap",
            "kp": kp,
            "title": "本次对话·知识全景导图",
            "payload": {
                "markmap": md,
                "topic_label": "本次对话学习全景",
                "custom_topic": all(topic["custom"] for topic in conversation_topics),
                "conversation_map": True,
                "topic_count": len(conversation_topics),
                "topics": conversation_topics,
                "prompt_skill": prompt_meta,
                "outline_node_ids": outline_meta,
            },
            "citations": list(dict.fromkeys(
                citation.get("citation", "")
                for citation in citations if citation.get("citation")
            )),
        }
        await emit({"type": "resource", "resource": resource})
        await agent_end(
            "mindmap",
            f"已整合 {len(conversation_topics)} 个会话知识点并推送导图",
            {"id": rid, "nodes": len(expanded), "prompt_sample": prompt_samples[:1]},
        )
        return {"generated_resources": {rid: resource}}

    await agent_start("mindmap", "思维导图智能体", f"「{name}」→ markmap 交互脑图")
    expanded: list[tuple[str, str, list[str]]] = []
    citations: list[dict] = []
    prompt_samples: list[str] = []
    prompt_meta: dict[str, str] = {}
    guided = bool(state.get("guided_learning") or state.get("intent") == "learn")
    outline = (
        [("当前主题", kp)] if custom_topic
        else _outline_for_scope(kp, source_ids, guided=guided)
    )
    for relation, node_id in outline:
        points, node_citations, prompt_call = await _expand_node(
            node_id,
            source_ids=source_ids,
            goal=goal,
            guided=guided,
            topic_name=name if custom_topic else "",
            custom_topic=custom_topic,
            user_id=state.get("user_id", "demo_user"),
        )
        expanded.append((relation, name if custom_topic else _node_label(node_id, mastery, unlocked), points))
        citations.extend(node_citations)
        prompt_meta = prompt_call.metadata()
        if relation == "当前":
            prompt_samples = [prompt_call.prompt[:600]]
        elif not prompt_samples:
            prompt_samples.append(prompt_call.prompt[:600])

    md = _render_markmap(name if custom_topic else _node_label(kp, mastery, unlocked), expanded)
    rid = uuid.uuid4().hex[:12]
    resource = {"id": rid, "kind": "mindmap", "kp": kp,
                "title": f"{name}·{'资料框架' if source_ids else '入门导图' if guided else '思维导图'}",
                "payload": {"markmap": md,
                            "topic_label": name,
                            "custom_topic": custom_topic,
                            "prompt_skill": prompt_meta,
                            "outline_node_ids": [{"relation": rel, "id": node_id}
                                                 for rel, node_id in outline]},
                "citations": list(dict.fromkeys(c.get("citation", "") for c in citations if c.get("citation")))}
    await emit({"type": "resource", "resource": resource})
    await agent_end("mindmap", f"脑图节点 {md.count(chr(10)) + 1} 行,已推送卡片",
                    {"id": rid, "nodes": len(expanded), "prompt_sample": prompt_samples[:1]})
    return {"generated_resources": {rid: resource}}

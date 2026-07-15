"""思维导图智能体(Mindmap Agent):知识点 → markmap Markdown 层级语法,
前端 markmap-view 渲染交互式脑图;同时附 Mermaid mindmap 备选语法。"""
from __future__ import annotations

import re
import uuid

from ..config import is_demo
from ..llm.spark_client import llm_complete
from ..prompt_templates import PromptCall, render_mindmap_prompt_call
from ..rag.citation import build_context
from ..rag.ingest import load_all_chunks
from ..rag.retriever import retrieve
from ..services.bkt import mastery_level
from ..services.knowledge_graph import kp_name, load_kg, prerequisites, unlockable
from .emitter import agent_end, agent_start, emit

def _clean_point(line: str) -> str:
    line = re.sub(r"^\s*[-*+]\s*", "", line.strip())
    line = re.sub(r"^\s*\d+[.)、]\s*", "", line)
    line = line.strip(" `#\t\r\n")
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
        if len(points) >= 3:
            break
    return points or ["资料片段不足"]


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


def _outline_for_scope(kp: str, source_ids: list[str]) -> list[tuple[str, str]]:
    """Keep selected-source maps free from unsourced course-graph relations."""
    if source_ids:
        return [("资料要点", kp)]
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


def _retrieve_node_chunks(query: str, node_id: str, source_ids: list[str]) -> list[dict]:
    hits = retrieve(
        query,
        top_k=80,
        final_k=50,
        source_ids=source_ids,
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
    node_id: str, *, source_ids: list[str], goal: str,
) -> tuple[list[str], list[dict], PromptCall]:
    name = kp_name(node_id)
    node_desc = load_kg()["nodes"].get(node_id, {}).get("desc", "")
    query = f"{name} {node_desc} 概念 性质 操作 算法 复杂度 易错点 {goal}"
    chunks = _retrieve_node_chunks(query, node_id, source_ids)
    ctx, citations = build_context(chunks)
    prompt_call = render_mindmap_prompt_call(kp=name, context=ctx or "(无)")

    points: list[str] = []
    if chunks and not is_demo():
        try:
            raw = await llm_complete(
                prompt_call.prompt,
                system=prompt_call.system,
                role="lite",
                temperature=0.2,
                max_tokens=260,
            )
            points = _points_from_text(raw)
        except Exception:
            points = []
    if not points:
        points = _fallback_points(chunks)
    return points[:5], citations, prompt_call


def _render_markmap(root_name: str, expanded: list[tuple[str, str, list[str]]]) -> str:
    lines = [f"# {root_name}"]
    for relation, node_name, points in expanded:
        lines.append(f"## {relation}:{node_name}")
        for point in points:
            lines.append(f"### {point}")
    return "\n".join(lines)


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
    kp = (state.get("knowledge_points") or ["binary_tree"])[0]
    name = kp_name(kp)
    source_ids = [str(x) for x in (state.get("source_ids") or []) if str(x).strip()]
    goal = state.get("learning_goal") or ""
    mastery, unlocked = _label_context(state.get("student_profile"))
    await agent_start("mindmap", "思维导图智能体", f"「{name}」→ markmap 交互脑图")
    expanded: list[tuple[str, str, list[str]]] = []
    citations: list[dict] = []
    prompt_samples: list[str] = []
    prompt_meta: dict[str, str] = {}
    outline = _outline_for_scope(kp, source_ids)
    for relation, node_id in outline:
        points, node_citations, prompt_call = await _expand_node(node_id, source_ids=source_ids, goal=goal)
        expanded.append((relation, _node_label(node_id, mastery, unlocked), points))
        citations.extend(node_citations)
        prompt_meta = prompt_call.metadata()
        if relation == "当前":
            prompt_samples = [prompt_call.prompt[:600]]
        elif not prompt_samples:
            prompt_samples.append(prompt_call.prompt[:600])

    md = _render_markmap(_node_label(kp, mastery, unlocked), expanded)
    rid = uuid.uuid4().hex[:12]
    resource = {"id": rid, "kind": "mindmap", "kp": kp,
                "title": f"{name}·{'资料框架' if source_ids else '思维导图'}",
                "payload": {"markmap": md,
                            "prompt_skill": prompt_meta,
                            "outline_node_ids": [{"relation": rel, "id": node_id}
                                                 for rel, node_id in outline]},
                "citations": list(dict.fromkeys(c.get("citation", "") for c in citations if c.get("citation")))}
    await emit({"type": "resource", "resource": resource})
    await agent_end("mindmap", f"脑图节点 {md.count(chr(10)) + 1} 行,已推送卡片",
                    {"id": rid, "nodes": len(expanded), "prompt_sample": prompt_samples[:1]})
    return {"generated_resources": {rid: resource}}

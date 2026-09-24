"""引用溯源:把检索 chunk 编号为 [^n],供 Doc/Tutor Agent 生成"强制带出处"内容,
并产出前端可渲染的 citations 列表。"""
from __future__ import annotations


def build_context(chunks: list[dict]) -> tuple[str, list[dict]]:
    """返回 (拼接上下文, citations)。上下文中每段以 [n] 开头,提示词要求按 [^n] 引用。"""
    lines, cites = [], []
    for i, c in enumerate(chunks, start=1):
        lines.append(f"[{i}] {c['text']}")
        cites.append({
            "index": i,
            "citation": c.get("citation", ""),
            "source_id": c.get("source_id", ""),
            "source": c.get("source", ""),
            "chapter": c.get("chapter", ""),
            "page": c.get("page", 0),
            "url": c.get("url", ""),
            "section_id": c.get("section_id", ""),
            "course_release_id": c.get("course_release_id", ""),
            "provenance": c.get("provenance", []),
            "source_sha256": c.get("source_sha256", ""),
            "start_char": c.get("start_char"),
            "end_char": c.get("end_char"),
            "version": c.get("version", ""),
            "location_kind": c.get("location_kind", "片段"),
            "score": round(float(c.get("score", 0)), 4),
            "excerpt": c["text"],
            "preview": c["text"][:80] + ("…" if len(c["text"]) > 80 else ""),
        })
    return "\n---\n".join(lines), cites


def used_indices(answer: str, n: int) -> list[int]:
    """统计答案实际引用了哪些 [^n],供 grounding 与前端高亮。"""
    import re
    found = {int(m) for m in re.findall(r"\[\^(\d+)\]", answer) if 0 < int(m) <= n}
    return sorted(found)

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


def normalize_reference_markers(answer: str) -> str:
    """Normalize unambiguous prose references, preserving code and Markdown links.

    A bare [1] can be a single-element list. Only sentence-final markers or
    explicit source cues qualify. All new one-page contexts use [^n] directly.
    Keep out-of-bounds markers so grounding rejects invented references.
    """
    import re
    protected = re.compile(
        r"(?P<ticks>`+)[\s\S]*?(?P=ticks)|"
        r"(?P<fence>~{3,})[^\n]*\n[\s\S]*?\n(?P=fence)|"
        r"!?\[[^\]\n]*\](?:\([^\n]*?\)|\[[^\]\n]*\])|"
        r"(?m:^[ \t]{0,3}\[[^\]\n]+\]:[^\n]*)"
    )
    marker = re.compile(r"((?:[。！？.!?；;]|资料|来源|出处|文献|参见|参考|依据)\s*)\[(\d+)\](?![\[(：:])")
    parts, start = [], 0
    for item in protected.finditer(answer):
        parts.append(marker.sub(r"\1[^\2]", answer[start:item.start()]))
        parts.append(item.group())
        start = item.end()
    parts.append(marker.sub(r"\1[^\2]", answer[start:]))
    return "".join(parts)

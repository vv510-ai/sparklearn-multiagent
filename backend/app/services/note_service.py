"""把已沉淀的个人学习笔记重新作为后续答疑的低权重参考资料。"""
from __future__ import annotations

from ..models.db import session
from ..models.entities import Resource


def _bigrams(text: str) -> set[str]:
    compact = "".join(str(text or "").lower().split())
    return {compact[i:i + 2] for i in range(max(0, len(compact) - 1))}


def recent_note_chunks(user_id: str, query: str, *, limit: int = 2) -> list[dict]:
    """返回与问题最相关的近期“对话笔记”，不混入普通生成文档。"""
    with session() as s:
        rows = (
            s.query(Resource)
            .filter(Resource.user_id == user_id, Resource.kind == "doc")
            .order_by(Resource.created_at.desc())
            .limit(12)
            .all()
        )

    query_parts = _bigrams(query)
    ranked: list[tuple[float, Resource, str]] = []
    for recency, row in enumerate(rows):
        payload = row.payload if isinstance(row.payload, dict) else {}
        if not payload.get("reusable_note"):
            continue
        markdown = str(payload.get("markdown") or "").strip()
        if not markdown:
            continue
        haystack = f"{row.title} {row.kp} {markdown}"
        overlap = len(query_parts & _bigrams(haystack))
        if overlap < 2:
            continue
        score = float(overlap) + max(0.0, 1.0 - recency * 0.05)
        ranked.append((score, row, markdown))

    ranked.sort(key=lambda item: item[0], reverse=True)
    return [
        {
            "text": markdown[:2200],
            "source": "我的学习笔记",
            "chapter": row.title,
            "page": 1,
            "source_type": "personal_note",
            "score": score,
            "citation": f"我的学习笔记 · {row.title}",
        }
        for score, row, markdown in ranked[:limit]
    ]

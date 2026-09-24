"""把已沉淀的个人学习笔记重新作为后续答疑的低权重参考资料。"""
from __future__ import annotations

from ..models.db import session
from ..models.entities import Resource
from .knowledge_graph import canonical_kp_id
from .course_library import provenance


_GENERIC_QUERY_BIGRAMS = {
    "什么", "是什", "为什", "怎么", "如何", "是否", "哪些", "讲讲", "解释", "一下", "意思", "可以", "怎样",
}


def _bigrams(text: str) -> set[str]:
    compact = "".join(str(text or "").lower().split())
    return {compact[i:i + 2] for i in range(max(0, len(compact) - 1))}


def recent_note_chunks(
    user_id: str,
    query: str,
    *,
    limit: int = 2,
    knowledge_point: str | None = None,
) -> list[dict]:
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
    informative_parts = query_parts - _GENERIC_QUERY_BIGRAMS
    target_kp = canonical_kp_id(knowledge_point)
    ranked: list[tuple[float, Resource, str]] = []
    for recency, row in enumerate(rows):
        payload = row.payload if isinstance(row.payload, dict) else {}
        from .course_library import blocked_payload
        if blocked_payload(payload):
            continue
        # Course-derived notes are reusable only within that exact release.
        # This also keeps unquoted context from carrying withdrawn material into
        # an unrelated course's answer when the model omits a citation.
        from .learning_scope import current_space
        current_release = str((current_space() or {}).get("course", {}).get("course_release_id") or "")
        origins = {x["course_release_id"] for x in provenance(payload)}
        if origins and origins != {current_release}:
            continue
        if not payload.get("reusable_note"):
            continue
        row_kp = canonical_kp_id(row.kp)
        if target_kp and row_kp != target_kp:
            continue
        markdown = str(payload.get("markdown") or "").strip()
        if not markdown:
            continue
        topic_text = f"{row.title} {row.kp}"
        topic_overlap = len(informative_parts & _bigrams(topic_text))
        content_overlap = len(informative_parts & _bigrams(markdown))
        if not target_kp and topic_overlap == 0 and content_overlap < 2:
            continue
        score = float(topic_overlap * 3 + min(content_overlap, 8)) + max(0.0, 1.0 - recency * 0.05)
        ranked.append((score, row, markdown))

    ranked.sort(key=lambda item: item[0], reverse=True)
    return [
        {
            "text": markdown[:2200],
            "provenance": provenance(row.payload),
            "source": "我的学习笔记",
            "chapter": row.title,
            "page": 1,
            "source_type": "personal_note",
            "score": score,
            "citation": f"我的学习笔记 · {row.title}",
        }
        for score, row, markdown in ranked[:limit]
    ]

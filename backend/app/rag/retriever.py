from __future__ import annotations

import logging

import numpy as np

from .embedding import embed_texts
from .ingest import COURSE_SCOPE_ID, chunks_for_source
from .reranker import rerank
from .vector_store import get_store

log = logging.getLogger("sparklearn.retriever")
COURSE_SOURCE = "《数据结构与算法》讲义"
SQL_SOURCE = "《SQL 入门》讲义"
BUILTIN_COURSE_SOURCES = {COURSE_SOURCE, SQL_SOURCE}


def _clean_ids(source_ids: list[str] | tuple[str, ...] | None) -> list[str]:
    return [str(x).strip() for x in (source_ids or []) if str(x).strip()]


def kp_values(value: object) -> set[str]:
    return {item.strip() for item in str(value or "").split(",") if item.strip()}


def hit_matches_kp(hit: dict, kp: str | None) -> bool:
    if not kp:
        return True
    values = kp_values(hit.get("kp"))
    return not values or kp in values


def _compact_term(value: object) -> str:
    return "".join(str(value or "").lower().split())


def hit_matches_required_terms(hit: dict, required_terms: list[str] | None) -> bool:
    """Require explicit concept evidence for high-stakes source-bound generation.

    Rerank scores are relative to the current candidate set, so an unrelated
    top result can still receive a high normalized score. Remediation instead
    requires the target concept name or id to appear in the body or metadata.
    """
    terms = [_compact_term(term) for term in (required_terms or []) if _compact_term(term)]
    if not terms:
        return True
    tags = hit.get("tags") or []
    if isinstance(tags, str):
        tags = [tags]
    values = (
        hit.get("text", ""),
        hit.get("source", ""),
        hit.get("chapter", ""),
        hit.get("kp", ""),
        hit.get("source_id", ""),
        *tags,
    )
    haystack = _compact_term(" ".join(str(value) for value in values if value))
    return any(term in haystack for term in terms)


def _hits_from_sources(
    query: str,
    source_ids: list[str],
    top_k: int,
    user_id: str | None,
) -> list[dict]:
    chunks: list[dict] = []
    for source_id in source_ids:
        # Missing tenant context is allowed to see only built-in (ownerless)
        # chunks. Uploaded sources always require their exact authenticated id.
        chunks.extend(chunks_for_source(source_id, user_id=user_id or ""))
    if not chunks:
        return []

    vectors = embed_texts([c.get("text", "") for c in chunks])
    qv = embed_texts([query], domain="query")[0]
    scores = vectors @ qv
    idx = np.argsort(-scores)[:top_k]
    return [{**chunks[i], "score": float(scores[i])} for i in idx]


def retrieve(
    query: str,
    course: str = "ds_algo",
    top_k: int = 20,
    final_k: int = 5,
    *,
    source_ids: list[str] | None = None,
    kp: str | None = None,
    required_terms: list[str] | None = None,
    user_id: str | None = None,
) -> list[dict]:
    selected_sources = _clean_ids(source_ids)
    uploaded_sources = [source_id for source_id in selected_sources if source_id != COURSE_SCOPE_ID]
    include_course = not selected_sources or COURSE_SCOPE_ID in selected_sources
    from ..services.learning_scope import current_space
    space = current_space()
    if space and space["course"].get("kind") != "ds_algo":
        include_course = False
    hits: list[dict] = []
    if uploaded_sources:
        hits.extend(_hits_from_sources(
            query,
            uploaded_sources,
            top_k=max(top_k, final_k * 4),
            user_id=user_id,
        ))
    if include_course:
        store = get_store()
        qv = embed_texts([query], domain="query")[0]
        search_k = max(top_k * 4, final_k * 8, 40)
        hits.extend([
            hit for hit in store.search(qv, top_k=search_k, user_id=user_id)
            if course != "ds_algo" or hit.get("source") in BUILTIN_COURSE_SOURCES
        ])

    if kp:
        hits = [hit for hit in hits if hit_matches_kp(hit, kp)]
    if required_terms:
        hits = [hit for hit in hits if hit_matches_required_terms(hit, required_terms)]
    if not hits:
        return []

    hits, mode = rerank(query, hits, top_k=final_k)
    log.debug(
        "RAG rerank mode=%s course=%s sources=%s evidence_terms=%s query=%s",
        mode,
        course,
        selected_sources or "-",
        required_terms or "-",
        query[:80],
    )

    for hit in hits:
        hit["citation"] = _format_citation(hit)
    return hits


def _format_citation(hit: dict) -> str:
    source = hit.get("source") or "未知来源"
    chapter = hit.get("chapter") or ""
    page = hit.get("page", "?")
    url = hit.get("url") or ""
    source_type = hit.get("source_type") or "lecture"

    if url:
        return f"{source} ({source_type}) {url}"
    if chapter:
        return f"{source} · {chapter} p.{page}"
    return f"{source} p.{page}"

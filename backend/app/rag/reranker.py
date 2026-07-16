"""Cross-encoder API reranking with a strong local hybrid fallback."""
from __future__ import annotations

import logging
import math
import re
from collections import Counter
from typing import Any

import requests

from ..config import get_settings
from .embedding import embed_texts, embedding_status, query_core

log = logging.getLogger("sparklearn.reranker")


def _api_rerank(query: str, docs: list[dict], top_k: int) -> tuple[list[dict], str] | None:
    settings = get_settings()
    if not settings.rerank_api_url:
        return None
    headers = {"Content-Type": "application/json"}
    if settings.rerank_api_key:
        headers["Authorization"] = f"Bearer {settings.rerank_api_key}"
    payload = {
        "query": query,
        "documents": [doc.get("text", "") for doc in docs],
        "top_k": top_k,
    }
    try:
        response = requests.post(
            settings.rerank_api_url, headers=headers, json=payload, timeout=20
        )
        response.raise_for_status()
        ranked = _parse_api_response(response.json(), docs)
        if ranked:
            return ranked[:top_k], "api"
    except Exception as exc:  # noqa: BLE001
        log.warning("Rerank API failed; using local hybrid reranker: %s", exc)
    return None


def _parse_api_response(data: Any, docs: list[dict]) -> list[dict]:
    if isinstance(data, dict) and isinstance(data.get("results"), list):
        rows = data["results"]
        ranked = []
        for row in rows:
            idx = int(row.get("index", row.get("document_index", -1)))
            if 0 <= idx < len(docs):
                relevance = float(row.get("relevance_score", row.get("score", 0.0)))
                ranked.append({
                    **docs[idx],
                    "vector_score": float(docs[idx].get("score", 0.0)),
                    "rerank_score": relevance,
                    "score": relevance,
                })
        return ranked
    if isinstance(data, dict) and isinstance(data.get("scores"), list):
        scores = data["scores"]
        return sorted(
            (
                {
                    **doc,
                    "vector_score": float(doc.get("score", 0.0)),
                    "rerank_score": float(scores[index]),
                    "score": float(scores[index]),
                }
                for index, doc in enumerate(docs[:len(scores)])
            ),
            key=lambda item: item.get("rerank_score", 0.0),
            reverse=True,
        )
    if isinstance(data, list):
        return _parse_api_response({"results": data}, docs)
    return []


def _terms(text: str) -> list[str]:
    value = str(text or "").lower()
    terms = [f"latin:{token}" for token in re.findall(r"[a-z0-9_+#.-]+", value)]
    for sequence in re.findall(r"[\u3400-\u9fff]+", value):
        for size in (1, 2, 3):
            terms.extend(
                f"cjk{size}:{sequence[start:start + size]}"
                for start in range(max(0, len(sequence) - size + 1))
            )
    return terms


def _metadata_text(doc: dict) -> str:
    tags = doc.get("tags") or []
    if isinstance(tags, str):
        tags = [tags]
    values = [
        doc.get("source", ""),
        doc.get("chapter", ""),
        doc.get("kp", ""),
        doc.get("source_id", ""),
        " ".join(str(tag) for tag in tags),
    ]
    return " ".join(str(value) for value in values if value)


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).lower()


def _normalize_scores(values: list[float]) -> list[float]:
    if not values:
        return []
    low, high = min(values), max(values)
    if high - low < 1e-8:
        return [0.5 for _ in values]
    return [(value - low) / (high - low) for value in values]


def _local_semantic_scores(query: str, docs: list[dict]) -> tuple[list[float], str] | None:
    """Re-encode candidate evidence with metadata for a genuine second-stage rank."""

    try:
        backend = str(embedding_status().get("backend") or "")
        if backend.startswith("hash"):
            return None
        query_vector = embed_texts([query], domain="query")[0]
        evidence = [
            "\n".join(filter(None, [
                _metadata_text(doc),
                str(doc.get("text", ""))[:480],
            ]))
            for doc in docs
        ]
        document_vectors = embed_texts(evidence, domain="para")
        return [float(score) for score in document_vectors @ query_vector], backend
    except Exception as exc:  # noqa: BLE001
        log.warning("Local semantic reranker failed; using lexical hybrid: %s", exc)
        return None


def _local_hybrid_rerank(query: str, docs: list[dict], top_k: int) -> list[dict]:
    core = query_core(query)
    query_terms = list(dict.fromkeys(_terms(core)))
    body_terms = [_terms(str(doc.get("text", ""))) for doc in docs]
    meta_terms = [_terms(_metadata_text(doc)) for doc in docs]
    document_terms = [set(body + meta) for body, meta in zip(body_terms, meta_terms)]
    document_frequency = {
        term: sum(term in terms for terms in document_terms) for term in query_terms
    }
    count = max(1, len(docs))
    body_lengths = [max(1, len(terms)) for terms in body_terms]
    average_length = sum(body_lengths) / count

    lexical_scores: list[float] = []
    needle = _compact(core)
    for doc, body, meta, body_length in zip(docs, body_terms, meta_terms, body_lengths):
        body_counter = Counter(body)
        meta_counter = Counter(meta)
        score = 0.0
        for term in query_terms:
            frequency = body_counter[term] + 2.6 * meta_counter[term]
            if frequency <= 0:
                continue
            df = document_frequency.get(term, 0)
            inverse_frequency = math.log(1.0 + (count - df + 0.5) / (df + 0.5))
            denominator = frequency + 1.2 * (0.25 + 0.75 * body_length / average_length)
            score += inverse_frequency * (frequency * 2.2 / denominator)

        body_text = _compact(doc.get("text", ""))
        meta_text = _compact(_metadata_text(doc))
        heading = body_text[:160]
        if needle:
            if needle in meta_text:
                score += 4.0
            if needle in heading:
                score += 2.0
            elif needle in body_text:
                score += 1.0
        lexical_scores.append(score)

    vector_scores = [float(doc.get("score", 0.0)) for doc in docs]
    semantic_result = _local_semantic_scores(query, docs)
    semantic_scores = semantic_result[0] if semantic_result else vector_scores
    normalized_vectors = _normalize_scores(vector_scores)
    normalized_semantic = _normalize_scores(semantic_scores)
    normalized_lexical = _normalize_scores(lexical_scores)
    lexical_has_signal = max(lexical_scores, default=0.0) > 0.0

    ranked = []
    for doc, vector, semantic, lexical, norm_vector, norm_semantic, norm_lexical in zip(
        docs,
        vector_scores,
        semantic_scores,
        lexical_scores,
        normalized_vectors,
        normalized_semantic,
        normalized_lexical,
    ):
        if semantic_result and lexical_has_signal:
            combined = 0.20 * norm_vector + 0.55 * norm_semantic + 0.25 * norm_lexical
        elif semantic_result:
            combined = 0.30 * norm_vector + 0.70 * norm_semantic
        elif lexical_has_signal:
            combined = 0.35 * norm_vector + 0.65 * norm_lexical
        else:
            combined = norm_vector
        ranked.append({
            **doc,
            "vector_score": vector,
            "semantic_score": semantic,
            "lexical_score": lexical,
            "rerank_score": combined,
            "score": combined,
        })
    ranked.sort(key=lambda item: item.get("rerank_score", 0.0), reverse=True)
    selected_mode = "semantic-hybrid" if semantic_result else "hybrid"
    return [
        {**doc, "local_rerank_mode": selected_mode}
        for doc in ranked[:top_k]
    ]


def rerank(query: str, docs: list[dict], top_k: int | None = None) -> tuple[list[dict], str]:
    if not docs:
        return [], "none"
    settings = get_settings()
    limit = int(top_k or settings.rerank_top_k or 5)
    mode = (settings.rerank_mode or "auto").lower()

    api_result = None
    if mode in {"auto", "api"}:
        api_result = _api_rerank(query, docs, limit)
    if api_result is not None:
        ranked, selected_mode = api_result
    elif mode == "vector":
        ranked, selected_mode = docs[:limit], "vector"
    else:
        ranked = _local_hybrid_rerank(query, docs, limit)
        selected_mode = str(ranked[0].get("local_rerank_mode") or "hybrid") if ranked else "hybrid"

    return [{**doc, "rerank_mode": selected_mode} for doc in ranked], selected_mode


def reranker_status() -> dict[str, str | bool]:
    settings = get_settings()
    configured = bool(settings.rerank_api_url)
    mode = (settings.rerank_mode or "auto").lower()
    local_backend = str(embedding_status().get("backend") or "unknown")
    local_mode = "hybrid" if local_backend.startswith("hash") else "semantic-hybrid"
    active = (
        f"api-with-{local_mode}-fallback"
        if configured and mode in {"auto", "api"}
        else "vector"
        if mode == "vector"
        else local_mode
    )
    return {
        "mode": active,
        "api_configured": configured,
        "local_model": local_backend,
    }

"""Cross-encoder API reranking with a strong local hybrid fallback."""
from __future__ import annotations

import logging
import math
import re
from collections import Counter
from typing import Any

import requests

from ..config import get_settings
from .embedding import query_core

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
    normalized_vectors = _normalize_scores(vector_scores)
    normalized_lexical = _normalize_scores(lexical_scores)
    lexical_has_signal = max(lexical_scores, default=0.0) > 0.0

    ranked = []
    for doc, vector, lexical, norm_vector, norm_lexical in zip(
        docs, vector_scores, lexical_scores, normalized_vectors, normalized_lexical
    ):
        combined = (
            0.35 * norm_vector + 0.65 * norm_lexical
            if lexical_has_signal
            else norm_vector
        )
        ranked.append({
            **doc,
            "vector_score": vector,
            "lexical_score": lexical,
            "rerank_score": combined,
            "score": combined,
        })
    ranked.sort(key=lambda item: item.get("rerank_score", 0.0), reverse=True)
    return ranked[:top_k]


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
        ranked, selected_mode = _local_hybrid_rerank(query, docs, limit), "hybrid"

    return [{**doc, "rerank_mode": selected_mode} for doc in ranked], selected_mode


def reranker_status() -> dict[str, str | bool]:
    settings = get_settings()
    configured = bool(settings.rerank_api_url)
    mode = (settings.rerank_mode or "auto").lower()
    active = "api-with-hybrid-fallback" if configured and mode in {"auto", "api"} else mode
    return {"mode": active, "api_configured": configured}

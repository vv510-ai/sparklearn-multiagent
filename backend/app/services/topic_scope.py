"""Narrow broad retrieved chapters to the current knowledge-point section."""
from __future__ import annotations

import re

from .knowledge_graph import infer_kp_ids


def _metadata_kps(chunk: dict) -> set[str]:
    return {
        value.strip()
        for value in str(chunk.get("kp") or "").split(",")
        if value.strip()
    }


def _topic_terms(topic_name: str) -> list[str]:
    compact = re.sub(r"\s+", "", str(topic_name or ""))
    return [
        part for part in re.split(r"[与和、/·（）()：:\s]+", compact)
        if len(part) >= 2
    ]


def _focused_text(text: str, kp: str, topic_name: str, metadata_kps: set[str]) -> str:
    raw = str(text or "").strip()
    if not raw or not kp:
        return raw

    # Markdown headings are the strongest section boundary in the seed corpus
    # and in most uploaded notes. Keep only sections that identify this kp and
    # do not introduce another course topic.
    sections = [
        section.strip()
        for section in re.split(r"(?=^\s{0,3}#{1,6}\s+)", raw, flags=re.MULTILINE)
        if section.strip()
    ]
    focused = []
    for section in sections:
        detected = infer_kp_ids(section)
        if kp != "custom_topic" and detected and detected[0] == kp:
            focused.append(section)
        elif kp == "custom_topic" and any(term in section for term in _topic_terms(topic_name)):
            focused.append(section)
    if focused:
        return "\n\n".join(focused)

    # Plain text may not have headings. Keep individual lines/sentences that
    # mention only the current kp, rather than returning a whole mixed chapter.
    pieces = [
        piece.strip()
        for piece in re.split(r"(?<=[。！？；])|\n+", raw)
        if piece.strip()
    ]
    focused = []
    for piece in pieces:
        detected = infer_kp_ids(piece)
        if kp != "custom_topic" and detected and detected[0] == kp:
            focused.append(piece)
        elif kp == "custom_topic" and any(term in piece for term in _topic_terms(topic_name)):
            focused.append(piece)
    if focused:
        return "".join(focused)

    detected_all = set(infer_kp_ids(raw))
    if kp != "custom_topic":
        # Retrieval metadata may describe a broad chapter (for example
        # graph_basic, graph_traverse, shortest_path) even when this exact
        # chunk only contains the requested definition. Preserve it whenever
        # the text itself introduces no foreign knowledge point.
        if kp in metadata_kps and not (detected_all - {kp}):
            return raw
        return ""
    return raw if any(term in raw for term in _topic_terms(topic_name)) else ""


def focus_chunks_on_topic(chunks: list[dict], kp: str | None, topic_name: str) -> list[dict]:
    """Return copied chunks whose text is safe for one current-topic artifact."""

    if not kp:
        return [dict(chunk) for chunk in chunks]
    focused_chunks: list[dict] = []
    for chunk in chunks:
        copied = dict(chunk)
        copied["text"] = _focused_text(
            str(chunk.get("text") or ""),
            kp,
            topic_name,
            _metadata_kps(chunk),
        )
        if str(copied["text"]).strip():
            focused_chunks.append(copied)
    return focused_chunks

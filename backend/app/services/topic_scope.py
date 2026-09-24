"""Narrow broad retrieved chapters to the current knowledge-point section."""
from __future__ import annotations

import re

from .knowledge_graph import clean_topic_label, infer_kp_ids


def _metadata_kps(chunk: dict) -> set[str]:
    return {
        value.strip()
        for value in str(chunk.get("kp") or "").split(",")
        if value.strip()
    }


def topic_terms(topic_name: str) -> list[str]:
    """Extract subject phrases without using generic teaching words as evidence."""
    compact = re.sub(r"\s+", "", clean_topic_label(topic_name)).casefold()
    # A custom course keeps the learner's natural question as its topic label.
    # Extract the subject before treating that label as literal source evidence;
    # instructions after a question mark are not subject names.
    compact = re.split(r"[？?。；;！!]", compact, maxsplit=1)[0]
    compact = re.sub(r"^(?:请问|什么是|如何理解|怎么理解)", "", compact)
    subject = re.split(
        r"是什么|是啥|有没有|有什么(?:区别|联系|关系|作用)|有哪些(?:区别|联系|关系|作用)|有何(?:区别|联系|关系)|怎么|如何",
        compact, maxsplit=1,
    )[0]
    compact = subject or compact
    generic = {"当前主题", "学习", "资料", "内容", "问题", "例子", "概念", "定义", "原理",
               "特点", "过程", "区别", "比较", "基础", "入门", "应用", "角色区分"}
    terms: list[str] = []
    for part in re.split(r"[与和、/·（）()：:，,。；;]+", compact):
        candidates = [part]
        # A confirmed outline may say “食物链中的能量流动特点”, while the
        # uploaded passage uses the shorter concept “能量流动”.
        candidates.append(re.split(r"中的|的", part)[-1])
        for candidate in candidates:
            candidate = re.sub(r"(?:特点|的?概念|的?定义|的?区别|的?比较)$", "", candidate)
            if (len(candidate) >= 2 or candidate in {"栈", "堆", "树", "图"}) and candidate not in generic and candidate not in terms:
                terms.append(candidate)
    return terms


def _focused_text(text: str, kp: str, topic_name: str, metadata_kps: set[str], *, named_topic: bool) -> str:
    raw = str(text or "").strip()
    if not raw or not kp:
        return raw
    terms = topic_terms(topic_name) if named_topic else []

    def matches_name(value: str) -> bool:
        compact = re.sub(r"\s+", "", value).casefold()
        return any(term in compact for term in terms)

    # Markdown headings are the strongest section boundary in the seed corpus
    # and in most uploaded notes. A comparison section can explicitly teach
    # more than one concept: the requested concept need not be detected first.
    sections = [
        section.strip()
        for section in re.split(r"(?=^\s{0,3}#{1,6}\s+)", raw, flags=re.MULTILINE)
        if section.strip()
    ]
    focused = []
    for section in sections:
        detected = infer_kp_ids(section)
        if kp != "custom_topic" and kp in detected:
            focused.append(section)
        elif named_topic and matches_name(section):
            focused.append(section)
    if focused:
        return "\n\n".join(focused)

    # Plain text may not have headings. Keep lines/sentences that explicitly
    # mention the current kp, rather than returning a whole mixed chapter.
    pieces = [
        piece.strip()
        for piece in re.split(r"(?<=[。！？；])|\n+", raw)
        if piece.strip()
    ]
    focused = []
    for piece in pieces:
        detected = infer_kp_ids(piece)
        if kp != "custom_topic" and kp in detected:
            focused.append(piece)
        elif named_topic and matches_name(piece):
            focused.append(piece)
    if focused:
        return "".join(focused)

    detected_all = set(infer_kp_ids(raw))
    if not named_topic:
        # Retrieval metadata may describe a broad chapter (for example
        # graph_basic, graph_traverse, shortest_path) even when this exact
        # chunk only contains the requested definition. Preserve it whenever
        # the text itself introduces no foreign knowledge point.
        if kp in metadata_kps and not (detected_all - {kp}):
            return raw
        return ""
    return raw if matches_name(raw) else ""


def focus_chunks_on_topic(chunks: list[dict], kp: str | None, topic_name: str) -> list[dict]:
    """Return copied chunks whose text is safe for one current-topic artifact."""

    if not kp:
        return [dict(chunk) for chunk in chunks]
    from .learning_scope import current_space
    space = current_space()
    course = (space or {}).get("course") or {}
    whole_course = bool(kp == "custom_topic" and topic_name and
                        re.sub(r"\s+", "", topic_name).casefold() ==
                        re.sub(r"\s+", "", str(course.get("title") or "")).casefold())
    named_topic = kp == "custom_topic" or bool(space and space["course"].get("kind") != "ds_algo")
    focused_chunks: list[dict] = []
    requested = set(infer_kp_ids(topic_name)) | ({kp} if kp != "custom_topic" else set())
    for chunk in chunks:
        copied = dict(chunk)
        # Versioned course-book sections already carry curated topic metadata.
        # Natural questions need not repeat an entire Chinese section title.
        # Preserve all explicitly mentioned subjects in a compound question.
        if (space and chunk.get("source_type") == "textbook"
                and chunk.get("source_id") == space["course"].get("textbook", {}).get("id")
                and (whole_course or requested)):
            # A tagged course section is authoritative. A passing mention of
            # vocabulary in a listening lesson must not broaden a vocab note.
            if whole_course or _metadata_kps(chunk) & requested:
                focused_chunks.append(copied)
            continue
        copied["text"] = _focused_text(
            str(chunk.get("text") or ""),
            kp,
            topic_name,
            _metadata_kps(chunk),
            named_topic=named_topic,
        )
        if str(copied["text"]).strip():
            focused_chunks.append(copied)
    return focused_chunks

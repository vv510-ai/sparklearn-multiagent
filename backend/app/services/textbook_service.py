"""Versioned textbook sections shared by assessment, lessons and retrieval."""
from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path

FILE = Path(__file__).resolve().parents[1] / "data/textbooks/python_tutorial.json"


@lru_cache
def python_book() -> dict:
    book = json.loads(FILE.read_text(encoding="utf-8"))
    for section in book["sections"]:
        if hashlib.sha256(section["text"].encode()).hexdigest() != section["sha256"]:
            raise ValueError("Textbook section hash mismatch")
    return book


def public_book() -> dict:
    book = python_book()
    return {**{k: book[k] for k in ("id", "title", "version", "url", "license", "license_url", "scope_note")},
            "sha256": hashlib.sha256(FILE.read_bytes()).hexdigest(),
            "sections": [{k: s[k] for k in ("id", "title", "url", "kps", "sha256")} for s in book["sections"]]}


def evidence_by_kp() -> dict[str, list[dict]]:
    book = python_book()
    result: dict[str, list[dict]] = {}
    for index, section in enumerate(book["sections"], 1):
        evidence = {"source": book["title"], "source_id": book["id"], "chapter": section["title"],
                    "section_id": section["id"], "page": index, "location_kind": "章节", "url": section["url"],
                    "version": book["version"], "text": section["text"], "sha256": section["sha256"]}
        for kp in section["kps"]:
            result.setdefault(kp, []).append(evidence)
    return result


@lru_cache
def python_chunks() -> tuple[dict, ...]:
    return _chunk_sections(python_book())


def course_textbook_chunks(course: dict) -> tuple[dict, ...]:
    """Use the learner's pinned source text, even after the platform book changes."""
    if course.get("course_release_id"):
        from .course_library import load_release
        _, index = load_release(course["course_release_id"])
        return tuple(index["chunks"])
    book = course["textbook"]
    evidence = {e["section_id"]: e for entries in course.get("evidence", {}).values() for e in entries}
    sections = []
    for section in book["sections"]:
        item = evidence.get(section["id"])
        if item and hashlib.sha256(item["text"].encode()).hexdigest() == section["sha256"]:
            sections.append({**section, "text": item["text"]})
    return _chunk_sections({**book, "sections": sections})


def _chunk_sections(book: dict) -> tuple[dict, ...]:
    result = []
    for section in book["sections"]:
        # Split between paragraphs; a fenced code example stays together.
        parts = re.finditer(r"```[\s\S]*?```|(?:(?!```)[\s\S])+?(?=\n\s*\n|```|$)", section["text"])
        start = end = None
        ranges = []
        for match in parts:
            if not match[0].strip():
                continue
            if start is not None and match.end() - start > 1400:
                ranges.append((start, end))
                start = None
            if start is None:
                start = match.start()
            end = match.end()
        if start is not None:
            ranges.append((start, end))
        for number, (start, end) in enumerate(ranges, 1):
            result.append({"text": section["text"][start:end], "source": book["title"],
                "source_id": book["id"], "source_type": "textbook", "user_id": "", "course": book.get("course", "python"),
                "chapter": section["title"], "section_id": section["id"], "kp": ",".join(section["kps"]),
                "page": number, "location_kind": "章节", "start_char": start, "end_char": end,
                "version": book["version"], "url": section["url"], "tags": [section["title"], *section["kps"]]})
    return tuple(result)


def attach_python_book(course: dict) -> dict:
    from ..data.python_practice import practice_bank, LESSONS
    book = public_book()
    course.update(textbook=book, evidence=evidence_by_kp(), practice_bank=practice_bank(),
                  lessons=LESSONS.copy(), coverage_note=book["scope_note"])
    course["boundary"] = "依据 Python 官方教程所列章节；起点题和新题由本站编写、代码示例已核对，难度尚未经学习者标定。只描述本次作答，延迟复测用于继续核对。"
    for question in course["bank"]:
        question["citations"] = [{k: v for k, v in e.items() if k != "text"}
                                 for e in course["evidence"].get(question["kp"], [])]
    return course

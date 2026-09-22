"""Derive replay times from the source cue, never from model timestamps."""
from __future__ import annotations

import html
import re

_TIME = re.compile(r"(?P<start>(?:\d{1,2}:)?\d{2}:\d{2}[.,]\d{1,3})\s*-->[^\n]*\n")


def normalized(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", text))).strip().casefold()


def source_lines(lines: list[dict], subtitles: str) -> list[dict]:
    cues = []
    text = subtitles.replace("\r\n", "\n")
    times = list(_TIME.finditer(text))
    for index, match in enumerate(times):
        end = times[index + 1].start() if index + 1 < len(times) else len(text)
        content = text[match.end():end]
        # Cue numbers/identifiers belong to the following timestamp, not dialogue.
        content = re.split(r"\n\s*\n", content, maxsplit=1)[0]
        content = re.sub(r"\n\d+\s*$", "", content)
        cues.append((normalized(content), match["start"]))
    source = normalized(subtitles)
    for line in lines:
        text = normalized(line["text"])
        matches = [stamp for content, stamp in cues if text and text in content]
        if not text or (cues and not matches) or (not cues and text not in source):
            raise ValueError("dialogue not present in source subtitles")
        # Ambiguous repeated dialogue has no reliable replay location.
        line["timestamp"] = matches[0] if len(matches) == 1 else ""
    return lines

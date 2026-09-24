"""Deterministic knowledge-map typography: models supply text, never glyphs.

Only fixed SVG primitives are emitted. All content is XML-escaped; long content
continues onto another card/page instead of being clipped or summarized.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
import uuid
from xml.sax.saxutils import escape

from ..config import GEN_DIR

RENDERER = "svg-text-v1"


def _plain(line: str) -> str:
    line = re.sub(r"\[\^(\d+)\]", r"[\1]", line)
    line = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", line)
    line = line.replace("**", "").replace("`", "")
    # XML 1.0 excludes these controls; never interpret content as SVG markup.
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", line)


def _width(text: str) -> float:
    return sum(1.0 if unicodedata.east_asian_width(c) in {"W", "F", "A"}
               or c in "WM@" else 0.7 for c in text)


def _wrap(text: str, budget: float = 26) -> list[str]:
    """Keep words intact when possible; preserve every character across lines."""
    lines, current = [], ""
    for token in re.findall(r"\[\d+\]|[A-Za-z0-9_]+|\s+|.", text):
        if _width(current + token) > budget and current:
            lines.append(current)
            current = ""
        for char in token:
            if _width(current + char) > budget and current:
                lines.append(current)
                current = ""
            current += char
    if current:
        lines.append(current)
    return lines or [""]


def _cards(markdown: str) -> list[list[tuple[str, bool]]]:
    cards: list[list[tuple[str, bool]]] = []
    current: list[tuple[str, bool]] = []
    for raw in markdown.splitlines():
        if not raw.strip():
            continue
        heading = bool(re.match(r"^#{1,6}\s", raw))
        if heading and any(not bold for _, bold in current):
            cards.append(current)
            current = []
        line = _plain(re.sub(r"^#{1,6}\s+|^>\s?", "", raw))
        if not line.strip():
            continue
        wrapped_lines = _wrap(line)
        # Keep a paragraph in one card when it fits. Only an oversized
        # paragraph may continue across cards; never cut words or conditions.
        if current and len(wrapped_lines) <= 9 and len(current) + len(wrapped_lines) > 9:
            cards.append(current)
            current = []
        for wrapped in wrapped_lines:
            if len(current) == 9:
                cards.append(current)
                current = []
            current.append((wrapped, heading))
    if current:
        cards.append(current)
    return cards


def render_one_page(name: str, markdown: str, *, content_status: str) -> dict:
    from .knowledge_map_layout import render_map
    diagram = render_map(name, markdown, content_status, GEN_DIR)
    if diagram:
        return diagram
    cards = _cards(markdown)
    if not cards:
        raise ValueError("没有可排版的文字")
    pages = []
    groups = [cards[i:i + 4] for i in range(0, len(cards), 4)]
    title = _plain(name)
    # A long topic remains visible in the body, with a short navigation header.
    header = title if _width(title) <= 36 else "一图看懂 · 完整主题见正文"
    scope = {"source_excerpt": "资料原文摘录 · 仅覆盖本次检索片段",
             "checked": "依据相关资料整理 · 可结合出处复核",
             "general_knowledge": "通用知识整理 · 未经课程资料核验",
             "supplemented": "资料优先，含通用补充 · 补充部分未经资料核验"}[content_status]
    try:
        for page_index, group in enumerate(groups):
            parts = [
                '<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900" viewBox="0 0 1600 900">',
                f'<title>{escape(title)} · {page_index + 1}/{len(groups)}</title>',
                '<rect width="1600" height="900" fill="#f6f8f4"/>',
                '<g font-family="Microsoft YaHei, Noto Sans CJK SC, Arial, sans-serif">',
                '<text x="60" y="53" font-size="19" fill="#287257">LEARNLOOP / 一图看懂</text>',
                f'<text x="60" y="108" font-size="36" font-weight="700" fill="#163e32">{escape(header)}</text>',
            ]
            texts = []
            for card_index, card in enumerate(group):
                x, y = 60 + (card_index % 2) * 755, 151 + (card_index // 2) * 338
                parts.append(f'<rect x="{x}" y="{y}" width="725" height="318" rx="18" fill="white" stroke="#cbded2"/>')
                for row, (text, bold) in enumerate(card):
                    texts.append(text)
                    parts.append(f'<text data-content="true" xml:space="preserve" x="{x + 28}" y="{y + 39 + row * 31}" '
                                 f'font-size="24" font-weight="{700 if bold else 400}" fill="{ "#176449" if bold else "#243a31" }">{escape(text)}</text>')
            parts += [f'<text x="60" y="854" font-size="19" fill="#4e6c5c">{escape(scope)}</text>',
                      f'<text x="1510" y="854" text-anchor="end" font-size="19" fill="#4e6c5c">{page_index + 1} / {len(groups)}</text>',
                      '</g></svg>']
            filename = f"one_page_{uuid.uuid4().hex}.svg"
            (GEN_DIR / filename).write_text("\n".join(parts), encoding="utf-8")
            pages.append({"title": title, "image_url": f"/static/gen/{filename}",
                          "image_status": "ready", "renderer": RENDERER, "provider": "text_layout",
                          "content_status": content_status, "layout": "text_excerpt",
                          "text_sha256": hashlib.sha256("".join(texts).encode()).hexdigest()})
    except Exception:
        for page in pages:
            (GEN_DIR / page["image_url"].rsplit("/", 1)[-1]).unlink(missing_ok=True)
        raise
    return {**pages[0], "pages": pages, "markdown_sha256": hashlib.sha256(markdown.encode()).hexdigest()}

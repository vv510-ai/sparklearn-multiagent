"""Editable, deterministic slides from the central model's validated outline."""
from __future__ import annotations

import asyncio
import re
import uuid
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field
from typing import Annotated

from ..config import GEN_DIR, get_settings, is_demo
from .model_preferences import resolve
from ..llm.spark_client import active_llm_label, active_provider, llm_complete, parse_json
from ..prompt_templates import invoke_learning_prompt


class Slide(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=40)
    bullets: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(min_length=1, max_length=4)


class Outline(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=60)
    slides: list[Slide] = Field(min_length=3, max_length=10)


def render(outline: Outline, target: Path, references: list[str] | None = None) -> int:
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.util import Inches, Pt
    deck = Presentation()
    deck.slide_width, deck.slide_height = Inches(13.333), Inches(7.5)
    pages = list(outline.slides)
    reference_lines = []
    for reference in references or []:
        # Preserve the full source label while keeping every editable line readable.
        reference_lines.extend(reference[i:i+76] for i in range(0, len(reference), 76))
    for offset in range(0, len(reference_lines), 4):
        pages.append(Slide(title="资料来源 · 引用编号对照", bullets=reference_lines[offset:offset+4]))
    for index, item in enumerate(pages):
        slide = deck.slides.add_slide(deck.slide_layouts[6])
        slide.background.fill.solid()
        slide.background.fill.fore_color.rgb = RGBColor.from_string("F4F7F4")
        def box(text, x, y, w, h, size, color, bold=False):
            frame = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h)).text_frame
            frame.word_wrap = True
            p = frame.paragraphs[0]; p.text = text
            p.font.name = "Microsoft YaHei"; p.font.size = Pt(size)
            p.font.bold = bold; p.font.color.rgb = RGBColor.from_string(color)
        box("知行循证 / 课程复习", .65, .4, 11, .4, 14, "167259")
        box(item.title, .65, 1.0, 12, 1.15, 28, "14352E", True)
        for j, bullet in enumerate(item.bullets):
            box(f"{j+1:02d}", .7, 2.2+j*1.02, .55, .45, 17, "167259", True)
            box(bullet, 1.5, 2.12+j*1.02, 10.7, .95, 19, "263E37")
        box("生成内容请结合课程资料核对；支持直接编辑。", .7, 6.95, 10.5, .3, 11, "63766E")
        box(f"{index+1:02d} / {len(pages):02d}", 11.9, 6.9, .9, .4, 12, "63766E")
    temp = target.with_suffix(".part")
    try:
        deck.save(temp)
        temp.replace(target)
    finally:
        temp.unlink(missing_ok=True)
    return len(pages)


async def create(query: str, *, citations: list[dict] | None = None) -> dict:
    if (is_demo() and resolve("CAPABILITY=media.ppt_outline") is None):
        raise RuntimeError("Editable AI slides require a configured text model")
    call = invoke_learning_prompt("media.ppt_outline", content=query)
    raw = await llm_complete(call.prompt, system=call.system, role="reasoner",
                             json_mode=True, json_object=True, max_tokens=6500,
                             reasoning_mode="disabled", temperature=0.2,
                             allow_model_fallback=False, allow_mock_fallback=False)
    outline = Outline.model_validate(parse_json(raw))
    sources = {}
    for position, citation in enumerate(citations or [], start=1):
        index = int(citation.get("index", position))
        label = str(citation.get("citation") or " · ".join(str(citation[k]) for k in ("source", "chapter", "page") if citation.get(k))).strip()
        if index > 0 and label:
            sources[index] = label
    used = {int(index) for index in re.findall(r"\[\^(\d+)\]", outline.model_dump_json())}
    if used - sources.keys():
        raise ValueError("PPT contains a citation without a supplied source")
    references = [f"[^{index}] {label}" for index, label in sorted(sources.items())]
    target = GEN_DIR / ("lesson_" + uuid.uuid4().hex + ".pptx")
    target.parent.mkdir(parents=True, exist_ok=True)
    total_pages = await asyncio.to_thread(render, outline, target, references)
    return {"status": "ready", "title": outline.title, "total_pages": total_pages,
            "content_pages": len(outline.slides), "reference_pages": total_pages - len(outline.slides),
            "url": "/static/gen/" + target.name, "provider": "native_pptx",
            "model": get_settings().deepseek_model if active_provider() == "deepseek" else active_llm_label()}

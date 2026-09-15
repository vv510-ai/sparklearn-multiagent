"""Editable, deterministic slides from the central model's validated outline."""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field
from typing import Annotated

from ..config import GEN_DIR, is_demo
from ..llm.spark_client import active_llm_label, llm_complete, parse_json
from ..prompt_templates import invoke_learning_prompt


class Slide(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=40)
    bullets: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(min_length=1, max_length=4)


class Outline(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=60)
    slides: list[Slide] = Field(min_length=3, max_length=10)


def render(outline: Outline, target: Path) -> None:
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.util import Inches, Pt
    deck = Presentation()
    deck.slide_width, deck.slide_height = Inches(13.333), Inches(7.5)
    for index, item in enumerate(outline.slides):
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
        box(f"{index+1:02d} / {len(outline.slides):02d}", 11.9, 6.9, .9, .4, 12, "63766E")
    temp = target.with_suffix(".part")
    try:
        deck.save(temp)
        temp.replace(target)
    finally:
        temp.unlink(missing_ok=True)


async def create(query: str) -> dict:
    if is_demo():
        raise RuntimeError("Editable AI slides require a configured text model")
    call = invoke_learning_prompt("media.ppt_outline", content=query)
    raw = await llm_complete(call.prompt, system=call.system, role="reasoner",
                             json_mode=True, max_tokens=6500, allow_mock_fallback=False)
    outline = Outline.model_validate(parse_json(raw))
    target = GEN_DIR / ("lesson_" + uuid.uuid4().hex + ".pptx")
    target.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(render, outline, target)
    return {"status": "ready", "title": outline.title, "total_pages": len(outline.slides),
            "url": "/static/gen/" + target.name, "provider": "native_pptx", "model": active_llm_label()}

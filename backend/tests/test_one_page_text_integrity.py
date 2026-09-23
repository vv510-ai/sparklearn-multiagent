"""Feedback 03: a knowledge map must render approved text, not repaint it."""
import asyncio
import hashlib
from xml.etree import ElementTree as ET

import pytest

from app.agents import doc_agent
from app.services import one_page_renderer


SOURCE = "选词：promising ≠ proven；may ≠ will certainly。①圈出转折；②判断词性；③替换；④重读。"


@pytest.fixture(autouse=True)
def isolated_assets(monkeypatch, tmp_path):
    monkeypatch.setattr(one_page_renderer, "GEN_DIR", tmp_path)


def visible_text(visual):
    texts = []
    for page in visual["pages"]:
        root = ET.parse(one_page_renderer.GEN_DIR / page["image_url"].rsplit("/", 1)[-1]).getroot()
        text = "".join(node.text or "" for node in root.iter() if node.get("data-content"))
        assert hashlib.sha256(text.encode()).hexdigest() == page["text_sha256"]
        texts.append(text)
    return "".join(texts)


def generate(monkeypatch, *, approved=True, has_source=True):
    monkeypatch.setattr(doc_agent, "is_demo", lambda: False)
    monkeypatch.setattr(doc_agent, "retrieve", lambda *a, **k: [{
        "text": SOURCE, "source": "课程原文", "source_id": "vocab", "page": 1,
    }])

    async def complete(*a, **k):
        return "# 选词\n\n## 例子\n" + (SOURCE if approved else "promising = proven，表示已经证明有效。") + "[^1]"

    async def grounding(*a, **k):
        return {"grounded": approved, "unsupported": [] if approved else ["promising = proven"], "verdict": "checked"}

    async def image(*a, **k):
        pytest.fail("Knowledge-map glyphs must never go through the image model")

    monkeypatch.setattr(doc_agent, "llm_complete", complete)
    monkeypatch.setattr(doc_agent, "grounding_check", grounding)
    monkeypatch.setattr(doc_agent.multimodal_gateway, "text_to_image", image)
    return asyncio.run(doc_agent._gen_one("doc", "custom_topic", {}, topic_name="选词", custom_topic=True,
        source_ids=["vocab"] if has_source else [], goal="一图看懂", prompt_template="one_page", trace_id="feedback-03"))


def test_map_uses_literal_text_instead_of_image_model(monkeypatch):
    result = generate(monkeypatch)
    visual = result["resource"]["payload"]["one_page_visual"]
    assert visual["image_url"].endswith(".svg")
    assert visual["renderer"] == "svg-text-v1"
    actual = visible_text(visual)
    assert SOURCE in actual
    assert actual.count("③") == 1
    assert actual.count("≠") == 2


def test_failed_factual_check_cannot_publish_the_rejected_claim(monkeypatch):
    result = generate(monkeypatch, approved=False)
    payload = result["resource"]["payload"]
    assert "promising = proven" not in payload["markdown"]
    assert SOURCE in payload["markdown"]
    assert payload["generation_mode"] == "source_guide"
    assert payload["one_page_visual"]["content_status"] == "source_excerpt"
    actual = visible_text(payload["one_page_visual"])
    assert SOURCE in actual and "promising = proven" not in actual


def test_pagination_preserves_every_character_even_for_long_words():
    text = (SOURCE + " VERY_LONG_WORD_" * 30 + "\"<&> 末尾条件不可丢失。") * 30
    visual = one_page_renderer.render_one_page("超长内容", text, content_status="checked")
    assert len(visual["pages"]) > 1
    assert visible_text(visual) == text


def test_svg_treats_markup_as_text_and_has_no_active_content():
    attack = '</text><script>alert("x")</script><image href="https://example.test/x"/>'
    visual = one_page_renderer.render_one_page(attack, attack, content_status="source_excerpt")
    assert visible_text(visual) == attack
    root = ET.parse(one_page_renderer.GEN_DIR / visual["image_url"].rsplit("/", 1)[-1]).getroot()
    assert {node.tag.rsplit("}", 1)[-1] for node in root.iter()} <= {"svg", "title", "rect", "g", "text"}
    assert not any("href" in key or key.startswith("on") for node in root.iter() for key in node.attrib)


def test_local_render_failure_retains_text_and_reports_failure(monkeypatch):
    def fail(*args, **kwargs):
        raise OSError("disk unavailable")
    monkeypatch.setattr(doc_agent, "render_one_page", fail)
    result = generate(monkeypatch)
    assert result["resource"]["payload"]["one_page_visual"]["image_status"] == "fallback"
    assert SOURCE in result["resource"]["payload"]["markdown"]


def test_general_knowledge_does_not_claim_source_verification(monkeypatch):
    payload = generate(monkeypatch, has_source=False)["resource"]["payload"]
    assert not payload["grounded"]
    assert not payload["source_evidence"]
    assert payload["one_page_visual"]["content_status"] == "general_knowledge"

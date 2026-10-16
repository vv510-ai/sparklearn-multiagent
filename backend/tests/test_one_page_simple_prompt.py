"""Simple-mode 一图看懂: exact product prompt, multi-image results and independent review."""
import asyncio
import json

import pytest
from PIL import Image

from app.agents import doc_agent
from app.services import one_page_image as pipeline

TEMPLATE = "帮我弄一个一图看懂光合作用的内容，如果一张图不够全面的解释或无法完整讲清楚，根据内容合理拆分为多张（合理数量）的一图看懂，确保内容全面、准确、直观易懂。"


def test_simple_prompt_is_exactly_the_product_template_without_system_or_context():
    call = pipeline.simple_prompt("光合作用")
    assert call.prompt == TEMPLATE
    assert call.system == "" and "CAPABILITY" not in call.prompt
    with_material = pipeline.simple_prompt("光合作用", "- 光反应在类囊体膜上进行")
    assert with_material.prompt.startswith(TEMPLATE)
    assert with_material.prompt.endswith("请以我的课程资料要点为准：\n- 光反应在类囊体膜上进行")


@pytest.fixture
def two_pictures(monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline, "is_demo", lambda: False)
    monkeypatch.setattr(pipeline.gateway, "GEN_DIR", tmp_path)
    for index in (1, 2):
        Image.new("RGB", (320, 180), "white").save(tmp_path / f"chatgpt_x_{index}.png")
    calls = {}

    async def generate(prompt, **kwargs):
        calls["prompt"], calls["kwargs"] = prompt, kwargs
        return {"ok": True, "data": {"provider": "chatgpt_web", "images": [
            {"index": 1, "image_url": "/static/gen/chatgpt_x_1.png", "width": 320, "height": 180},
            {"index": 2, "image_url": "/static/gen/chatgpt_x_2.png", "width": 320, "height": 180}],
            "image_url": "/static/gen/chatgpt_x_1.png", "conversation_url": "https://chatgpt.com/c/abc-12345678"}}

    readings = iter([{"text": "光反应 类囊体膜 产生ATP和NADPH", "confidence": 0.93},
                     {"text": "暗反应 叶绿体基质 卡尔文循环 固定CO2", "confidence": 0.9}])
    monkeypatch.setattr(pipeline.gateway, "text_to_image", generate)
    from app.llm import local_ocr
    monkeypatch.setattr(local_ocr, "available", lambda: True)
    monkeypatch.setattr(local_ocr, "recognize", lambda content, **kwargs: {**next(readings), "engine": "rapidocr-onnx"})
    return calls


def test_simple_pipeline_requests_multiple_pictures_and_reviews_each_independently(two_pictures, monkeypatch):
    seen = {}

    async def review(prompt, **kwargs):
        seen["prompt"] = prompt
        return json.dumps({"images": [
            {"index": 1, "title": "光反应", "status": "passed", "issues": [], "uncertain": []},
            {"index": 2, "title": "暗反应", "status": "failed", "issues": ["图2把卡尔文循环写成在类囊体膜进行，应为叶绿体基质"], "uncertain": []}],
            "coverage": {"status": "partial", "missing": ["影响光合速率的因素"]},
            "text_version": "## 图1 · 光反应\n- 在类囊体膜上产生 ATP 和 NADPH"}, ensure_ascii=False)

    monkeypatch.setattr(pipeline, "llm_complete", review)
    visual = asyncio.run(pipeline.generate_simple_one_page("光合作用", trace_id="t"))
    assert two_pictures["prompt"] == TEMPLATE
    assert two_pictures["kwargs"]["multi"] is True and two_pictures["kwargs"]["preferred_provider"] == "chatgpt_web"
    assert two_pictures["kwargs"]["allow_provider_fallback"] is False
    assert [image["index"] for image in visual["images"]] == [1, 2]
    assert visual["images"][0]["verification"]["status"] == "passed"
    assert visual["images"][1]["verification"]["status"] == "failed"
    assert visual["verification"]["status"] == "failed"
    assert any("影响光合速率" in issue for issue in visual["verification"]["issues"])
    assert visual["text_version"].startswith("## 图1")
    # The reviewer receives OCR transcripts, not the request it is judging.
    assert "叶绿体基质" in seen["prompt"] and "合理拆分" not in seen["prompt"]


def test_review_outage_keeps_pictures_and_marks_them_unverified(two_pictures, monkeypatch):
    async def broken(*args, **kwargs):
        raise TimeoutError("reviewer offline")

    monkeypatch.setattr(pipeline, "llm_complete", broken)
    visual = asyncio.run(pipeline.generate_simple_one_page("光合作用", trace_id="t"))
    assert visual["image_status"] == "ready" and len(visual["images"]) == 2
    assert {image["verification"]["status"] for image in visual["images"]} == {"unverified"}
    assert visual["verification"]["status"] == "unverified"
    assert "图1" in visual["text_version"]  # raw OCR is kept as a readable text version


def test_document_agent_uses_simple_mode_for_the_chatgpt_bridge(monkeypatch):
    monkeypatch.setattr(doc_agent, "retrieve", lambda *a, **k: [])
    monkeypatch.setattr(doc_agent, "_simple_one_page_mode", lambda: True)
    captured = {}

    async def simple(topic, **kwargs):
        captured["topic"], captured["kwargs"] = topic, kwargs
        page = {"title": topic, "renderer": pipeline.SIMPLE_RENDERER, "image_status": "ready", "image_url": "/static/gen/a.png",
                "images": [{"index": 1, "url": "/static/gen/a.png", "verification": {"status": "passed", "issues": []}}],
                "verification": {"status": "passed", "issues": []}, "attempts": [{"attempt": 1}], "text_version": "## 图1 · 光反应"}
        return {**page, "pages": [page]}

    async def must_not_draft(*args, **kwargs):
        raise AssertionError("simple mode must not write a long draft first")

    monkeypatch.setattr(doc_agent, "generate_simple_one_page", simple)
    monkeypatch.setattr(doc_agent, "llm_complete", must_not_draft)
    result = asyncio.run(doc_agent._gen_one("doc", "custom_topic", {}, topic_name="光合作用", custom_topic=True,
        source_ids=[], goal="生成一图看懂", prompt_template="one_page", trace_id="simple",
        one_page_scope={"topic": "光合作用", "kp": "custom_topic", "overview": False}))
    payload = result["resource"]["payload"]
    assert captured["topic"] == "光合作用" and captured["kwargs"]["material_points"] == ""
    assert payload["one_page_visual"]["renderer"] == pipeline.SIMPLE_RENDERER
    assert payload["markdown"].startswith("# 一图看懂：光合作用") and "图1" in payload["markdown"]
    assert result["resource"]["title"] == "光合作用·一图看懂"

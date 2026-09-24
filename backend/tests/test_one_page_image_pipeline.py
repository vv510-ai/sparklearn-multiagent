"""Real provider routing and fail-closed infographic verification contracts."""
import asyncio

from app.agents import doc_agent


def test_one_page_calls_xiaoyunque_without_provider_fallback(monkeypatch):
    monkeypatch.setattr(doc_agent, "retrieve", lambda *a, **k: [{"text": "栈后进先出。", "source_id": "stack", "source": "讲义"}])
    monkeypatch.setattr(doc_agent, "is_demo", lambda: False)
    calls = []

    async def complete(*a, **k):
        return "# 栈\n\n## 规则\n栈后进先出。[^1]"

    async def grounded(*a, **k):
        return {"grounded": True, "unsupported": []}

    async def generate(prompt, **kwargs):
        calls.append(kwargs)
        return {"ok": False, "error": "test unavailable", "data": {}}

    monkeypatch.setattr(doc_agent, "llm_complete", complete)
    monkeypatch.setattr(doc_agent, "grounding_check", grounded)
    monkeypatch.setattr(doc_agent.multimodal_gateway, "text_to_image", generate)
    result = asyncio.run(doc_agent._gen_one("doc", "custom_topic", {}, topic_name="栈", custom_topic=True,
        source_ids=["stack"], goal="生成一图看懂", prompt_template="one_page", trace_id="one-page-contract"))
    assert len(calls) == 1
    assert calls[0]["preferred_provider"] == "xiaoyunque"
    assert calls[0]["allow_provider_fallback"] is False
    visual = result["resource"]["payload"]["one_page_visual"]
    assert visual["image_status"] == "fallback"
    assert not visual.get("image_url")


import json
from io import BytesIO

import pytest
from PIL import Image
from app.services import one_page_image as pipeline


def passing_review():
    return {"checks": {key: "passed" for key in pipeline.CHECK_NAMES}, "issues": []}


@pytest.fixture
def image_checks(monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline, "is_demo", lambda: False)
    monkeypatch.setattr(pipeline.gateway, "GEN_DIR", tmp_path)
    image = Image.new("RGB", (200, 100), "white")
    image.save(tmp_path / "map.png")
    observation = {"text": "promising ≠ proven", "formulas": [],
                   "relations": ["promising → 含义：有希望"], "legible": True, "uncertainties": []}
    responses = {"observation": observation, "judgment": passing_review(), "engine": "spark_image_understanding", "degraded": False}

    async def ocr(data, **kwargs):
        assert isinstance(data, bytes)
        assert "promising" not in kwargs["hint"]  # Do not show the expected answer to the image reader.
        return {"ok": True, "degraded": responses["degraded"],
                "data": {"engine": responses["engine"], "text": json.dumps(responses["observation"], ensure_ascii=False)}}

    async def compare(prompt, **kwargs):
        assert kwargs["allow_mock_fallback"] is False
        return json.dumps(responses["judgment"], ensure_ascii=False)

    monkeypatch.setattr(pipeline.gateway, "ocr_image", ocr)
    monkeypatch.setattr(pipeline, "llm_complete", compare)
    return responses


def test_inspection_reads_real_bytes_and_requires_all_dimensions(image_checks):
    result = asyncio.run(pipeline.inspect_image("/static/gen/map.png", "promising ≠ proven", trace_id="test"))
    assert result["status"] == "passed"
    assert result["image_sha256"] and result["content_sha256"]
    assert result["checks"] == {key: "passed" for key in pipeline.CHECK_NAMES}


@pytest.mark.parametrize("change", ["missing_dimension", "unclear", "no_relations", "local_ocr", "degraded", "malformed", "finding_despite_pass", "blank_relations"])
def test_incomplete_or_uncertain_review_never_passes(image_checks, change):
    if change == "missing_dimension":
        del image_checks["judgment"]["checks"]["relations"]
    elif change == "unclear":
        image_checks["observation"]["legible"] = False
    elif change == "no_relations":
        image_checks["observation"]["relations"] = []
    elif change == "blank_relations":
        image_checks["observation"]["relations"] = ["   "]
    elif change == "local_ocr":
        image_checks["engine"] = "rapidocr"
    elif change == "degraded":
        image_checks["degraded"] = True
    elif change == "malformed":
        image_checks["observation"] = {"text": "OK"}
    else:
        image_checks["judgment"]["issues"] = ["右侧符号不清楚"]
    assert asyncio.run(pipeline.inspect_image("/static/gen/map.png", "底稿", trace_id="test"))["status"] == "unverified"


@pytest.mark.parametrize("url", ["https://example.com/image.png", "/static/gen/../map.png", "/static/gen/map.svg"])
def test_review_only_opens_local_generated_raster_files(image_checks, url):
    assert asyncio.run(pipeline.inspect_image(url, "底稿", trace_id="test"))["status"] == "unverified"


def _generation_stubs(monkeypatch, statuses, fail_second=False):
    requests = []
    checked = []

    async def generate(prompt, **kwargs):
        assert kwargs["preferred_provider"] == "xiaoyunque"
        assert kwargs["allow_provider_fallback"] is False
        requests.append(prompt)
        if fail_second and len(requests) == 2:
            return {"ok": False, "data": {}}
        return {"ok": True, "data": {"provider": "xiaoyunque", "image_url": f"/static/gen/image{len(requests)}.png"}}

    async def inspect(url, content, **kwargs):
        status = statuses[min(len(checked), len(statuses)-1)]
        checked.append((url, content))
        return {"status": status, "checks": {key: "failed" if status == "failed" else "passed" for key in pipeline.CHECK_NAMES},
                "issues": ["≠ 被画成 ="] if status == "failed" else []}

    monkeypatch.setattr(pipeline.gateway, "text_to_image", generate)
    monkeypatch.setattr(pipeline, "inspect_image", inspect)
    return requests, checked


def test_failed_comparison_regenerates_once_and_rechecks(monkeypatch):
    requests, checked = _generation_stubs(monkeypatch, ["failed", "passed"])
    result = asyncio.run(pipeline.generate_one_page("词义", ["promising ≠ proven"], content_status="checked", trace_id="test"))
    assert len(requests) == len(checked) == 2
    assert "≠ 被画成 =" in requests[1]
    assert result["verification"]["status"] == "passed"
    assert result["attempts"][0]["verification"]["status"] == "failed"
    assert result["image_url"].endswith("image2.png")


@pytest.mark.parametrize("status,attempts", [("failed", 2), ("unverified", 1), ("passed", 1)])
def test_repair_is_bounded_and_unavailable_check_does_not_trigger_spending(monkeypatch, status, attempts):
    requests, _ = _generation_stubs(monkeypatch, [status])
    result = asyncio.run(pipeline.generate_one_page("词义", ["promising ≠ proven"], content_status="checked", trace_id="test"))
    assert len(requests) == attempts
    assert result["verification"]["status"] == status


def test_failed_repair_preserves_first_image_and_reports_failure(monkeypatch):
    requests, _ = _generation_stubs(monkeypatch, ["failed"], fail_second=True)
    result = asyncio.run(pipeline.generate_one_page("词义", ["promising ≠ proven"], content_status="checked", trace_id="test"))
    assert len(requests) == 2 and result["image_url"].endswith("image1.png")
    assert result["verification"]["status"] == "failed"
    assert any("修正未能" in issue for issue in result["verification"]["issues"])


def test_multi_page_preserves_each_page_and_skips_excessive_input(monkeypatch):
    requests, checked = _generation_stubs(monkeypatch, ["passed"])
    result = asyncio.run(pipeline.generate_one_page("词义", ["第一节", "第二节"], content_status="checked", trace_id="test"))
    assert len(result["pages"]) == 2
    assert [content for _, content in checked] == ["第一节", "第二节"]
    result = asyncio.run(pipeline.generate_one_page("超长", ["原文"*4000], content_status="checked", trace_id="test"))
    assert result["image_status"] == "fallback" and len(requests) == 2


def test_summary_does_not_call_failed_or_unverified_checks_passed():
    from app.agents.eval_agent import _learner_summary
    for status in ("failed", "unverified"):
        page = {"renderer": pipeline.RENDERER, "image_status": "ready", "verification": {"status": status}}
        summary = _learner_summary({"r": {"payload": {"one_page_visual": page}}}, [], "one_page")
        assert "未确认" in summary


def test_independent_image_checks_never_receive_learner_context(monkeypatch):
    from app.services import course_learning_service
    from app.prompt_templates import invoke_learning_prompt
    monkeypatch.setattr(course_learning_service, "context_summary", lambda: {"goal": "PRIVATE_LEARNER_CONTEXT"})
    for name in ("image.one_page_observe", "image.one_page_check"):
        call = invoke_learning_prompt(name, content="已核对内容", observation="{}")
        assert "PRIVATE_LEARNER_CONTEXT" not in call.prompt

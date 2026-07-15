from __future__ import annotations

import asyncio

from app.agents import doc_agent


def _chunk() -> dict:
    return {
        "text": "二叉树每个节点最多有两个孩子，中序遍历按左子树、根节点、右子树访问。",
        "source": "《数据结构与算法》讲义",
        "chapter": "二叉树",
        "kp": "binary_tree",
        "page": 1,
        "source_type": "lecture",
        "source_id": "binary-tree-notes",
    }


def _install_doc_stubs(monkeypatch, *, audio_ok: bool, image_ok: bool = False):
    monkeypatch.setattr(doc_agent, "retrieve", lambda *args, **kwargs: [_chunk()])

    async def fake_complete(*args, **kwargs):
        return "# 二叉树\n\n## 核心概念\n二叉树每个节点最多有两个孩子。[^1]"

    async def fake_grounding(*args, **kwargs):
        return {"grounded": True, "unsupported": [], "verdict": "ok"}

    async def fake_tts(*args, **kwargs):
        if audio_ok:
            return {"ok": True, "data": {"audio_url": "/static/gen/doc-test.mp3"}}
        return {"ok": False, "degraded": True, "data": {}, "error": "disabled"}

    async def fake_image(*args, **kwargs):
        if image_ok:
            return {"ok": True, "data": {"image_url": "/static/gen/doc-test.jpg"}}
        return {"ok": False, "degraded": True, "data": {}, "error": "disabled"}

    monkeypatch.setattr(doc_agent, "llm_complete", fake_complete)
    monkeypatch.setattr(doc_agent, "grounding_check", fake_grounding)
    monkeypatch.setattr(doc_agent, "safety_filter", lambda text: {"safe": True, "hits": []})
    monkeypatch.setattr(doc_agent.multimodal_gateway, "tts", fake_tts)
    monkeypatch.setattr(doc_agent.multimodal_gateway, "text_to_image", fake_image)


def test_doc_includes_audio_when_tts_succeeds(monkeypatch):
    _install_doc_stubs(monkeypatch, audio_ok=True)
    out = asyncio.run(doc_agent._gen_one(  # noqa: SLF001
        "doc",
        "binary_tree",
        {},
        source_ids=[],
        goal="",
        trace_id="doc-audio-test",
    ))

    assert out["resource"]["payload"]["audio_url"] == "/static/gen/doc-test.mp3"
    assert out["resource"]["payload"]["markdown"].startswith("# 二叉树")


def test_doc_survives_tts_degradation(monkeypatch):
    _install_doc_stubs(monkeypatch, audio_ok=False)
    out = asyncio.run(doc_agent._gen_one(  # noqa: SLF001
        "doc",
        "binary_tree",
        {},
        source_ids=[],
        goal="",
        trace_id="doc-audio-degraded",
    ))

    assert "audio_url" not in out["resource"]["payload"]
    assert out["resource"]["payload"]["markdown"]


def test_doc_includes_cover_when_image_succeeds(monkeypatch):
    _install_doc_stubs(monkeypatch, audio_ok=False, image_ok=True)
    out = asyncio.run(doc_agent._gen_one(  # noqa: SLF001
        "doc",
        "binary_tree",
        {},
        source_ids=[],
        goal="",
        trace_id="doc-cover-test",
    ))

    assert out["resource"]["payload"]["cover_url"] == "/static/gen/doc-test.jpg"
    assert "audio_url" not in out["resource"]["payload"]


def test_doc_survives_unexpected_multimodal_exception(monkeypatch):
    _install_doc_stubs(monkeypatch, audio_ok=True)

    async def broken_image(*args, **kwargs):
        raise RuntimeError("image provider crashed")

    monkeypatch.setattr(doc_agent.multimodal_gateway, "text_to_image", broken_image)
    out = asyncio.run(doc_agent._gen_one(  # noqa: SLF001
        "doc",
        "binary_tree",
        {},
        source_ids=[],
        goal="",
        trace_id="doc-image-exception",
    ))

    assert out["resource"]["payload"]["audio_url"] == "/static/gen/doc-test.mp3"
    assert "cover_url" not in out["resource"]["payload"]
    assert out["resource"]["payload"]["markdown"]


def test_narration_is_short_plain_text():
    text = doc_agent._narration_text(  # noqa: SLF001
        "二叉树",
        "# 标题\n正文包含 [链接](https://example.com) 与引用[^1]。\n```python\nprint('skip')\n```",
        limit=80,
    )
    assert len(text) <= 80
    assert "[^1]" not in text
    assert "```" not in text
    assert "https://" not in text


def test_cover_prompt_is_fixed_and_knowledge_point_scoped():
    prompt = doc_agent._cover_prompt("二叉树")  # noqa: SLF001
    assert "二叉树" in prompt
    assert "数据结构教学插画" in prompt
    assert "无人物" in prompt


def test_doc_template_has_a_distinct_resource_label():
    assert doc_agent._doc_label("学习笔记", "one_page") == "一页看懂"  # noqa: SLF001
    assert doc_agent._doc_label("学习笔记", "error_confusion") == "易错易混"  # noqa: SLF001


def test_remediation_disables_unrelated_generic_mock_fallback(monkeypatch):
    _install_doc_stubs(monkeypatch, audio_ok=False)
    monkeypatch.setattr(doc_agent, "is_demo", lambda: False)
    captured: dict[str, object] = {}

    async def capture_complete(*args, **kwargs):
        captured.update(kwargs)
        return "# 堆的最小补救\n\n堆使用完全二叉树结构。[^1]"

    monkeypatch.setattr(doc_agent, "llm_complete", capture_complete)
    asyncio.run(doc_agent._gen_one(  # noqa: SLF001
        "doc",
        "heap",
        {},
        topic_name="堆与优先队列",
        source_ids=[],
        goal="重讲堆的 Top-K 误区",
        prompt_template="remediation",
        trace_id="doc-remediation-test",
        skip_multimodal=True,
    ))

    assert captured["allow_mock_fallback"] is False


def test_remediation_rejects_successful_but_off_topic_content(monkeypatch):
    heap_chunk = {
        "text": "堆使用完全二叉树结构，并通过上浮和下沉维护堆序性质。",
        "source": "《数据结构与算法》讲义",
        "chapter": "堆",
        "kp": "heap",
        "page": 1,
        "source_type": "lecture",
        "source_id": "heap-notes",
    }
    monkeypatch.setattr(doc_agent, "retrieve", lambda *args, **kwargs: [heap_chunk])
    monkeypatch.setattr(doc_agent, "is_demo", lambda: False)

    async def off_topic_complete(*args, **kwargs):
        return "# 二叉搜索树精讲\n\n中序遍历会得到有序序列。[^1]"

    async def unexpected_grounding(*args, **kwargs):
        raise AssertionError("RAG fallback does not need an LLM grounding call")

    monkeypatch.setattr(doc_agent, "llm_complete", off_topic_complete)
    monkeypatch.setattr(doc_agent, "grounding_check", unexpected_grounding)
    monkeypatch.setattr(doc_agent, "safety_filter", lambda text: {"safe": True, "hits": []})

    result = asyncio.run(doc_agent._gen_one(  # noqa: SLF001
        "doc",
        "heap",
        {},
        topic_name="堆与优先队列",
        source_ids=[],
        goal="重讲堆的 Top-K 误区",
        prompt_template="remediation",
        trace_id="doc-remediation-drift-test",
        skip_multimodal=True,
    ))

    assert "堆与优先队列" in result["resource"]["payload"]["markdown"]
    assert "二叉搜索树精讲" not in result["resource"]["payload"]["markdown"]
    assert result["resource"]["payload"]["grounded"] is True
    assert any(flag["type"] == "topic_drift" for flag in result["flags"])

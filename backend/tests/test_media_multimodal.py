from __future__ import annotations

import asyncio
import json

from app.agents import media_agent


def _install_llm(monkeypatch):
    calls = 0
    monkeypatch.setattr(media_agent, "is_demo", lambda: False)

    async def fake_complete(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return (
                '{"title":"二叉树讲解","narration":"二叉树每个节点最多有两个孩子。",'
                '"scenes":[{"t":"0-10s","visual":"展示根节点与左右孩子","caption":"二叉树"}],'
                '"video_prompt":"binary tree educational animation"}'
            )
        return "```python\nfrom manim import *\nclass SceneBinaryTree(Scene):\n    pass\n```"

    monkeypatch.setattr(media_agent, "llm_complete", fake_complete)


def test_media_degrades_to_manim_and_keeps_real_tts(monkeypatch, tmp_path):
    _install_llm(monkeypatch)
    monkeypatch.setattr(media_agent, "GEN_DIR", tmp_path)

    async def degraded_video(*args, **kwargs):
        return {"ok": False, "degraded": True, "data": {}, "error": "not configured"}

    async def working_tts(*args, **kwargs):
        return {"ok": True, "degraded": False, "data": {"audio_url": "/static/gen/media-test.mp3"}}

    async def broken_cover(*args, **kwargs):
        raise RuntimeError("image provider crashed")

    monkeypatch.setattr(media_agent.multimodal_gateway, "video_create", degraded_video)
    monkeypatch.setattr(media_agent.multimodal_gateway, "tts", working_tts)
    monkeypatch.setattr(media_agent.multimodal_gateway, "text_to_image", broken_cover)

    out = asyncio.run(media_agent.run({
        "kinds": ["video"],
        "knowledge_points": ["binary_tree"],
        "session_id": "media-degraded",
    }))
    resource = next(iter(out["generated_resources"].values()))

    assert resource["kind"] == "video"
    assert resource["payload"]["script"]["title"] == "二叉树讲解"
    assert "SceneBinaryTree" in resource["payload"]["manim_code"]
    assert "```" not in resource["payload"]["manim_code"]
    compile(resource["payload"]["manim_code"], "<manim>", "exec")
    assert resource["payload"]["audio_url"] == "/static/gen/media-test.mp3"
    assert "cover_url" not in resource["payload"]
    assert out["progress_events"] == [{"agent": "media", "mode": "manim"}]


def test_media_survives_unexpected_video_and_postprocess_errors(monkeypatch, tmp_path):
    _install_llm(monkeypatch)
    monkeypatch.setattr(media_agent, "GEN_DIR", tmp_path)

    async def broken_video(*args, **kwargs):
        raise RuntimeError("video gateway crashed")

    async def broken_postprocess(*args, **kwargs):
        raise RuntimeError("postprocess crashed")

    monkeypatch.setattr(media_agent.multimodal_gateway, "video_create", broken_video)
    monkeypatch.setattr(media_agent.multimodal_gateway, "tts", broken_postprocess)
    monkeypatch.setattr(media_agent.multimodal_gateway, "text_to_image", broken_postprocess)

    out = asyncio.run(media_agent.run({
        "kinds": ["video"],
        "knowledge_points": ["binary_tree"],
        "session_id": "media-errors",
    }))
    resource = next(iter(out["generated_resources"].values()))

    assert resource["payload"]["video"]["status"] == "degraded"
    assert "manim_code" in resource["payload"]
    assert "audio_url" not in resource["payload"]
    assert "cover_url" not in resource["payload"]
    assert resource["payload"]["script"]


def test_cloud_video_returns_running_task_without_waiting_and_rejects_old_topic(monkeypatch, tmp_path):
    monkeypatch.setattr(media_agent, "GEN_DIR", tmp_path)
    monkeypatch.setattr(media_agent, "is_demo", lambda: False)
    captured: dict[str, object] = {}

    def fake_retrieve(*args, **kwargs):
        captured["kp"] = kwargs.get("kp")
        return [{
            "text": "排序是按关键字把元素重新排列，最小例子可以把 3、1、2 排成 1、2、3。",
            "citation": "排序讲义 p.1",
            "kp": "sorting",
        }]

    async def old_topic_script(*args, **kwargs):
        assert kwargs.get("allow_mock_fallback") is False
        return (
            '{"title":"二叉树中序遍历","narration":"二叉树左根右。",'
            '"scenes":[],"video_prompt":"binary tree"}'
        )

    async def create_task(*args, **kwargs):
        return {"ok": True, "data": {"task_id": "video-running-1", "status": "running", "provider": "xiaoyunque"}}

    async def must_not_wait(*args, **kwargs):
        raise AssertionError("resource generation must not wait for the cloud video")

    async def no_audio(*args, **kwargs):
        return {"ok": False, "data": {}, "error": "tts unavailable"}

    monkeypatch.setattr(media_agent, "retrieve", fake_retrieve)
    monkeypatch.setattr(media_agent, "llm_complete", old_topic_script)
    monkeypatch.setattr(media_agent.multimodal_gateway, "video_create", create_task)
    monkeypatch.setattr(media_agent.multimodal_gateway, "video_wait", must_not_wait)
    monkeypatch.setattr(media_agent.multimodal_gateway, "tts", no_audio)

    out = asyncio.run(media_agent.run({
        "kinds": ["video"],
        "knowledge_points": ["sorting_basic"],
        "source_ids": ["__course__"],
        "session_id": "video-immediate",
    }))
    resource = next(iter(out["generated_resources"].values()))

    assert captured["kp"] == "sorting_basic"
    assert resource["payload"]["video"]["status"] == "running"
    assert resource["payload"]["script"]["title"] == "基础排序 2 分钟讲透"
    assert "二叉树" not in json.dumps(resource["payload"]["script"], ensure_ascii=False)
    assert "3、1、2" in resource["payload"]["script"]["narration"]
    assert resource["payload"]["script"]["target_seconds"] == 120


def test_strict_sorting_example_never_absorbs_adjacent_chapter_topics(monkeypatch, tmp_path):
    monkeypatch.setattr(media_agent, "GEN_DIR", tmp_path)
    monkeypatch.setattr(media_agent, "is_demo", lambda: False)

    monkeypatch.setattr(media_agent, "retrieve", lambda *args, **kwargs: [{
        "text": (
            "基础排序会重新排列元素。计数排序适合小范围整数；"
            "快速排序使用基准分区；二叉树每个节点最多有两个孩子。"
        ),
        "citation": "宽章节 p.1",
        "kp": "sorting_basic,sorting_adv,binary_tree",
    }])

    async def must_not_call_llm(*args, **kwargs):
        raise AssertionError("strict 3,1,2 explanation must not call a drifting model")

    async def no_video(*args, **kwargs):
        return {"ok": False, "data": {}, "error": "disabled"}

    async def no_audio(*args, **kwargs):
        return {"ok": False, "data": {}, "error": "disabled"}

    monkeypatch.setattr(media_agent, "llm_complete", must_not_call_llm)
    monkeypatch.setattr(media_agent.multimodal_gateway, "video_create", no_video)
    monkeypatch.setattr(media_agent.multimodal_gateway, "tts", no_audio)

    out = asyncio.run(media_agent.run({
        "kinds": ["video"],
        "knowledge_points": ["sorting_basic"],
        "source_ids": ["__course__"],
        "conversation_focus": "什么是排序？请只用 3、1、2 这个最小例子说明。",
        "session_id": "video-strict-sorting-example",
    }))
    script = next(iter(out["generated_resources"].values()))["payload"]["script"]
    serialized = json.dumps(script, ensure_ascii=False)

    assert script["target_seconds"] == 120
    assert len(script["narration"]) >= 650
    assert "3、1、2" in script["narration"]
    assert all(term not in serialized for term in ("计数排序", "快速排序", "二叉树"))


def test_media_uses_pre_rendered_video_when_cloud_video_is_unavailable(monkeypatch, tmp_path):
    _install_llm(monkeypatch)
    monkeypatch.setattr(media_agent, "GEN_DIR", tmp_path)
    (tmp_path / "manim_binary_tree_traversal.mp4").write_bytes(b"fixed-manim-video")

    async def degraded_video(*args, **kwargs):
        return {"ok": False, "degraded": True, "data": {}, "error": "not configured"}

    async def degraded_postprocess(*args, **kwargs):
        return {"ok": False, "degraded": True, "data": {}, "error": "not configured"}

    monkeypatch.setattr(media_agent.multimodal_gateway, "video_create", degraded_video)
    monkeypatch.setattr(media_agent.multimodal_gateway, "tts", degraded_postprocess)
    monkeypatch.setattr(media_agent.multimodal_gateway, "text_to_image", degraded_postprocess)

    out = asyncio.run(media_agent.run({
        "kinds": ["video"],
        "knowledge_points": ["binary_tree"],
        "session_id": "media-local-manim",
    }))
    resource = next(iter(out["generated_resources"].values()))

    assert resource["payload"]["video"] == {
        "status": "succeeded",
        "url": "/static/gen/manim_binary_tree_traversal.mp4",
    }
    assert "manim_code" in resource["payload"]
    assert out["progress_events"] == [{"agent": "media", "mode": "local_manim"}]


def test_invalid_manim_is_replaced_with_renderable_scene():
    code = media_agent._normalize_manim_code(  # noqa: SLF001
        "```python\nclass SceneBinaryTree:\n    pass\n```",
        "SceneBinaryTree",
        "二叉树",
    )

    assert "class SceneBinaryTree(Scene):" in code
    assert "def construct(self):" in code
    assert "```" not in code
    compile(code, "<manim-fallback>", "exec")


def test_valid_manim_only_loses_markdown_fence():
    raw = "```python\nfrom manim import *\nclass SceneBinaryTree(Scene):\n    def construct(self):\n        self.wait()\n```"
    code = media_agent._normalize_manim_code(raw, "SceneBinaryTree", "二叉树")  # noqa: SLF001

    assert code.startswith("from manim import *")
    assert "self.wait()" in code
    assert "```" not in code


def test_explicit_python_animation_has_preview_and_downloadable_code(monkeypatch, tmp_path):
    monkeypatch.setattr(media_agent, "GEN_DIR", tmp_path)

    async def should_not_create_video(*args, **kwargs):
        raise AssertionError("explicit Python animation must not submit a cloud video task")

    async def degraded_postprocess(*args, **kwargs):
        return {"ok": False, "degraded": True, "data": {}, "error": "not configured"}

    monkeypatch.setattr(media_agent.multimodal_gateway, "video_create", should_not_create_video)
    monkeypatch.setattr(media_agent.multimodal_gateway, "tts", degraded_postprocess)
    monkeypatch.setattr(media_agent.multimodal_gateway, "text_to_image", degraded_postprocess)
    out = asyncio.run(media_agent.run({
        "kinds": ["python_animation"],
        "knowledge_points": ["binary_tree"],
        "session_id": "explicit-python-animation",
    }))
    resource = next(iter(out["generated_resources"].values()))
    assert resource["kind"] == "python_animation"
    assert resource["payload"]["animation_mode"] == "python_animation"
    assert len(resource["payload"]["animation_preview"]["stages"]) >= 3
    assert "FuncAnimation" in resource["payload"]["python_code"]
    compile(resource["payload"]["python_code"], "<python-animation>", "exec")
    assert out["progress_events"] == [{"agent": "media", "mode": "python_animation"}]


def test_explicit_manim_skips_cloud_video_and_keeps_browser_preview(monkeypatch, tmp_path):
    monkeypatch.setattr(media_agent, "GEN_DIR", tmp_path)

    async def should_not_create_video(*args, **kwargs):
        raise AssertionError("explicit Manim must not submit a cloud video task")

    async def degraded_postprocess(*args, **kwargs):
        return {"ok": False, "degraded": True, "data": {}, "error": "not configured"}

    monkeypatch.setattr(media_agent.multimodal_gateway, "video_create", should_not_create_video)
    monkeypatch.setattr(media_agent.multimodal_gateway, "tts", degraded_postprocess)
    monkeypatch.setattr(media_agent.multimodal_gateway, "text_to_image", degraded_postprocess)
    out = asyncio.run(media_agent.run({
        "kinds": ["manim"],
        "knowledge_points": ["binary_tree"],
        "session_id": "explicit-manim",
    }))
    resource = next(iter(out["generated_resources"].values()))
    assert resource["kind"] == "manim"
    assert resource["payload"]["animation_preview"]["stages"]
    assert "class SceneBinaryTree(Scene):" in resource["payload"]["manim_code"]

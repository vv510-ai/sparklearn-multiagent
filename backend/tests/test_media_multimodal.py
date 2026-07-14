from __future__ import annotations

import asyncio

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


def test_media_uses_pre_rendered_video_when_seedance_is_unavailable(monkeypatch, tmp_path):
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

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.llm import multimodal_gateway as gateway
from app.llm import local_ocr, spark_image, spark_ocr


@pytest.fixture(autouse=True)
def _non_demo_gateway(monkeypatch):
    monkeypatch.setattr(gateway, "is_demo", lambda: False)


def _settings(**overrides):
    values = {
        "spark_appid": "app",
        "spark_api_key": "key",
        "spark_api_secret": "secret",
        "spark_tti_appid": "",
        "spark_tti_api_key": "",
        "spark_tti_api_secret": "",
        "spark_vision_appid": "",
        "spark_vision_api_key": "",
        "spark_vision_api_secret": "",
        "spark_super_tts_api_password": "",
        "spark_super_tts_appid": "",
        "spark_super_tts_api_key": "",
        "spark_super_tts_api_secret": "",
        "spark_super_tts_voice": "x6_lingxiaoxuan_pro",
        "spark_super_tts_strict": False,
        "spark_asr_appid": "",
        "spark_asr_api_key": "",
        "spark_asr_api_secret": "",
        "xyq_access_key": "",
        "mm_xyq_image_enabled": True,
        "mm_ocr_enabled": True,
        "mm_local_ocr_enabled": False,
        "mm_asr_enabled": True,
        "mm_tts_enabled": True,
        "mm_image_enabled": True,
        "mm_video_enabled": True,
        # These cases test provider results, not thread-startup latency on Windows.
        # Timeout/budget tests override their own deadline below.
        "mm_ocr_tutor_timeout_s": 0.5,
        "mm_ocr_ingest_timeout_s": 0.5,
        "mm_local_ocr_timeout_s": 0.5,
        "mm_asr_timeout_s": 0.5,
        "mm_tts_timeout_s": 0.5,
        "mm_image_timeout_s": 0.5,
        "mm_xyq_image_wait_budget_s": 0.05,
        "mm_xyq_image_poll_interval_s": 0.001,
        "mm_image_download_timeout_s": 0.2,
        "mm_image_max_mb": 8,
        "mm_video_create_timeout_s": 0.5,
        "mm_video_wait_budget_s": 0.02,
        "mm_video_poll_timeout_s": 0.5,
        "mm_video_download_timeout_s": 0.2,
        "mm_video_max_mb": 8,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_disabled_capability_degrades_without_call(monkeypatch):
    settings = _settings(mm_tts_enabled=False)
    called = False

    def provider(*args, **kwargs):
        nonlocal called
        called = True
        return "/static/gen/should-not-exist.mp3"

    monkeypatch.setattr(gateway, "get_settings", lambda: settings)
    monkeypatch.setattr(gateway.spark_tts, "synthesize", provider)
    result = asyncio.run(gateway.tts("test", trace_id="disabled-test"))

    assert result["ok"] is False
    assert result["degraded"] is True
    assert "disabled" in result["error"]
    assert called is False


def test_forced_demo_never_calls_real_tts(monkeypatch):
    settings = _settings()
    called = False

    def provider(*args, **kwargs):
        nonlocal called
        called = True
        return "/static/gen/should-not-exist.mp3"

    monkeypatch.setattr(gateway, "get_settings", lambda: settings)
    monkeypatch.setattr(gateway, "is_demo", lambda: True)
    monkeypatch.setattr(gateway.spark_tts, "synthesize", provider)
    result = asyncio.run(gateway.tts("offline demo", trace_id="demo-no-network"))

    assert result["ok"] is False
    assert result["degraded"] is True
    assert called is False


def test_slow_tts_times_out_without_blocking_event_loop(monkeypatch):
    settings = _settings(mm_tts_timeout_s=0.01)
    marker_reached = False

    def slow_provider(*args, **kwargs):
        time.sleep(0.08)
        return None

    async def scenario():
        nonlocal marker_reached

        async def marker():
            nonlocal marker_reached
            await asyncio.sleep(0.003)
            marker_reached = True

        result, _ = await asyncio.gather(
            gateway.tts("slow", trace_id="timeout-test"),
            marker(),
        )
        return result

    monkeypatch.setattr(gateway, "get_settings", lambda: settings)
    monkeypatch.setattr(gateway.spark_super_tts, "configured", lambda _settings=None: False)
    monkeypatch.setattr(gateway.spark_tts, "synthesize", slow_provider)
    result = asyncio.run(scenario())

    assert marker_reached is True
    assert result["ok"] is False
    assert result["degraded"] is True
    assert "timeout" in result["error"]


def test_saturated_multimodal_pool_degrades_without_provider_call(monkeypatch):
    settings = _settings()
    called = False

    class NoSlots:
        @staticmethod
        def acquire(*, blocking):
            assert blocking is False
            return False

    def provider(*args, **kwargs):
        nonlocal called
        called = True
        return "/static/gen/should-not-exist.mp3"

    monkeypatch.setattr(gateway, "get_settings", lambda: settings)
    monkeypatch.setattr(gateway, "_MM_SLOTS", NoSlots())
    monkeypatch.setattr(gateway.spark_tts, "synthesize", provider)

    result = asyncio.run(gateway.tts("pool full", trace_id="pool-saturated"))

    assert result["ok"] is False
    assert result["degraded"] is True
    assert "pool saturated" in result["error"]
    assert called is False


def test_tts_uses_stable_content_cache(monkeypatch, tmp_path: Path):
    # A previous timeout test deliberately leaves its worker finishing in the
    # shared pool. Give this cache contract enough scheduling headroom without
    # changing the production timeout behavior under test elsewhere.
    settings = _settings(mm_tts_timeout_s=0.2)
    calls = 0

    def provider(text, *, voice, filename):
        nonlocal calls
        calls += 1
        (tmp_path / filename).write_bytes(b"ID3-test-audio" + b"x" * 200)
        return f"/static/gen/{filename}"

    monkeypatch.setattr(gateway, "GEN_DIR", tmp_path)
    monkeypatch.setattr(gateway, "get_settings", lambda: settings)
    monkeypatch.setattr(gateway.spark_tts, "synthesize", provider)

    first = asyncio.run(gateway.tts("same text", trace_id="cache-1"))
    second = asyncio.run(gateway.tts("same text", trace_id="cache-2"))

    assert first["ok"] is True, first
    assert first["data"]["cached"] is False
    assert second["ok"] is True, second
    assert second["data"]["cached"] is True
    assert first["data"]["audio_url"] == second["data"]["audio_url"]
    assert calls == 1


def test_tts_prefers_super_voice_and_reports_provider(monkeypatch, tmp_path: Path):
    settings = _settings(
        spark_super_tts_api_password="super-password",
        spark_super_tts_appid="super-app",
        mm_tts_timeout_s=0.2,
    )
    standard_called = False

    def super_provider(text, *, voice, filename):
        assert voice == "x6_lingxiaoxuan_pro"
        (tmp_path / filename).write_bytes(b"ID3-super-audio")
        return f"/static/gen/{filename}"

    def standard_provider(*args, **kwargs):
        nonlocal standard_called
        standard_called = True
        raise AssertionError("standard TTS should not run when super TTS succeeds")

    monkeypatch.setattr(gateway, "GEN_DIR", tmp_path)
    monkeypatch.setattr(gateway, "get_settings", lambda: settings)
    monkeypatch.setattr(gateway.spark_super_tts, "synthesize", super_provider)
    monkeypatch.setattr(gateway.spark_tts, "synthesize", standard_provider)

    result = asyncio.run(gateway.tts("超拟人语音", trace_id="super-tts"))

    assert result["ok"] is True, result
    assert result["degraded"] is False
    assert result["data"]["provider"] == "spark_super_tts"
    assert standard_called is False


def test_standard_cache_does_not_mask_recovered_super_tts(monkeypatch, tmp_path: Path):
    settings = _settings(
        spark_super_tts_api_password="super-password",
        spark_super_tts_appid="super-app",
        mm_tts_timeout_s=0.2,
    )
    text = "recovered super voice"
    standard_digest = hashlib.sha1(
        f"standard\0xiaoyan\0{42}\0{text}".encode("utf-8")
    ).hexdigest()[:16]
    (tmp_path / f"tts_standard_{standard_digest}.wav").write_bytes(
        b"RIFF-cached-standard" + b"x" * 200
    )
    super_calls = 0

    def super_provider(value, *, voice, filename):
        nonlocal super_calls
        super_calls += 1
        assert value == text
        assert voice == "x6_lingxiaoxuan_pro"
        (tmp_path / filename).write_bytes(b"ID3-super-audio" + b"x" * 1200)
        return f"/static/gen/{filename}"

    def standard_provider(*args, **kwargs):
        raise AssertionError("cached standard TTS should only be used after super TTS fails")

    monkeypatch.setattr(gateway, "GEN_DIR", tmp_path)
    monkeypatch.setattr(gateway, "get_settings", lambda: settings)
    monkeypatch.setattr(gateway.spark_super_tts, "synthesize", super_provider)
    monkeypatch.setattr(gateway.spark_tts, "synthesize", standard_provider)

    result = asyncio.run(gateway.tts(text, trace_id="super-cache-recovery"))

    assert result["ok"] is True, result
    assert result["degraded"] is False
    assert result["data"]["provider"] == "spark_super_tts"
    assert result["data"]["cached"] is False
    assert super_calls == 1


def test_tts_strict_super_voice_never_plays_standard_provider(monkeypatch, tmp_path: Path):
    settings = _settings(
        spark_super_tts_api_password="super-password",
        spark_super_tts_appid="super-app",
        spark_super_tts_strict=True,
        mm_tts_timeout_s=0.2,
    )

    def broken_super(*args, **kwargs):
        raise RuntimeError("super voice unavailable")

    standard_called = False

    def standard_provider(*args, **kwargs):
        nonlocal standard_called
        standard_called = True
        raise AssertionError("strict super voice must not fall back to another voice")

    monkeypatch.setattr(gateway, "GEN_DIR", tmp_path)
    monkeypatch.setattr(gateway, "get_settings", lambda: settings)
    monkeypatch.setattr(gateway.spark_super_tts, "synthesize", broken_super)
    monkeypatch.setattr(gateway.spark_tts, "synthesize", standard_provider)

    result = asyncio.run(gateway.tts("自动降级", trace_id="super-fallback"))

    assert result["ok"] is False, result
    assert result["degraded"] is True
    assert result["data"]["provider"] == "spark_super_tts"
    assert result["data"]["strict_voice"] is True
    assert result["data"]["retryable"] is True
    assert "super voice unavailable" in result["error"]
    assert standard_called is False


def test_tts_can_fall_back_when_strict_super_is_disabled(monkeypatch, tmp_path: Path):
    settings = _settings(
        spark_super_tts_api_password="super-password",
        spark_super_tts_appid="super-app",
        spark_super_tts_strict=False,
        mm_tts_timeout_s=0.2,
    )

    def broken_super(*args, **kwargs):
        raise RuntimeError("super voice unavailable")

    def standard_provider(text, *, voice, filename):
        (tmp_path / filename).write_bytes(b"ID3-standard-audio")
        return f"/static/gen/{filename}"

    monkeypatch.setattr(gateway, "GEN_DIR", tmp_path)
    monkeypatch.setattr(gateway, "get_settings", lambda: settings)
    monkeypatch.setattr(gateway.spark_super_tts, "synthesize", broken_super)
    monkeypatch.setattr(gateway.spark_tts, "synthesize", standard_provider)

    result = asyncio.run(gateway.tts("explicit fallback", trace_id="super-fallback"))

    assert result["ok"] is True, result
    assert result["degraded"] is True
    assert result["data"]["provider"] == "spark_tts"
    assert "super voice unavailable" in result["error"]


def test_provider_exception_is_a_degraded_result(monkeypatch):
    settings = _settings()

    def broken_provider(*args, **kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(gateway, "get_settings", lambda: settings)
    monkeypatch.setattr(gateway.spark_image, "generate_image", broken_provider)
    result = asyncio.run(gateway.text_to_image("binary tree", trace_id="image-fail"))

    assert result["ok"] is False
    assert result["degraded"] is True
    assert result["capability"] == "image"
    assert "provider unavailable" in result["error"]


def test_image_uses_spark_provider(monkeypatch, tmp_path: Path):
    settings = _settings()

    def spark_provider(*args, **kwargs):
        output = tmp_path / "spark-image.jpg"
        output.write_bytes(b"\xff\xd8\xffmock-image")
        return f"/static/gen/{output.name}"

    monkeypatch.setattr(gateway, "GEN_DIR", tmp_path)
    monkeypatch.setattr(gateway, "get_settings", lambda: settings)
    monkeypatch.setattr(gateway.spark_image, "generate_image", spark_provider)

    result = asyncio.run(gateway.text_to_image("binary tree", trace_id="image-spark"))

    assert result["ok"] is True, result
    assert result["degraded"] is False
    assert result["data"]["provider"] == "spark"
    assert result["data"]["image_url"].endswith(".jpg")
    assert result["error"] == ""


def test_one_page_image_prefers_xiaoyunque(monkeypatch, tmp_path: Path):
    settings = _settings(xyq_access_key="test-xyq-key")
    other_provider_called = False

    def xyq_provider(prompt, digest, provider_settings):
        assert "二叉树" in prompt
        assert provider_settings is settings
        output = tmp_path / f"xiaoyunque_img_{digest}.png"
        output.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 64)
        return f"/static/gen/{output.name}"

    def other_provider(*args, **kwargs):
        nonlocal other_provider_called
        other_provider_called = True
        raise AssertionError("fallback provider should not run")

    monkeypatch.setattr(gateway, "GEN_DIR", tmp_path)
    monkeypatch.setattr(gateway, "get_settings", lambda: settings)
    monkeypatch.setattr(gateway.xiaoyunque_client, "available", lambda: True)
    monkeypatch.setattr(gateway, "_generate_xiaoyunque_image", xyq_provider)
    monkeypatch.setattr(gateway.spark_image, "generate_image", other_provider)

    result = asyncio.run(gateway.text_to_image(
        "一图看懂二叉树",
        width=1536,
        height=864,
        preferred_provider="xiaoyunque",
        trace_id="one-page-xiaoyunque",
    ))

    assert result["ok"] is True, result
    assert result["data"]["provider"] == "xiaoyunque"
    assert result["data"]["image_url"].endswith(".png")
    assert other_provider_called is False


def test_xiaoyunque_image_download_is_signature_checked(monkeypatch, tmp_path: Path):
    image_data = b"\x89PNG\r\n\x1a\n" + b"image-data" * 8

    class FakeDownload:
        headers = {"content-length": str(len(image_data))}

        @staticmethod
        def raise_for_status():
            return None

        @staticmethod
        def iter_content(chunk_size):
            assert chunk_size > 0
            return [image_data]

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

    monkeypatch.setattr(gateway.requests, "get", lambda *args, **kwargs: FakeDownload())

    target = gateway._download_image(  # noqa: SLF001
        "https://cdn.test/knowledge-map",
        tmp_path / "owned-map",
        timeout_s=1,
        max_bytes=1024,
    )

    assert target == tmp_path / "owned-map.png"
    assert target.read_bytes() == image_data
    assert not list(tmp_path.glob("*.part"))


def test_xiaoyunque_image_download_rejects_insecure_url(tmp_path: Path):
    with pytest.raises(ValueError, match="HTTPS"):
        gateway._download_image(  # noqa: SLF001
            "http://cdn.test/knowledge-map.png",
            tmp_path / "owned-map",
            timeout_s=1,
            max_bytes=1024,
        )


def test_video_budget_hands_running_task_to_frontend(monkeypatch):
    settings = _settings(mm_video_wait_budget_s=0.015)
    monkeypatch.setattr(gateway, "get_settings", lambda: settings)
    monkeypatch.setattr(gateway.xiaoyunque_client, "available", lambda: True)
    monkeypatch.setattr(
        gateway.xiaoyunque_client,
        "create_task",
        lambda prompt, image_url=None: "task-1",
    )
    monkeypatch.setattr(
        gateway.xiaoyunque_client,
        "poll_task",
        lambda task_id: {
            "status": "running",
            "task_id": task_id,
            "provider": "xiaoyunque",
        },
    )

    created = asyncio.run(gateway.video_create("demo", trace_id="video-create"))
    waited = asyncio.run(
        gateway.video_wait(
            created["data"]["task_id"],
            budget_s=0.015,
            trace_id="video-wait",
        )
    )

    assert created["ok"] is True
    assert waited["ok"] is True
    assert waited["degraded"] is False
    assert waited["data"] == {
        "status": "running",
        "task_id": "task-1",
        "provider": "xiaoyunque",
    }


def test_paid_video_submission_preserves_a_receipt_after_outer_budget(monkeypatch):
    monkeypatch.setattr(gateway, "get_settings", lambda: _settings(mm_video_create_timeout_s=0.02))
    monkeypatch.setattr(gateway.xiaoyunque_client, "available", lambda: True)
    calls = []

    def delayed_receipt(prompt, image_url=None):
        calls.append(prompt)
        time.sleep(0.06)
        return "xyq_late_receipt"

    monkeypatch.setattr(gateway.xiaoyunque_client, "create_task", delayed_receipt)
    result = asyncio.run(gateway.video_create("变量赋值"))
    assert result["ok"] and result["data"]["task_id"] == "xyq_late_receipt"
    assert calls == ["变量赋值"]


def test_paid_video_lost_http_receipt_does_not_become_a_successful_fallback(monkeypatch):
    from app.services.generation_jobs import SubmissionUncertain
    monkeypatch.setattr(gateway, "get_settings", lambda: _settings())
    monkeypatch.setattr(gateway.xiaoyunque_client, "available", lambda: True)

    def lost_receipt(*args):
        raise gateway.requests.ReadTimeout("response lost after submission")

    monkeypatch.setattr(gateway.xiaoyunque_client, "create_task", lost_receipt)
    with pytest.raises(SubmissionUncertain):
        asyncio.run(gateway.video_create("变量赋值"))


def test_video_poll_materializes_and_reuses_provider_mp4(monkeypatch, tmp_path: Path):
    settings = _settings(mm_video_poll_timeout_s=0.2, mm_video_download_timeout_s=0.2)
    task_id = "xyq:test-materialize"
    provider_url = "https://video.example.test/signed/video.mp4"
    media = b"\x00\x00\x00\x20ftypisom" + b"x" * 2048
    downloads = 0

    class FakeResponse:
        headers = {"content-length": str(len(media)), "content-type": "video/mp4"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        @staticmethod
        def raise_for_status():
            return None

        @staticmethod
        def iter_content(_size):
            yield media

    def fake_download(*_args, **_kwargs):
        nonlocal downloads
        downloads += 1
        return FakeResponse()

    monkeypatch.setattr(gateway, "GEN_DIR", tmp_path)
    monkeypatch.setattr(gateway, "get_settings", lambda: settings)
    monkeypatch.setattr(gateway.xiaoyunque_client, "available", lambda: True)
    monkeypatch.setattr(
        gateway.xiaoyunque_client,
        "poll_task",
        lambda value: {
            "status": "succeeded",
            "task_id": value,
            "provider": "xiaoyunque",
            "url": provider_url,
            "urls": [provider_url],
        },
    )
    monkeypatch.setattr(gateway.requests, "get", fake_download)

    first = asyncio.run(gateway.video_poll(task_id, trace_id="video-materialize"))

    assert first["status"] == "succeeded"
    assert first["url"].startswith("/static/gen/xiaoyunque_")
    assert first["stored"] is True
    assert first["cached"] is False
    assert provider_url not in str(first)
    assert gateway._video_target(task_id).read_bytes() == media
    assert downloads == 1

    monkeypatch.setattr(
        gateway.xiaoyunque_client,
        "poll_task",
        lambda _value: (_ for _ in ()).throw(AssertionError("cached video must not poll provider")),
    )
    second = asyncio.run(gateway.video_poll(task_id, trace_id="video-cache"))

    assert second["url"] == first["url"]
    assert second["cached"] is True
    assert downloads == 1


def test_video_poll_rejects_non_mp4_response(monkeypatch, tmp_path: Path):
    settings = _settings(mm_video_poll_timeout_s=0.2, mm_video_download_timeout_s=0.2)
    body = b"<html>forbidden</html>" + b"x" * 2048

    class FakeResponse:
        headers = {"content-length": str(len(body)), "content-type": "text/html"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        @staticmethod
        def raise_for_status():
            return None

        @staticmethod
        def iter_content(_size):
            yield body

    monkeypatch.setattr(gateway, "GEN_DIR", tmp_path)
    monkeypatch.setattr(gateway, "get_settings", lambda: settings)
    monkeypatch.setattr(gateway.xiaoyunque_client, "available", lambda: True)
    monkeypatch.setattr(
        gateway.xiaoyunque_client,
        "poll_task",
        lambda value: {
            "status": "succeeded",
            "task_id": value,
            "provider": "xiaoyunque",
            "url": "https://video.example.test/not-a-video",
        },
    )
    monkeypatch.setattr(gateway.requests, "get", lambda *_args, **_kwargs: FakeResponse())

    result = asyncio.run(gateway.video_poll("xyq:invalid-video", trace_id="video-invalid"))

    assert result["status"] == "running"
    assert result["retryable"] is True
    assert "invalid MP4" in result["error"]
    assert list(tmp_path.iterdir()) == []


def test_demo_ocr_keeps_existing_sample_behavior(monkeypatch):
    settings = _settings(spark_appid="", spark_api_key="", spark_api_secret="")
    monkeypatch.setattr(gateway, "get_settings", lambda: settings)
    monkeypatch.setattr(gateway, "is_demo", lambda: True)
    monkeypatch.setattr(
        gateway.spark_ocr,
        "image_to_question",
        lambda image, hint="", max_tokens=1024, timeout_s=30: "演示题面",
    )

    result = asyncio.run(gateway.ocr_image(b"image", trace_id="ocr-demo"))

    assert result["ok"] is True
    assert result["data"]["text"] == "演示题面"


def test_ocr_falls_back_to_local_engine(monkeypatch):
    settings = _settings(mm_local_ocr_enabled=True)
    monkeypatch.setattr(gateway, "get_settings", lambda: settings)
    monkeypatch.setattr(gateway.spark_ocr, "image_to_question", lambda *args, **kwargs: (_ for _ in ()).throw(
        RuntimeError("spark image understanding code=11200")
    ))
    monkeypatch.setattr(gateway.local_ocr, "available", lambda: True)
    monkeypatch.setattr(
        gateway.local_ocr,
        "recognize",
        lambda image: {
            "text": "二叉树前序遍历",
            "lines": 1,
            "confidence": 0.98,
            "engine": "rapidocr-onnx",
        },
    )

    result = asyncio.run(gateway.ocr_image(b"image", trace_id="ocr-local-fallback"))

    assert result["ok"] is True
    assert result["degraded"] is True
    assert result["data"]["text"] == "二叉树前序遍历"
    assert result["data"]["engine"] == "rapidocr-onnx"
    assert "11200" in result["error"]


def test_local_ocr_normalizes_lines_and_confidence(monkeypatch):
    output = SimpleNamespace(
        txts=(" 二叉树 ", "", "前序遍历"),
        scores=(0.99, 0.8, 0.95),
    )
    monkeypatch.setattr(local_ocr, "_engine", lambda image: output)

    result = local_ocr.recognize(b"image")

    assert result == {
        "text": "二叉树\n前序遍历",
        "lines": 2,
        "confidence": 0.97,
        "engine": "rapidocr-onnx",
    }


def test_ocr_provider_error_keeps_code_and_sid(monkeypatch):
    sent_requests = []

    class FakeWebSocketApp:
        def __init__(self, url, **callbacks):
            self.callbacks = callbacks

        def send(self, payload):
            sent_requests.append(json.loads(payload))

        def close(self):
            return None

        def run_forever(self):
            self.callbacks["on_open"](self)
            self.callbacks["on_message"](
                self,
                json.dumps(
                    {
                        "header": {
                            "code": 11200,
                            "message": "AppIdNoAuthError: domain.image",
                            "sid": "ocr-sid-1",
                        }
                    }
                ),
            )

    monkeypatch.setattr(spark_ocr, "is_demo", lambda: False)
    monkeypatch.setattr(
        spark_ocr,
        "get_settings",
        lambda: SimpleNamespace(
            spark_appid="app",
            spark_api_key="key",
            spark_api_secret="secret",
            spark_vision_appid="vision-app",
            spark_vision_api_key="vision-key",
            spark_vision_api_secret="vision-secret",
        ),
    )
    signed = {}

    def fake_sign(_url, api_key, api_secret, **_kwargs):
        signed.update(api_key=api_key, api_secret=api_secret)
        return "https://signed.invalid"

    monkeypatch.setattr(spark_ocr, "assemble_auth_url", fake_sign)
    monkeypatch.setitem(sys.modules, "websocket", SimpleNamespace(WebSocketApp=FakeWebSocketApp))

    with pytest.raises(RuntimeError) as exc_info:
        spark_ocr.image_to_question(b"image")

    error = str(exc_info.value)
    assert "code=11200" in error
    assert "sid=ocr-sid-1" in error
    assert signed == {"api_key": "vision-key", "api_secret": "vision-secret"}
    assert sent_requests[0]["header"]["app_id"] == "vision-app"
    assert sent_requests[0]["parameter"]["chat"]["domain"] == "general"


def test_ocr_provider_watchdog_closes_stalled_websocket(monkeypatch):
    class StalledWebSocketApp:
        def __init__(self, url, **callbacks):
            self.callbacks = callbacks
            self.closed = threading.Event()

        def send(self, payload):
            json.loads(payload)

        def close(self):
            self.closed.set()

        def run_forever(self):
            self.callbacks["on_open"](self)
            assert self.closed.wait(0.5)

    monkeypatch.setattr(spark_ocr, "is_demo", lambda: False)
    monkeypatch.setattr(
        spark_ocr,
        "get_settings",
        lambda: SimpleNamespace(
            spark_appid="app",
            spark_api_key="key",
            spark_api_secret="secret",
            spark_image_domain="general",
        ),
    )
    monkeypatch.setattr(spark_ocr, "assemble_auth_url", lambda *args, **kwargs: "https://signed.invalid")
    monkeypatch.setitem(sys.modules, "websocket", SimpleNamespace(WebSocketApp=StalledWebSocketApp))

    started = time.monotonic()
    with pytest.raises(RuntimeError, match="provider timeout"):
        spark_ocr.image_to_question(b"image", timeout_s=0.02)

    assert time.monotonic() - started < 0.5


def test_image_provider_error_keeps_code_and_sid(monkeypatch):
    sent_bodies = []

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {
                "header": {
                    "code": 10005,
                    "message": "invalid resolution",
                    "sid": "tti-sid-1",
                }
            }

    monkeypatch.setattr(
        spark_image,
        "get_settings",
        lambda: SimpleNamespace(
            spark_appid="app",
            spark_api_key="key",
            spark_api_secret="secret",
            spark_tti_appid="tti-app",
            spark_tti_api_key="tti-key",
            spark_tti_api_secret="tti-secret",
        ),
    )
    signed = {}

    def fake_sign(_url, api_key, api_secret, **_kwargs):
        signed.update(api_key=api_key, api_secret=api_secret)
        return "https://signed.invalid"

    monkeypatch.setattr(spark_image, "assemble_auth_url", fake_sign)
    def fake_post(*args, **kwargs):
        sent_bodies.append(kwargs["json"])
        return FakeResponse()

    monkeypatch.setattr(spark_image.requests, "post", fake_post)

    with pytest.raises(RuntimeError) as exc_info:
        spark_image.generate_image("binary tree")

    error = str(exc_info.value)
    assert "code=10005" in error
    assert "sid=tti-sid-1" in error
    assert signed == {"api_key": "tti-key", "api_secret": "tti-secret"}
    assert sent_bodies[0]["header"]["app_id"] == "tti-app"
    assert sent_bodies[0]["parameter"]["chat"]["width"] == 768
    assert sent_bodies[0]["parameter"]["chat"]["height"] == 768


def test_strict_xiaoyunque_failure_does_not_call_spark(monkeypatch, tmp_path):
    monkeypatch.setattr(gateway, "GEN_DIR", tmp_path)
    monkeypatch.setattr(gateway, "get_settings", lambda: _settings(xyq_access_key="test"))
    monkeypatch.setattr(gateway.xiaoyunque_client, "available", lambda: True)
    monkeypatch.setattr(gateway, "_generate_xiaoyunque_image", lambda *a: (_ for _ in ()).throw(RuntimeError("unavailable")))
    monkeypatch.setattr(gateway.spark_image, "generate_image", lambda *a, **k: pytest.fail("must not change provider"))
    result = asyncio.run(gateway.text_to_image("知识图", preferred_provider="xiaoyunque", allow_provider_fallback=False))
    assert not result["ok"]


def test_strict_image_cache_retains_provider_and_is_tenant_scoped(monkeypatch, tmp_path):
    monkeypatch.setattr(gateway, "GEN_DIR", tmp_path)
    monkeypatch.setattr(gateway, "get_settings", lambda: _settings(xyq_access_key="test"))
    monkeypatch.setattr(gateway.xiaoyunque_client, "available", lambda: True)
    calls = []
    def generate(prompt, digest, settings):
        calls.append(digest)
        target = tmp_path / f"source_{digest}.png"
        target.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x"*64)
        return f"/static/gen/{target.name}"
    monkeypatch.setattr(gateway, "_generate_xiaoyunque_image", generate)
    monkeypatch.setattr(gateway, "current_user_id", lambda: "first")
    for _ in range(2):
        result = asyncio.run(gateway.text_to_image("知识图", preferred_provider="xiaoyunque", allow_provider_fallback=False))
        assert result["ok"] and result["data"]["provider"] == "xiaoyunque"
    assert len(calls) == 1 and result["data"]["cached"]
    monkeypatch.setattr(gateway, "current_user_id", lambda: "second")
    result = asyncio.run(gateway.text_to_image("知识图", preferred_provider="xiaoyunque", allow_provider_fallback=False))
    assert len(calls) == 2 and not result["data"]["cached"]

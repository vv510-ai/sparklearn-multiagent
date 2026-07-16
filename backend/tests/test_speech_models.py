from __future__ import annotations

import asyncio
import base64
import json
import sys
import threading
from io import BytesIO
from types import SimpleNamespace

import pytest
from starlette.datastructures import Headers, UploadFile

from app.api import tutor as tutor_api
from app.llm import spark_asr, spark_super_tts


def test_super_tts_apipassword_request_and_sequence_order(monkeypatch, tmp_path):
    sent = []
    connected = {}

    class FakeWebSocketApp:
        def __init__(self, url, header=None, **callbacks):
            connected["url"] = url
            connected["header"] = header
            self.callbacks = callbacks

        def send(self, payload):
            sent.append(json.loads(payload))

        def close(self):
            return None

        def run_forever(self, **kwargs):
            self.callbacks["on_open"](self)
            self.callbacks["on_message"](
                self,
                json.dumps({
                    "header": {"code": 0, "status": 0},
                    "payload": {"audio": {
                        "seq": 1,
                        "status": 0,
                        "audio": base64.b64encode(b"b" * 700).decode("ascii"),
                    }},
                }),
            )
            self.callbacks["on_message"](
                self,
                json.dumps({
                    "header": {"code": 0, "status": 2},
                    "payload": {"audio": {
                        "seq": 0,
                        "status": 2,
                        "audio": base64.b64encode(b"a" * 700).decode("ascii"),
                    }},
                }),
            )

    settings = SimpleNamespace(
        spark_super_tts_api_password="private-password",
        spark_super_tts_appid="super-app",
        spark_super_tts_api_key="",
        spark_super_tts_api_secret="",
        spark_super_tts_url="wss://super.example.test/v1/private/model",
        spark_super_tts_voice="x6_lingxiaoxuan_pro",
        mm_tts_timeout_s=0.2,
    )
    monkeypatch.setattr(spark_super_tts, "get_settings", lambda: settings)
    monkeypatch.setattr(spark_super_tts, "GEN_DIR", tmp_path)
    monkeypatch.setitem(sys.modules, "websocket", SimpleNamespace(WebSocketApp=FakeWebSocketApp))

    url = spark_super_tts.synthesize("你好", filename="super.mp3")

    assert url == "/static/gen/super.mp3"
    assert (tmp_path / "super.mp3").read_bytes() == b"a" * 700 + b"b" * 700
    assert connected["header"] == {"x-api-key": "private-password"}
    assert sent[0]["header"]["app_id"] == "super-app"
    assert sent[0]["parameter"]["tts"]["vcn"] == "x6_lingxiaoxuan_pro"
    assert sent[0]["parameter"]["tts"]["audio"]["encoding"] == "lame"
    assert base64.b64decode(sent[0]["payload"]["text"]["text"]).decode("utf-8") == "你好"


def test_super_tts_rejects_unusably_short_audio(monkeypatch, tmp_path):
    class FakeWebSocketApp:
        def __init__(self, _url, **callbacks):
            self.callbacks = callbacks

        def send(self, _payload):
            return None

        def close(self):
            return None

        def run_forever(self, **_kwargs):
            self.callbacks["on_open"](self)
            self.callbacks["on_message"](
                self,
                json.dumps({
                    "header": {"code": 0, "status": 2},
                    "payload": {"audio": {
                        "seq": 0,
                        "status": 2,
                        "audio": base64.b64encode(b"silent" * 48).decode("ascii"),
                    }},
                }),
            )

    settings = SimpleNamespace(
        spark_super_tts_api_password="private-password",
        spark_super_tts_appid="super-app",
        spark_super_tts_url="wss://super.example.test/v1/private/model",
        spark_super_tts_voice="x6_lingxiaoxuan_pro",
        mm_tts_timeout_s=0.2,
    )
    monkeypatch.setattr(spark_super_tts, "get_settings", lambda: settings)
    monkeypatch.setattr(spark_super_tts, "GEN_DIR", tmp_path)
    monkeypatch.setitem(sys.modules, "websocket", SimpleNamespace(WebSocketApp=FakeWebSocketApp))

    with pytest.raises(RuntimeError, match="unusably short audio"):
        spark_super_tts.synthesize("这段音频不能被误判为成功", filename="too-short.mp3")

    assert not (tmp_path / "too-short.mp3").exists()


def test_asr_sends_model_parameters_and_decodes_text(monkeypatch):
    requests = []

    class FakeWebSocketApp:
        def __init__(self, url, **callbacks):
            self.callbacks = callbacks
            self.closed = threading.Event()

        def send(self, payload):
            request = json.loads(payload)
            requests.append(request)
            if request["header"]["status"] != 2:
                return
            recognized = {
                "sn": 1,
                "ret": 0,
                "ws": [{"cw": [{"w": "二叉树是什么"}]}],
            }
            self.callbacks["on_message"](
                self,
                json.dumps({
                    "header": {"code": 0, "status": 2},
                    "payload": {"result": {
                        "status": 2,
                        "text": base64.b64encode(
                            json.dumps(recognized, ensure_ascii=False).encode("utf-8")
                        ).decode("ascii"),
                    }},
                }),
            )

        def close(self):
            self.closed.set()

        def run_forever(self, **kwargs):
            self.callbacks["on_open"](self)
            assert self.closed.wait(1)

    settings = SimpleNamespace(
        spark_asr_appid="asr-app",
        spark_asr_api_key="asr-key",
        spark_asr_api_secret="asr-secret",
        spark_asr_url="wss://iat.example.test/v1",
        mm_asr_timeout_s=1,
    )
    monkeypatch.setattr(spark_asr, "get_settings", lambda: settings)
    monkeypatch.setattr(spark_asr, "assemble_auth_url", lambda *args, **kwargs: "https://signed.test")
    monkeypatch.setitem(sys.modules, "websocket", SimpleNamespace(WebSocketApp=FakeWebSocketApp))

    text = spark_asr.transcribe(b"\x00\x01" * 100, timeout_s=1)

    assert text == "二叉树是什么"
    assert requests[0]["parameter"]["iat"]["domain"] == "slm"
    assert requests[0]["parameter"]["iat"]["language"] == "zh_cn"
    assert requests[-1]["header"]["status"] == 2


def test_transcribe_api_returns_gateway_text(monkeypatch):
    async def fake_speech_to_text(*args, **kwargs):
        return {
            "ok": True,
            "data": {"text": "为什么二叉树最多有两个孩子", "provider": "spark_asr"},
            "elapsed_ms": 42,
        }

    monkeypatch.setattr(tutor_api.multimodal_gateway, "speech_to_text", fake_speech_to_text)
    upload = UploadFile(
        file=BytesIO(b"\x00\x00" * 1600),
        filename="question.pcm",
        headers=Headers({"content-type": "audio/pcm"}),
    )

    result = asyncio.run(tutor_api.transcribe_question(upload, "voice-user", "raw", 16000))

    assert result["text"] == "为什么二叉树最多有两个孩子"
    assert result["provider"] == "spark_asr"
    assert result["duration_s"] == 0.1

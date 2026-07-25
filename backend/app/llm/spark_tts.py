"""讯飞在线语音合成 TTS(流式 WebSocket wss://tts-api.xfyun.cn/v2/tts)。

无三元组时降级:返回 None 并由调用方仅保留台词文本(配套 Manim 本地动画方案)。
"""
from __future__ import annotations

import base64
import json
import logging
import ssl
import threading
import wave
from pathlib import Path

from ..config import GEN_DIR, get_settings
from .signing import assemble_auth_url

log = logging.getLogger("sparklearn.tts")
TTS_URL = "wss://tts-api.xfyun.cn/v2/tts"


def synthesize(text: str, *, voice: str = "xiaoyan", filename: str | None = None) -> str | None:
    """合成可验证的 WAV 到 static/gen,返回可访问的 /static 相对路径。"""
    s = get_settings()
    if not (s.spark_appid and s.spark_api_key and s.spark_api_secret):
        log.info("TTS 未配置三元组,跳过合成(降级为台词文本)")
        return None
    try:
        import websocket  # websocket-client
    except ImportError:
        log.warning("websocket-client 未安装,TTS 跳过")
        return None

    out = GEN_DIR / (filename or f"tts_{abs(hash(text)) % 10**8}.wav")
    audio = bytearray()
    url = assemble_auth_url(TTS_URL.replace("wss://", "https://"), s.spark_api_key, s.spark_api_secret)
    url = url.replace("https://", "wss://")
    speed = max(0, min(100, int(getattr(s, "spark_tts_speed", 42))))
    payload = {
        "common": {"app_id": s.spark_appid},
        # Request PCM so a code=0 response can still be checked for actual
        # audible samples. The provider can return a structurally valid but
        # completely silent MP3 when the voice entitlement is unavailable.
        "business": {
            "aue": "raw",
            "auf": "audio/L16;rate=16000",
            "vcn": voice,
            "tte": "UTF8",
            "speed": speed,
        },
        "data": {"status": 2, "text": base64.b64encode(text.encode("utf-8")).decode()},
    }
    done: list[bool] = []

    def on_message(ws, message):  # noqa: ANN001
        msg = json.loads(message)
        if msg.get("code") != 0:
            log.error("TTS 错误: %s", msg)
            ws.close()
            return
        data = msg.get("data", {})
        if data.get("audio"):
            audio.extend(base64.b64decode(data["audio"]))
        if data.get("status") == 2:
            done.append(True)
            ws.close()

    def on_open(ws):  # noqa: ANN001
        ws.send(json.dumps(payload))

    ws = websocket.WebSocketApp(url, on_message=on_message, on_open=on_open)
    timeout_s = max(0.1, float(getattr(s, "mm_tts_timeout_s", 15)))
    timed_out: list[bool] = []

    def abort_on_deadline() -> None:
        timed_out.append(True)
        try:
            ws.close()
        except Exception:  # noqa: BLE001
            pass

    watchdog = threading.Timer(timeout_s, abort_on_deadline)
    watchdog.daemon = True
    watchdog.start()
    try:
        ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE})
    finally:
        watchdog.cancel()
    if timed_out:
        raise TimeoutError(f"TTS provider timeout after {timeout_s:g}s")
    if done and audio:
        pcm = bytes(audio)
        peak = max(
            (
                abs(int.from_bytes(pcm[index:index + 2], "little", signed=True))
                for index in range(0, len(pcm) - 1, 2)
            ),
            default=0,
        )
        if peak <= 32:
            raise RuntimeError("standard TTS returned silent PCM audio")
        with wave.open(str(out), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(pcm)
        return f"/static/gen/{out.name}"
    return None

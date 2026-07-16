"""讯飞中英识别大模型 WebSocket 客户端。

接收 8K/16K、16-bit、单声道 PCM 或 MP3，音频最长 60 秒。当前网页录音
统一在浏览器侧转为 16K 单声道 PCM，避免服务端依赖 FFmpeg。
"""
from __future__ import annotations

import base64
import json
import logging
import ssl
import threading
import time
from typing import Any

from ..config import get_settings
from .signing import assemble_auth_url

log = logging.getLogger("sparklearn.asr")
DEFAULT_ASR_URL = "wss://iat.xf-yun.com/v1"


def configured(settings: Any | None = None) -> bool:
    s = settings or get_settings()
    return bool(
        (getattr(s, "spark_asr_appid", "") or getattr(s, "spark_appid", ""))
        and (getattr(s, "spark_asr_api_key", "") or getattr(s, "spark_api_key", ""))
        and (getattr(s, "spark_asr_api_secret", "") or getattr(s, "spark_api_secret", ""))
    )


def _decoded_text(encoded: str) -> tuple[int, str]:
    payload = json.loads(base64.b64decode(encoded).decode("utf-8"))
    ret = int(payload.get("ret") or 0)
    if ret != 0:
        raise RuntimeError(f"recognition ret={ret}")
    words = []
    for segment in payload.get("ws") or []:
        candidates = segment.get("cw") or []
        if candidates:
            words.append(str(candidates[0].get("w") or ""))
    return int(payload.get("sn") or 0), "".join(words)


def transcribe(
    audio: bytes,
    *,
    encoding: str = "raw",
    sample_rate: int = 16000,
    timeout_s: float | None = None,
) -> str:
    """Return recognized text for one audio clip."""
    s = get_settings()
    if not configured(s):
        raise RuntimeError("ASR credentials not configured")
    if encoding not in {"raw", "lame"}:
        raise ValueError("ASR encoding must be raw or lame")
    if sample_rate not in {8000, 16000}:
        raise ValueError("ASR sample rate must be 8000 or 16000")
    if not audio:
        raise ValueError("ASR audio is empty")
    try:
        import websocket  # websocket-client
    except ImportError as error:
        raise RuntimeError("websocket-client is not installed") from error

    request_url = str(getattr(s, "spark_asr_url", "") or DEFAULT_ASR_URL)
    api_key = str(getattr(s, "spark_asr_api_key", "") or getattr(s, "spark_api_key", ""))
    api_secret = str(
        getattr(s, "spark_asr_api_secret", "") or getattr(s, "spark_api_secret", "")
    )
    signed_url = assemble_auth_url(
        request_url.replace("wss://", "https://"),
        api_key,
        api_secret,
    ).replace("https://", "wss://")
    appid = str(getattr(s, "spark_asr_appid", "") or getattr(s, "spark_appid", ""))
    results: dict[int, str] = {}
    completed = threading.Event()
    errors: list[str] = []

    def on_message(ws, message):  # noqa: ANN001
        try:
            response = json.loads(message)
            header = response.get("header") or {}
            code = int(header.get("code") or 0)
            if code != 0:
                errors.append(
                    f"code={code} sid={header.get('sid', '')} message={header.get('message', '')}"[:240]
                )
                completed.set()
                ws.close()
                return
            result = ((response.get("payload") or {}).get("result") or {})
            if result.get("text"):
                sequence, text = _decoded_text(str(result["text"]))
                results[sequence] = text
                log.debug(
                    "asr result seq=%s status=%s chars=%s text=%s",
                    sequence,
                    result.get("status"),
                    len(text),
                    text[:80],
                )
            status = result.get("status")
            if status is None:
                status = header.get("status")
            if int(status or 0) == 2:
                completed.set()
                ws.close()
        except Exception as error:  # noqa: BLE001
            errors.append(f"invalid provider response: {error}"[:240])
            completed.set()
            ws.close()

    def on_error(_ws, error):  # noqa: ANN001
        errors.append(str(error).replace("\r", " ").replace("\n", " ")[:240])
        completed.set()

    def frame(status: int, sequence: int, chunk: bytes, *, first: bool) -> str:
        request: dict[str, Any] = {
            "header": {"app_id": appid, "status": status},
            "payload": {
                "audio": {
                    "encoding": encoding,
                    "sample_rate": sample_rate,
                    "channels": 1,
                    "bit_depth": 16,
                    "seq": sequence,
                    "status": status,
                    "audio": base64.b64encode(chunk).decode("ascii"),
                }
            },
        }
        if first:
            request["parameter"] = {
                "iat": {
                    "domain": "slm",
                    "language": "zh_cn",
                    "accent": "mandarin",
                    "eos": 6000,
                    "ltc": 1,
                    "result": {"encoding": "utf8", "compress": "raw", "format": "json"},
                }
            }
        return json.dumps(request, ensure_ascii=False)

    def send_audio(ws) -> None:  # noqa: ANN001
        try:
            frame_size = 1280
            chunks = [audio[index:index + frame_size] for index in range(0, len(audio), frame_size)]
            for index, chunk in enumerate(chunks, start=1):
                if completed.is_set():
                    return
                status = 0 if index == 1 else 1
                ws.send(frame(status, index, chunk, first=index == 1))
                if index < len(chunks):
                    time.sleep(0.04)
            ws.send(frame(2, len(chunks) + 1, b"", first=False))
        except Exception as error:  # noqa: BLE001
            errors.append(f"audio upload failed: {error}"[:240])
            completed.set()
            try:
                ws.close()
            except Exception:  # noqa: BLE001
                pass

    def on_open(ws):  # noqa: ANN001
        sender = threading.Thread(target=send_audio, args=(ws,), daemon=True)
        sender.start()

    ws = websocket.WebSocketApp(
        signed_url,
        on_message=on_message,
        on_error=on_error,
        on_open=on_open,
    )
    budget = max(0.1, float(timeout_s or getattr(s, "mm_asr_timeout_s", 20)))

    def abort_on_deadline() -> None:
        if not completed.is_set():
            errors.append(f"provider timeout after {budget:g}s")
            completed.set()
            try:
                ws.close()
            except Exception:  # noqa: BLE001
                pass

    watchdog = threading.Timer(budget, abort_on_deadline)
    watchdog.daemon = True
    watchdog.start()
    try:
        ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE})
    finally:
        watchdog.cancel()

    if errors:
        raise RuntimeError("ASR " + "; ".join(errors))
    text = "".join(results[index] for index in sorted(results)).strip()
    if not text:
        raise RuntimeError("ASR returned no text")
    return text

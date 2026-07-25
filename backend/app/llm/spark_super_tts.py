"""讯飞超拟人语音合成 WebSocket 客户端。

超拟人 TTS 使用独立服务授权。优先使用控制台 APIPassword 的 ``x-api-key``
鉴权；未配置时也支持复用 APPID/APIKey/APISecret 的 HMAC 鉴权。
"""
from __future__ import annotations

import base64
import json
import logging
import ssl
import threading
from pathlib import Path
from typing import Any

from ..config import GEN_DIR, get_settings
from .signing import assemble_auth_url

log = logging.getLogger("sparklearn.super_tts")
DEFAULT_SUPER_TTS_URL = "wss://cbm01.cn-huabei-1.xf-yun.com/v1/private/mcd9m97e6"


def configured(settings: Any | None = None) -> bool:
    """Return whether either supported authentication method is available."""
    s = settings or get_settings()
    return bool(
        getattr(s, "spark_super_tts_api_password", "")
        or (
            (getattr(s, "spark_super_tts_appid", "") or getattr(s, "spark_appid", ""))
            and (getattr(s, "spark_super_tts_api_key", "") or getattr(s, "spark_api_key", ""))
            and (
                getattr(s, "spark_super_tts_api_secret", "")
                or getattr(s, "spark_api_secret", "")
            )
        )
    )


def synthesize(
    text: str,
    *,
    voice: str | None = None,
    filename: str | None = None,
) -> str | None:
    """Synthesize text to MP3 and return its ``/static/gen`` URL."""
    s = get_settings()
    if not configured(s):
        log.info("超拟人 TTS 未配置鉴权，跳过")
        return None
    try:
        import websocket  # websocket-client
    except ImportError:
        log.warning("websocket-client 未安装，超拟人 TTS 跳过")
        return None

    appid = str(getattr(s, "spark_super_tts_appid", "") or getattr(s, "spark_appid", ""))
    api_password = str(getattr(s, "spark_super_tts_api_password", "") or "")
    request_url = str(getattr(s, "spark_super_tts_url", "") or DEFAULT_SUPER_TTS_URL)
    headers: dict[str, str] | None = None
    if api_password:
        url = request_url
        headers = {"x-api-key": api_password}
    else:
        url = assemble_auth_url(
            request_url.replace("wss://", "https://"),
            str(
                getattr(s, "spark_super_tts_api_key", "")
                or getattr(s, "spark_api_key", "")
            ),
            str(
                getattr(s, "spark_super_tts_api_secret", "")
                or getattr(s, "spark_api_secret", "")
            ),
        ).replace("https://", "wss://")

    chosen_voice = str(voice or getattr(s, "spark_super_tts_voice", "") or "x6_lingxiaoxuan_pro")
    output = GEN_DIR / (filename or f"super_tts_{abs(hash((chosen_voice, text))) % 10**8}.mp3")
    chunks: dict[int, bytes] = {}
    completed = threading.Event()
    payload_sent = threading.Event()
    errors: list[str] = []

    speed = max(0, min(100, int(getattr(s, "spark_tts_speed", 42))))
    payload = {
        "header": {"app_id": appid, "status": 2},
        "parameter": {
            "tts": {
                "vcn": chosen_voice,
                "speed": speed,
                "volume": 50,
                "pitch": 50,
                "bgs": 0,
                "reg": 0,
                "rdn": 0,
                "rhy": 0,
                "audio": {
                    "encoding": "lame",
                    "sample_rate": 24000,
                    "channels": 1,
                    "bit_depth": 16,
                    "frame_size": 0,
                },
            }
        },
        "payload": {
            "text": {
                "encoding": "utf8",
                "compress": "raw",
                "format": "plain",
                "status": 2,
                "seq": 0,
                # 当前服务端要求 text 与返回 audio 一样使用 Base64 承载；
                # 文档示例的占位字符串未体现这一点，真实接口会返回 10163。
                "text": base64.b64encode(text.encode("utf-8")).decode("ascii"),
            }
        },
    }

    def on_message(ws, message):  # noqa: ANN001
        try:
            response = json.loads(message)
            header = response.get("header") or {}
            code = int(header.get("code") or 0)
            if code != 0:
                sid = str(header.get("sid") or "")
                detail = str(header.get("message") or "provider error")
                errors.append(f"code={code} sid={sid} message={detail}"[:240])
                completed.set()
                ws.close()
                return
            audio = ((response.get("payload") or {}).get("audio") or {})
            encoded = audio.get("audio")
            if encoded:
                chunk = base64.b64decode(encoded)
                raw_sequence = audio.get("seq")
                sequence = int(raw_sequence) if raw_sequence is not None else len(chunks)
                # Some service versions repeat a sequence number. Preserve every
                # frame instead of silently overwriting audio already received.
                while sequence in chunks:
                    sequence += 1
                chunks[sequence] = chunk
                log.debug(
                    "super_tts frame header_status=%s audio_status=%s seq=%s bytes=%s",
                    header.get("status"),
                    audio.get("status"),
                    audio.get("seq"),
                    len(chunk),
                )
            status = audio.get("status")
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

    def on_open(ws):  # noqa: ANN001
        # The provider's official websocket-client demo sends the first payload
        # from a worker thread. Sending synchronously inside ``on_open`` can
        # make websocket-client re-enter its receive loop too early: the
        # service then closes with a single 288-byte MP3 frame (silence), which
        # used to be misreported as a normal provider outage.
        def send_payload() -> None:
            try:
                ws.send(json.dumps(payload, ensure_ascii=False))
            except Exception as error:  # noqa: BLE001
                errors.append(f"send failed: {error}"[:240])
                completed.set()
                try:
                    ws.close()
                except Exception:  # noqa: BLE001
                    pass
            finally:
                payload_sent.set()

        sender = threading.Thread(target=send_payload, daemon=True)
        sender.start()
        # The send still happens off the websocket callback thread. A tiny
        # bounded wait makes the hand-off deterministic for fast providers and
        # avoids racing a final frame against an unscheduled sender.
        payload_sent.wait(0.25)

    ws = websocket.WebSocketApp(
        url,
        header=headers,
        on_message=on_message,
        on_error=on_error,
        on_open=on_open,
    )
    timeout_s = max(0.1, float(getattr(s, "mm_tts_timeout_s", 15)))

    def abort_on_deadline() -> None:
        if not completed.is_set():
            errors.append(f"provider timeout after {timeout_s:g}s")
            completed.set()
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

    if errors:
        raise RuntimeError("super TTS " + "; ".join(errors))
    if chunks:
        output.write_bytes(b"".join(chunks[index] for index in sorted(chunks)))
        if output.stat().st_size >= 1024:
            return f"/static/gen/{output.name}"
        output.unlink(missing_ok=True)
        raise RuntimeError(
            "super TTS returned a silent/short audio frame; "
            f"check service quota and voice authorization for {chosen_voice}"
        )
    raise RuntimeError("super TTS returned no audio")

"""讯飞星火图片生成(文生图,HTTP+HMAC)。失败/未配置时返回 None,由上层降级为 SVG 占位图。"""
from __future__ import annotations

import base64
import json
import logging
from typing import Any

import requests

from ..config import GEN_DIR, get_settings
from .signing import assemble_auth_url

log = logging.getLogger("sparklearn.image")
TTI_URL = "https://spark-api.cn-huabei-1.xf-yun.com/v2.1/tti"


def _credentials(settings: Any | None = None) -> tuple[str, str, str]:
    """Prefer the dedicated TTI application without breaking older deployments."""
    s = settings or get_settings()
    return (
        str(getattr(s, "spark_tti_appid", "") or getattr(s, "spark_appid", "")),
        str(getattr(s, "spark_tti_api_key", "") or getattr(s, "spark_api_key", "")),
        str(
            getattr(s, "spark_tti_api_secret", "")
            or getattr(s, "spark_api_secret", "")
        ),
    )


def configured(settings: Any | None = None) -> bool:
    return all(_credentials(settings))


def _response_error(response: requests.Response, data: object) -> RuntimeError:
    payload = data if isinstance(data, dict) else {}
    header = payload.get("header") if isinstance(payload.get("header"), dict) else {}
    code = header.get("code", "-")
    sid = header.get("sid") or "-"
    message = header.get("message") or header.get("msg") or payload.get("message") or "unknown error"
    message = str(message).replace("\r", " ").replace("\n", " ")[:200]
    return RuntimeError(
        f"spark image generation http={response.status_code} "
        f"code={code} sid={sid} message={message}"
    )


def generate_image(prompt: str, *, width: int = 768, height: int = 768) -> str | None:
    s = get_settings()
    appid, api_key, api_secret = _credentials(s)
    if not (appid and api_key and api_secret):
        return None
    url = assemble_auth_url(TTI_URL, api_key, api_secret, method="POST")
    body = {
        "header": {"app_id": appid},
        "parameter": {"chat": {"domain": "general", "width": width, "height": height}},
        "payload": {"message": {"text": [{"role": "user", "content": prompt}]}},
    }
    try:
        r = requests.post(url, json=body, timeout=max(1.0, float(getattr(s, "mm_image_timeout_s", 30))))
        try:
            data = r.json()
        except ValueError as exc:
            raise RuntimeError(
                f"spark image generation http={r.status_code} invalid JSON"
            ) from exc

        header = data.get("header") if isinstance(data, dict) else None
        code = header.get("code", 0) if isinstance(header, dict) else 0
        if (
            not isinstance(data, dict)
            or r.status_code != 200
            or code not in (0, "0", None)
            or not data.get("payload")
        ):
            raise _response_error(r, data)

        choices = (data.get("payload") or {}).get("choices") or {}
        items = choices.get("text") or []
        text = items[0].get("content") if items and isinstance(items[0], dict) else None
        if not text:
            raise _response_error(r, data)
        img = base64.b64decode(text)
        out = GEN_DIR / f"img_{abs(hash(prompt)) % 10**8}.jpg"
        out.write_bytes(img)
        return f"/static/gen/{out.name}"
    except Exception as e:  # noqa: BLE001
        log.warning("文生图失败:%s", e)
        raise

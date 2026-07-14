"""OpenAI GPT Image provider used behind the multimodal gateway."""
from __future__ import annotations

import base64
import hashlib
from pathlib import Path
from typing import Any

import requests

from ..config import GEN_DIR, get_settings


def available() -> bool:
    settings = get_settings()
    return bool(settings.openai_api_key and settings.openai_image_model)


def _size_for(width: int, height: int) -> str:
    if width > height:
        return "1536x1024"
    if height > width:
        return "1024x1536"
    return "1024x1024"


def _image_bytes(item: dict[str, Any], timeout_s: float) -> bytes:
    encoded = item.get("b64_json")
    if encoded:
        try:
            return base64.b64decode(str(encoded))
        except Exception as error:  # noqa: BLE001
            raise RuntimeError("OpenAI image returned invalid base64") from error

    url = str(item.get("url") or "")
    if not url:
        raise RuntimeError("OpenAI image returned no image payload")
    response = requests.get(url, timeout=max(1.0, timeout_s))
    response.raise_for_status()
    return response.content


def _validate_image(data: bytes) -> None:
    is_png = data.startswith(b"\x89PNG\r\n\x1a\n")
    is_jpeg = data.startswith(b"\xff\xd8\xff")
    is_webp = len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    if not (is_png or is_jpeg or is_webp):
        raise RuntimeError("OpenAI image returned an unsupported image format")


def _api_error(response: requests.Response, payload: dict[str, Any]) -> RuntimeError:
    error = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(error, dict):
        error = {}
    message = str(error.get("message") or response.reason or "request failed")[:240]
    code = str(error.get("code") or "")[:80]
    kind = str(error.get("type") or "")[:80]
    return RuntimeError(
        f"OpenAI image request failed status={response.status_code} type={kind} code={code}: {message}"
    )


def generate_image(
    prompt: str,
    *,
    width: int = 1024,
    height: int = 1024,
    filename: str | None = None,
    timeout_s: float = 60,
) -> str:
    settings = get_settings()
    if not available():
        raise RuntimeError("OPENAI_API_KEY/OPENAI_IMAGE_MODEL is not configured")

    response = requests.post(
        f"{settings.openai_base_url.rstrip('/')}/images/generations",
        headers={
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": settings.openai_image_model,
            "prompt": prompt,
            "size": _size_for(width, height),
            "quality": settings.openai_image_quality,
        },
        timeout=max(1.0, timeout_s),
    )
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if response.status_code >= 400:
        raise _api_error(response, payload)

    items = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(items, list) or not items or not isinstance(items[0], dict):
        raise RuntimeError("OpenAI image returned an invalid response")
    data = _image_bytes(items[0], timeout_s)
    _validate_image(data)

    if not filename:
        digest = hashlib.sha1(prompt.encode("utf-8")).hexdigest()[:16]
        filename = f"openai_img_{digest}.png"
    path = GEN_DIR / Path(filename).name
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_bytes(data)
    temp.replace(path)
    return f"/static/gen/{path.name}"

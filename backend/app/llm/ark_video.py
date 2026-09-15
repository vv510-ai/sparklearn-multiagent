"""Official Ark video task contract; no generation retries or cookie scraping.

Reference: volcengine-python-sdk/resources/content_generation/tasks.py and
https://www.volcengine.com/docs/82379/1520757 (checked 2026-09-15).
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

import requests

from ..config import get_settings


def selected(settings=None) -> bool:
    s = settings or get_settings()
    provider = getattr(s, "video_provider", "auto").strip().lower()
    if provider not in {"auto", "ark", "xiaoyunque"}:
        raise ValueError("Unsupported VIDEO_PROVIDER")
    return provider == "ark" or provider == "auto" and bool(getattr(s, "ark_api_key", ""))


def available(settings=None) -> bool:
    return bool(getattr(settings or get_settings(), "ark_api_key", ""))


def is_task_id(task_id: str) -> bool:
    return str(task_id).startswith("ark_")


def _raw_id(task_id: str) -> str:
    if not re.fullmatch(r"ark_[A-Za-z0-9_-]{1,180}", str(task_id)):
        raise ValueError("Invalid Ark task id")
    return task_id[4:]


def _request(method: str, path: str, *, body=None) -> dict:
    s = get_settings()
    if not s.ark_api_key:
        raise RuntimeError("ARK_API_KEY is not configured")
    base = s.ark_base_url.rstrip("/")
    url = urlsplit(base)
    if url.scheme != "https" or url.username or url.password or url.query or url.fragment:
        raise ValueError("ARK_BASE_URL must be an HTTPS endpoint without credentials or query")
    if not url.path:
        base += "/api/v3"
    timeout = s.mm_video_create_timeout_s if method == "POST" else s.mm_video_poll_timeout_s
    response = requests.request(method, base + "/contents/generations/tasks" + path,
        headers={"Authorization": "Bearer " + s.ark_api_key}, json=body, timeout=timeout)
    if not response.ok:
        # Provider bodies can contain prompts or tokens; retain only status.
        try:
            code = response.json().get("error", {}).get("code")
        except (ValueError, AttributeError):
            code = None
        detail = "：模型尚未开通" if code == "ModelNotOpen" else ""
        raise RuntimeError(f"Ark video HTTP {response.status_code}" + detail)
    data = response.json()
    if not isinstance(data, dict):
        raise RuntimeError("Ark video returned an invalid envelope")
    return data


def create_task(prompt: str, image_url: str | None = None) -> str:
    s = get_settings()
    if not prompt.strip() or len(prompt) > 12000:
        raise ValueError("Video prompt must contain 1 to 12000 characters")
    if image_url:
        raise ValueError("This course video adapter accepts text only")
    if not 4 <= s.ark_video_duration <= 15:
        raise ValueError("ARK_VIDEO_DURATION must be between 4 and 15 seconds")
    if s.ark_video_resolution not in {"480p", "720p", "1080p"}:
        raise ValueError("Unsupported ARK_VIDEO_RESOLUTION")
    data = _request("POST", "", body={"model": s.ark_video_model,
        "content": [{"type": "text", "text": prompt}], "ratio": "16:9",
        "duration": s.ark_video_duration, "resolution": s.ark_video_resolution,
        "generate_audio": False, "watermark": True})
    task_id = "ark_" + str(data.get("id") or "")
    _raw_id(task_id)
    return task_id


def poll_task(task_id: str) -> dict:
    data = _request("GET", "/" + _raw_id(task_id))
    status = str(data.get("status", ""))
    result = {"task_id": task_id, "provider": "ark", "model": data.get("model") or get_settings().ark_video_model}
    if status == "succeeded":
        url = str((data.get("content") or {}).get("video_url") or "")
        if not url.startswith("https://"):
            raise RuntimeError("Ark task succeeded without an HTTPS video URL")
        return {**result, "status": status, "url": url}
    if status in {"failed", "cancelled", "expired"}:
        return {**result, "status": "failed", "error": "视频任务未完成，请在服务商控制台核验"}
    if status not in {"queued", "running"}:
        raise RuntimeError("Ark returned an unknown task state")
    return {**result, "status": "running"}

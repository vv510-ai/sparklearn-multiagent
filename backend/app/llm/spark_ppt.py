"""讯飞星火智能 PPT（新版）HTTP 客户端。

只负责供应商协议：创建任务、查询进度与下载最终 pptx。业务侧的
“仅在用户明确要求时生成”策略由编排器和学习工坊入口控制。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import time
from pathlib import Path
from typing import Any

import requests

from ..config import get_settings

DEFAULT_BASE_URL = "https://zwapi.xfyun.cn"
_MAX_PPT_BYTES = 50 * 1024 * 1024


def _credentials(settings: Any | None = None) -> tuple[str, str]:
    s = settings or get_settings()
    appid = str(getattr(s, "spark_ppt_appid", "") or getattr(s, "spark_appid", ""))
    secret = str(
        getattr(s, "spark_ppt_api_secret", "") or getattr(s, "spark_api_secret", "")
    )
    return appid, secret


def configured(settings: Any | None = None) -> bool:
    return all(_credentials(settings))


def signature(appid: str, secret: str, timestamp: int | str) -> str:
    """MD5(appId + timestamp) 后使用 secret 做 HMAC-SHA1，再 Base64。"""
    stamp = str(timestamp)
    auth = hashlib.md5(f"{appid}{stamp}".encode("utf-8")).hexdigest()  # noqa: S324
    digest = hmac.new(secret.encode("utf-8"), auth.encode("utf-8"), hashlib.sha1).digest()
    return base64.b64encode(digest).decode("ascii")


def _headers() -> dict[str, str]:
    appid, secret = _credentials()
    if not appid or not secret:
        raise RuntimeError("PPT credentials not configured")
    timestamp = int(time.time())
    return {
        "appId": appid,
        "timestamp": str(timestamp),
        "signature": signature(appid, secret, timestamp),
    }


def _json(response: requests.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError as error:
        raise RuntimeError(f"PPT provider returned invalid JSON (HTTP {response.status_code})") from error
    if not response.ok:
        raise RuntimeError(
            f"PPT provider HTTP {response.status_code}: {str(data.get('desc') or data)[:180]}"
        )
    code = int(data.get("code") or 0)
    if code != 0 or data.get("flag") is False:
        raise RuntimeError(f"PPT provider code={code}: {str(data.get('desc') or 'unknown error')[:180]}")
    return data


def create_task(query: str, *, timeout_s: float = 30.0) -> dict[str, Any]:
    s = get_settings()
    value = str(query or "").strip()
    if not value:
        raise ValueError("PPT query is empty")
    value = value[:12000]
    base_url = str(getattr(s, "spark_ppt_base_url", "") or DEFAULT_BASE_URL).rstrip("/")
    fields = {
        "query": (None, value),
        "language": (None, "cn"),
        "author": (None, "SparkLearn 星火学伴"),
        "search": (None, "false"),
        "isCardNote": (None, "false"),
        "isFigure": (None, "true"),
        "aiImage": (None, "normal"),
    }
    response = requests.post(
        f"{base_url}/api/ppt/v2/create",
        headers=_headers(),
        files=fields,
        timeout=max(1.0, float(timeout_s)),
    )
    data = _json(response).get("data") or {}
    task_id = str(data.get("sid") or "").strip()
    if not task_id:
        raise RuntimeError("PPT provider returned no task id")
    return {
        "task_id": task_id,
        "status": "building",
        "title": str(data.get("title") or ""),
        "subtitle": str(data.get("subTitle") or data.get("subtitle") or ""),
        "cover_url": str(data.get("coverImgSrc") or data.get("coverImage") or ""),
        "provider": "iflytek_ppt_v2",
    }


def poll_task(task_id: str, *, timeout_s: float = 15.0) -> dict[str, Any]:
    s = get_settings()
    sid = str(task_id or "").strip()
    if not sid or not re.fullmatch(r"[A-Za-z0-9@._:-]{6,200}", sid):
        raise ValueError("invalid PPT task id")
    base_url = str(getattr(s, "spark_ppt_base_url", "") or DEFAULT_BASE_URL).rstrip("/")
    response = requests.get(
        f"{base_url}/api/ppt/v2/progress",
        headers=_headers(),
        params={"sid": sid},
        timeout=max(1.0, float(timeout_s)),
    )
    data = _json(response).get("data") or {}
    ppt_status = str(data.get("pptStatus") or "building").lower()
    image_status = str(data.get("aiImageStatus") or "").lower()
    if ppt_status in {"build_failed", "failed"}:
        status = "failed"
    elif ppt_status == "done" and image_status in {"", "done"}:
        status = "ready"
    else:
        status = "building"
    return {
        "task_id": sid,
        "status": status,
        "provider_status": ppt_status,
        "image_status": image_status,
        "url": str(data.get("pptUrl") or ""),
        "total_pages": int(data.get("totalPages") or 0),
        "done_pages": int(data.get("donePages") or 0),
        "error": str(data.get("errMsg") or ""),
        "provider": "iflytek_ppt_v2",
    }


def download_ppt(url: str, target: Path, *, timeout_s: float = 45.0) -> Path:
    source = str(url or "").strip()
    if not source.startswith("https://"):
        raise ValueError("PPT download URL must use HTTPS")
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + ".part")
    total = 0
    with requests.get(source, stream=True, timeout=max(1.0, float(timeout_s))) as response:
        response.raise_for_status()
        with partial.open("wb") as handle:
            for chunk in response.iter_content(64 * 1024):
                if not chunk:
                    continue
                total += len(chunk)
                if total > _MAX_PPT_BYTES:
                    raise RuntimeError("PPT file exceeds 50 MB limit")
                handle.write(chunk)
    if total < 1024 or partial.read_bytes()[:2] != b"PK":
        partial.unlink(missing_ok=True)
        raise RuntimeError("PPT provider returned an invalid pptx file")
    partial.replace(target)
    return target

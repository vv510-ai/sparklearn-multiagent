"""Suno music generation through the suno-api.io service (memory songs).

Billing safety: every generation request carries an ``Idempotency-Key`` and uses
``accept_mode=async`` so a timeout or a resumed job never places a second paid
order. Alternate base URLs are tried only when the first host could not be
reached at all (no HTTP response), never after a host has answered.
"""
from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass

import httpx

from ..config import get_settings, is_demo
from ..services.generation_jobs import SubmissionUncertain, durable_call

DEFAULT_BASES = ("https://www.suno-api.io", "https://suno.code-go.com")
MODELS = {"suno-v6", "suno-v6-wild", "suno-v6-mini"}
MAX_AUDIO_BYTES = 40 * 1024 * 1024
MAX_COVER_BYTES = 8 * 1024 * 1024


class SunoError(RuntimeError):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(detail or code)
        self.code = code
        self.detail = detail or code


@dataclass(frozen=True)
class SunoConfig:
    key: str
    bases: tuple[str, ...]
    model: str


def config() -> SunoConfig:
    get_settings()  # loads backend/.env into the environment
    key = os.environ.get("SUNO_API_KEY", "").strip()
    raw = os.environ.get("SUNO_BASE_URLS", "") or ",".join(DEFAULT_BASES)
    bases = tuple(dict.fromkeys(
        value.strip().rstrip("/") for value in raw.split(",")
        if re.fullmatch(r"https://[A-Za-z0-9.-]+(?::\d+)?", value.strip().rstrip("/"))))
    model = os.environ.get("SUNO_MODEL", "suno-v6").strip()
    return SunoConfig(key=key, bases=bases or DEFAULT_BASES, model=model if model in MODELS else "suno-v6")


def available() -> bool:
    return bool(config().key) and not is_demo()


async def _request(method: str, path: str, *, json_body: dict | None = None, headers: dict | None = None,
                   timeout: float = 60) -> object:
    cfg = config()
    if not cfg.key:
        raise SunoError("not_configured", "未配置 SUNO_API_KEY，记忆歌曲只能生成口诀与歌词。")
    last_error: Exception | None = None
    for base in cfg.bases:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=12), follow_redirects=False) as client:
                response = await client.request(method, base + path, json=json_body, headers={
                    "Authorization": "Bearer " + cfg.key, "Content-Type": "application/json", **(headers or {})})
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            # No request body reached the service. A read/write failure can happen
            # after billing; it must never submit again through another host.
            last_error = exc
            continue
        except httpx.TransportError as exc:
            if method == "POST" and path.startswith("/api/music/create"):
                raise SubmissionUncertain("音乐提交回执未收到，已暂停，避免重复生成和扣费。请先核对音乐服务的任务记录。") from exc
            raise SunoError("unreachable", "音乐查询暂时中断，将继续查询原任务。") from exc
        try:
            body = response.json()
        except ValueError:
            body = {}
        if response.status_code >= 400:
            message = ""
            if isinstance(body, dict):
                error = body.get("error")
                message = (error.get("message") if isinstance(error, dict) else "") or str(body.get("message") or "")
            code = {401: "unauthorized", 402: "insufficient_balance", 403: "forbidden", 429: "rate_limited"}.get(
                response.status_code, "provider_error")
            raise SunoError(code, f"音乐服务返回 HTTP {response.status_code}{('：' + message[:160]) if message else ''}")
        return body
    raise SunoError("unreachable", "音乐服务暂时无法连接，请稍后重试。") from last_error


@durable_call("suno_create_custom")
async def create_custom(*, lyrics: str, style_tags: str, title: str, vocal_gender: str = "",
                        negative_tags: str = "", idempotency_key: str) -> str:
    """Submit one custom-mode song (usually two versions). Returns the request id."""
    body = {"model": config().model, "lyrics": lyrics[:3000], "style_tags": style_tags[:1000],
            "song_title": title[:100], "accept_mode": "async"}
    if vocal_gender in {"m", "f", "male", "female"}:
        body["vocal_gender"] = vocal_gender
    if negative_tags.strip():
        body["negative_tags"] = negative_tags[:1000]
    result = await _request("POST", "/api/music/create/custom", json_body=body,
                            headers={"Idempotency-Key": idempotency_key[:128]}, timeout=300)
    data = result.get("data") if isinstance(result, dict) else None
    request_id = str((data or {}).get("request_id") or "")
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{6,128}", request_id):
        raise SunoError("invalid_response", "音乐服务没有返回受理编号。")
    return request_id


async def request_status(request_id: str) -> dict:
    result = await _request("GET", f"/api/music/requests/{request_id}", timeout=30)
    data = result.get("data") if isinstance(result, dict) else None
    if not isinstance(data, dict):
        raise SunoError("invalid_response", "音乐服务进度格式不正确。")
    return data


async def query(song_ids: list[str]) -> list[dict]:
    result = await _request("POST", "/api/music/query", json_body={"model": config().model,
                            "song_ids": ",".join(song_ids)}, timeout=30)
    items = result.get("data") if isinstance(result, dict) else result
    return [item for item in (items or []) if isinstance(item, dict)]


async def timeline(song_id: str) -> list[dict]:
    try:
        result = await _request("POST", "/api/lyrics/timeline", json_body={"model": config().model, "song_id": song_id},
                                timeout=30)
    except SunoError:
        return []
    return [item for item in (result if isinstance(result, list) else []) if isinstance(item, dict)]


async def download(url: str, *, limit: int) -> bytes:
    if not re.match(r"https://", url or ""):
        raise SunoError("invalid_response", "媒体地址无效。")
    async with httpx.AsyncClient(timeout=httpx.Timeout(120, connect=15), follow_redirects=True) as client:
        async with client.stream("GET", url) as response:
            if response.status_code != 200:
                raise SunoError("download_failed", f"媒体下载失败（HTTP {response.status_code}）。")
            parts, size = [], 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > limit:
                    raise SunoError("download_failed", "媒体文件过大。")
                parts.append(chunk)
    return b"".join(parts)


async def wait_for_songs(request_id: str, *, budget_s: float = 420, interval_s: float = 5,
                         on_progress=None) -> list[dict]:
    """Poll the receipt until both versions finish (or one finished near the deadline)."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + budget_s
    song_ids: list[str] = []
    while loop.time() < deadline:
        status = await request_status(request_id)
        state = str(status.get("status") or "")
        tasks = [task for task in status.get("tasks") or [] if isinstance(task, dict)]
        song_ids = [str(task["song_id"]) for task in tasks if task.get("song_id")]
        if on_progress:
            await on_progress(state, tasks)
        if state == "failed":
            raise SunoError("generation_failed", str(status.get("error_message") or "音乐生成失败，费用已由平台退回。"))
        if state == "completed" and song_ids:
            break
        if state == "partial" and song_ids and loop.time() > deadline - 60:
            break
        await asyncio.sleep(interval_s)
    if not song_ids:
        raise SunoError("timeout", "等待音乐生成超时；歌曲可能仍在生成，可稍后重试同一请求。")
    songs = await query(song_ids)
    ready = [song for song in songs if song.get("audio_url") and str(song.get("status") or "") in {"completed", "complete", "playable", "streaming", ""}]
    if not ready:
        raise SunoError("timeout", "歌曲还没有可播放的音频，请稍后重试。")
    return ready

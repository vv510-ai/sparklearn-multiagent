"""火山方舟 Seedance 视频生成封装(OpenAI SDK 风格的 HTTP 异步任务)。

流程:创建任务 → 轮询/回调获取结果(公开输出最高 1080p / 15s)。
比赛降级策略:无 ARK_API_KEY 时不阻塞流水线 —— Media Agent 自动转
「Manim 本地动画代码 + 讯飞 TTS 旁白」方案,本模块仅返回 degraded 状态。
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import requests

from ..config import get_settings

log = logging.getLogger("sparklearn.seedance")


def available() -> bool:
    s = get_settings()
    return bool(s.ark_api_key and s.seedance_model)


def create_task(prompt: str, image_url: str | None = None) -> str:
    """创建异步视频生成任务,返回 task_id。"""
    s = get_settings()
    duration = int(getattr(s, "seedance_duration", 5))
    if duration <= 0:
        raise ValueError("SEEDANCE_DURATION must be greater than zero")
    headers = {"Authorization": f"Bearer {s.ark_api_key}", "Content-Type": "application/json"}
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    if image_url:
        content.append({
            "type": "image_url",
            "image_url": {"url": image_url},
            "role": "reference_image",
        })
    payload = {
        "model": s.seedance_model,
        "content": content,
        "generate_audio": bool(getattr(s, "seedance_generate_audio", True)),
        "ratio": str(getattr(s, "seedance_ratio", "16:9")),
        "duration": duration,
        "watermark": bool(getattr(s, "seedance_watermark", False)),
    }
    r = requests.post(
        f"{s.ark_base_url}/contents/generations/tasks",
        headers=headers,
        json=payload,
        timeout=max(1.0, float(getattr(s, "mm_video_create_timeout_s", 15))),
    )
    try:
        r.raise_for_status()
    except requests.HTTPError as exc:
        try:
            detail = r.json()
        except ValueError:
            detail = {}
        error = detail.get("error") if isinstance(detail, dict) else {}
        error = error if isinstance(error, dict) else {}
        code = error.get("code") or detail.get("code") or "unknown"
        message = error.get("message") or detail.get("message") or r.reason
        request_id = detail.get("request_id") or r.headers.get("x-request-id", "")
        raise RuntimeError(
            f"Seedance create failed: status={r.status_code} code={code} "
            f"message={message} request_id={request_id}"
        ) from exc
    data = r.json()
    task_id = data.get("id") if isinstance(data, dict) else None
    if not task_id:
        raise RuntimeError("Seedance create failed: response missing task id")
    return str(task_id)


def poll_task(task_id: str) -> dict:
    if not available():
        return {"status": "degraded", "task_id": task_id,
                "reason": "ARK_API_KEY/SEEDANCE_MODEL is not configured"}
    """查询一次任务状态:{status, video_url?}。"""
    s = get_settings()
    headers = {"Authorization": f"Bearer {s.ark_api_key}"}
    r = requests.get(f"{s.ark_base_url}/contents/generations/tasks/{task_id}",
                     headers=headers,
                     timeout=max(1.0, float(getattr(s, "mm_video_poll_timeout_s", 15))))
    r.raise_for_status()
    data = r.json()
    out = {"status": data.get("status", "running"), "task_id": task_id}
    if out["status"] == "succeeded":
        out["url"] = (data.get("content") or {}).get("video_url")
    if out["status"] == "failed":
        out["error"] = str(data)
    return out


def gen_video_blocking(prompt: str, image_url: str | None = None,
                       timeout_s: int = 600, interval_s: int = 3) -> str:
    """同步封装:创建并轮询直至成功,返回 video_url(脚本/测试用)。"""
    task_id = create_task(prompt, image_url)
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        st = poll_task(task_id)
        if st["status"] == "succeeded":
            return st["url"]
        if st["status"] == "failed":
            raise RuntimeError(st.get("error", "seedance failed"))
        time.sleep(interval_s)
    raise TimeoutError("Seedance 任务超时")


async def gen_video_async(prompt: str, image_url: str | None = None,
                          on_progress=None, timeout_s: int = 600) -> dict:
    """异步封装:供 Media Agent 调用,期间通过 on_progress 上报进度事件。"""
    if not available():
        return {"status": "degraded", "reason": "未配置 ARK_API_KEY/SEEDANCE_MODEL,转 Manim+TTS 本地方案"}
    try:
        task_id = await asyncio.to_thread(create_task, prompt, image_url)
        t0 = time.time()
        tick = 0
        while time.time() - t0 < timeout_s:
            st = await asyncio.to_thread(poll_task, task_id)
            tick += 1
            if on_progress:
                await on_progress({"percent": min(95, tick * 7),
                                   "status": st["status"],
                                   "detail": f"Seedance task {st['status']}",
                                   "task_id": task_id})
            if st["status"] == "succeeded":
                return {"status": "succeeded", "url": st.get("url"), "task_id": task_id}
            if st["status"] == "failed":
                return {"status": "failed", "error": st.get("error"), "task_id": task_id}
            await asyncio.sleep(3)
        return {"status": "timeout", "task_id": task_id}
    except Exception as e:  # noqa: BLE001
        log.warning("Seedance 调用异常,触发降级:%s", e)
        return {"status": "degraded", "reason": str(e)}

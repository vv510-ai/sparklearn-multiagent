"""小云雀图片 / 视频生成客户端（Bearer Access Key + 异步 Run 轮询）。

通用 Nest Agent 与视频 Agent 共用 POST submit_run / get_thread 调用链。
Run state=3 时，从对应图片或视频产物中读取临时下载地址；上层网关负责
校验并转存为 SparkLearn 自有静态资源。
"""
from __future__ import annotations

import base64
import json
import logging
import mimetypes
from pathlib import Path
from typing import Any

import requests

from ..config import get_settings

log = logging.getLogger("sparklearn.xiaoyunque")

_SUBMIT_RUN_PATH = "/api/biz/v1/skill/submit_run"
_GET_THREAD_PATH = "/api/biz/v1/skill/get_thread"
_UPLOAD_FILE_PATH = "/api/biz/v1/skill/upload_file"
_VIDEO_AGENT = "pippit_video_part_agent"
_TASK_PREFIX = "xyq_"


def available() -> bool:
    return bool(str(getattr(get_settings(), "xyq_access_key", "")).strip())


def _base_url() -> str:
    return str(
        getattr(get_settings(), "xyq_base_url", "https://xyq.jianying.com")
    ).rstrip("/")


def _headers(*, json_body: bool = True) -> dict[str, str]:
    key = str(getattr(get_settings(), "xyq_access_key", "")).strip()
    if not key:
        raise RuntimeError("XYQ_ACCESS_KEY is not configured")
    headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers


def _timeout(name: str, default: float) -> float:
    return max(1.0, float(getattr(get_settings(), name, default)))


def _response_json(response: requests.Response, action: str) -> dict[str, Any]:
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        request_id = response.headers.get("x-request-id", "")
        body = response.text.strip().replace("\r", " ").replace("\n", " ")[:400]
        raise RuntimeError(
            f"Xiaoyunque {action} failed: status={response.status_code} "
            f"request_id={request_id} body={body or response.reason}"
        ) from exc
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError(f"Xiaoyunque {action} failed: invalid JSON response") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"Xiaoyunque {action} failed: invalid response envelope")
    if str(payload.get("ret", "")) != "0":
        raise RuntimeError(
            f"Xiaoyunque {action} failed: ret={payload.get('ret', '')} "
            f"errmsg={payload.get('errmsg') or 'unknown'} log_id={payload.get('log_id', '')}"
        )
    data = payload.get("data")
    if not isinstance(data, dict):
        raise RuntimeError(f"Xiaoyunque {action} failed: response missing data")
    return data


def _encode_task_id(thread_id: str, run_id: str) -> str:
    raw = json.dumps(
        {"thread_id": thread_id, "run_id": run_id},
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    token = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    return _TASK_PREFIX + token


def _decode_task_id(task_id: str) -> tuple[str, str]:
    if not str(task_id).startswith(_TASK_PREFIX):
        raise ValueError("not a Xiaoyunque task id")
    token = str(task_id)[len(_TASK_PREFIX):]
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid Xiaoyunque task id") from exc
    thread_id = str(payload.get("thread_id") or "").strip()
    run_id = str(payload.get("run_id") or "").strip()
    if not thread_id or not run_id:
        raise ValueError("invalid Xiaoyunque task id")
    return thread_id, run_id


def is_task_id(task_id: str) -> bool:
    return str(task_id).startswith(_TASK_PREFIX)


def create_task(prompt: str, image_url: str | None = None) -> str:
    """提交文生视频任务，返回可安全用于 URL path 的不透明 task_id。"""
    text = " ".join(str(prompt or "").split())
    if not text:
        raise ValueError("video prompt must not be empty")
    if image_url:
        raise ValueError("Xiaoyunque reference images must be uploaded as asset ids")

    settings = get_settings()
    duration = max(10, int(getattr(settings, "xyq_video_duration", 10)))
    if duration <= 0:
        raise ValueError("XYQ_VIDEO_DURATION must be greater than zero")
    param: dict[str, Any] = {"prompt": text, "duration_sec": duration}
    for field, setting_name in (
        ("ratio", "xyq_video_ratio"),
        ("model", "xyq_video_model"),
        ("resolution", "xyq_video_resolution"),
    ):
        value = str(getattr(settings, setting_name, "") or "").strip()
        if value:
            param[field] = value

    response = requests.post(
        _base_url() + _SUBMIT_RUN_PATH,
        headers=_headers(),
        json={
            "agent_name": _VIDEO_AGENT,
            "message": text,
            "video_part_tool_param": param,
        },
        timeout=_timeout("mm_video_create_timeout_s", 15),
    )
    data = _response_json(response, "create")
    run = data.get("run")
    run = run if isinstance(run, dict) else {}
    thread_id = str(run.get("thread_id") or "").strip()
    run_id = str(run.get("run_id") or "").strip()
    if not thread_id or not run_id:
        raise RuntimeError("Xiaoyunque create failed: response missing thread_id/run_id")
    return _encode_task_id(thread_id, run_id)


def create_image_task(prompt: str) -> str:
    """向通用 Nest Agent 提交文生图请求。"""
    text = str(prompt or "").strip()
    if not text:
        raise ValueError("image prompt must not be empty")
    response = requests.post(
        _base_url() + _SUBMIT_RUN_PATH,
        headers=_headers(),
        json={"message": text},
        timeout=_timeout("mm_image_timeout_s", 30),
    )
    data = _response_json(response, "create image")
    run = data.get("run")
    run = run if isinstance(run, dict) else {}
    thread_id = str(run.get("thread_id") or "").strip()
    run_id = str(run.get("run_id") or "").strip()
    if not thread_id or not run_id:
        raise RuntimeError("Xiaoyunque create image failed: response missing thread_id/run_id")
    return _encode_task_id(thread_id, run_id)


def upload_file(path: str | Path) -> str:
    """上传本地参考素材并返回 asset_id，供后续扩展图生视频使用。"""
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(source)
    content_type = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
    with source.open("rb") as file_obj:
        response = requests.post(
            _base_url() + _UPLOAD_FILE_PATH,
            headers=_headers(json_body=False),
            files={"file": (source.name, file_obj, content_type)},
            timeout=_timeout("mm_video_create_timeout_s", 15),
        )
    data = _response_json(response, "upload")
    asset_id = str(data.get("asset_id") or data.get("pippit_asset_id") or "").strip()
    if not asset_id:
        raise RuntimeError("Xiaoyunque upload failed: response missing asset_id")
    return asset_id


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _video_urls(run: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for entry in run.get("entry_list") or []:
        if not isinstance(entry, dict):
            continue
        artifact = entry.get("artifact")
        artifact = artifact if isinstance(artifact, dict) else {}
        for content in artifact.get("content") or []:
            if (
                not isinstance(content, dict)
                or content.get("sub_type") != "biz/x_data_video"
            ):
                continue
            data = _json_object(content.get("data"))
            video = data.get("video")
            video = video if isinstance(video, dict) else {}
            url = str(video.get("download_url") or video.get("url") or "").strip()
            if url and url not in urls:
                urls.append(url)
    return urls


def _iter_result_urls(value: Any, path: str = ""):
    if isinstance(value, dict):
        for key, item in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            key_lower = str(key).lower()
            is_url_key = (
                key_lower in {"download_url", "url"}
                or key_lower.endswith("_url")
                or key_lower.endswith("_urls")
            )
            if is_url_key and isinstance(item, str) and item.startswith(("http://", "https://")):
                yield child_path, item
            elif is_url_key and isinstance(item, list):
                for index, url in enumerate(item):
                    if isinstance(url, str) and url.startswith(("http://", "https://")):
                        yield f"{child_path}[{index}]", url
            yield from _iter_result_urls(item, child_path)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            child_path = f"{path}[{index}]" if path else f"[{index}]"
            yield from _iter_result_urls(item, child_path)


def _looks_like_image(url: str, *, path: str, subtype: str, data: dict[str, Any]) -> bool:
    hint = f"{path} {subtype}".lower()
    if any(token in hint for token in ("image", "picture", "photo", "poster")):
        return True
    mime = str(data.get("mime") or data.get("content_type") or "").lower()
    if mime.startswith("image/"):
        return True
    clean_url = str(url).split("?", 1)[0].split("#", 1)[0].lower()
    return clean_url.endswith((".png", ".jpg", ".jpeg", ".webp"))


def _image_urls(run: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for entry in run.get("entry_list") or []:
        if not isinstance(entry, dict):
            continue
        for container_name in ("message", "artifact"):
            container = entry.get(container_name)
            container = container if isinstance(container, dict) else {}
            if str(container.get("role") or "").lower() == "user":
                continue
            for content in container.get("content") or []:
                if not isinstance(content, dict):
                    continue
                subtype = str(content.get("sub_type") or content.get("subtype") or "")
                data = _json_object(content.get("data"))
                for path, url in _iter_result_urls(data):
                    if _looks_like_image(url, path=path, subtype=subtype, data=data) and url not in urls:
                        urls.append(url)
    return urls


def _run_error(run: dict[str, Any]) -> str:
    for entry in run.get("entry_list") or []:
        if not isinstance(entry, dict):
            continue
        artifact = entry.get("artifact")
        artifact = artifact if isinstance(artifact, dict) else {}
        for content in artifact.get("content") or []:
            if not isinstance(content, dict):
                continue
            data = _json_object(content.get("data"))
            for field in ("error_message", "error_msg", "errmsg"):
                value = str(data.get(field) or "").strip()
                if value:
                    return value
    for field in ("fail_reason", "error_message", "error_msg", "errmsg"):
        value = str(run.get(field) or "").strip()
        if value:
            return value
    return "task failed"


def _find_run(data: dict[str, Any], run_id: str) -> dict[str, Any]:
    thread = data.get("thread")
    thread = thread if isinstance(thread, dict) else {}
    runs = [item for item in (thread.get("run_list") or []) if isinstance(item, dict)]
    for run in runs:
        if str(run.get("run_id") or "") == run_id:
            return run
    if len(runs) == 1:
        return runs[0]
    raise RuntimeError(f"Xiaoyunque poll failed: run_id={run_id} not found")


def poll_task(task_id: str) -> dict[str, Any]:
    """查询一次任务状态，归一化为 running/succeeded/failed。"""
    thread_id, run_id = _decode_task_id(task_id)
    response = requests.post(
        _base_url() + _GET_THREAD_PATH,
        headers=_headers(),
        json={"thread_id": thread_id, "run_id": run_id},
        timeout=_timeout("mm_video_poll_timeout_s", 15),
    )
    data = _response_json(response, "poll")
    run = _find_run(data, run_id)
    try:
        state = int(run.get("state", 0))
    except (TypeError, ValueError):
        state = 0
    result: dict[str, Any] = {
        "status": "running",
        "task_id": task_id,
        "provider": "xiaoyunque",
        "thread_id": thread_id,
        "run_id": run_id,
    }
    if state == 3:
        urls = _video_urls(run)
        if not urls:
            return {
                **result,
                "status": "failed",
                "error": "run succeeded without video artifact",
            }
        return {**result, "status": "succeeded", "url": urls[0], "urls": urls}
    if state in {4, 5}:
        reason = "task cancelled" if state == 5 else _run_error(run)
        return {**result, "status": "failed", "error": str(reason)}
    return result


def poll_image_task(task_id: str) -> dict[str, Any]:
    """查询一次通用 Nest 文生图任务，归一化为 running/succeeded/failed。"""
    thread_id, run_id = _decode_task_id(task_id)
    response = requests.post(
        _base_url() + _GET_THREAD_PATH,
        headers=_headers(),
        json={"thread_id": thread_id, "run_id": run_id},
        timeout=_timeout("mm_image_timeout_s", 30),
    )
    data = _response_json(response, "poll image")
    run = _find_run(data, run_id)
    raw_state = str(run.get("state") or "").strip().lower()
    result: dict[str, Any] = {
        "status": "running",
        "task_id": task_id,
        "provider": "xiaoyunque",
        "thread_id": thread_id,
        "run_id": run_id,
    }
    if raw_state in {"3", "completed", "complete", "succeeded", "success", "done"}:
        urls = _image_urls(run)
        if not urls:
            return {
                **result,
                "status": "failed",
                "error": "run succeeded without image artifact",
            }
        return {**result, "status": "succeeded", "url": urls[0], "urls": urls}
    if raw_state in {"4", "5", "failed", "failure", "error", "canceled", "cancelled"}:
        reason = "task cancelled" if raw_state in {"5", "canceled", "cancelled"} else _run_error(run)
        return {**result, "status": "failed", "error": str(reason)}
    if raw_state in {"9", "requires_action", "requires_user_input", "interaction_required"}:
        return {
            **result,
            "status": "failed",
            "error": "image task requires provider-side user interaction",
        }
    return result

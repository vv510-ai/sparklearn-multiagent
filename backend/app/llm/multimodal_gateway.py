"""多模态统一网关:开关、超时、线程隔离、缓存与安全降级。

文本大模型不经过本文件,仍只允许由 spark_client.llm_complete/llm_stream 调用。
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Awaitable, Callable

from ..agents.emitter import emit
from ..config import GEN_DIR, get_settings, is_demo
from . import (
    local_ocr,
    openai_image,
    seedance_client,
    spark_asr,
    spark_image,
    spark_ocr,
    spark_ppt,
    spark_super_tts,
    spark_tts,
)

log = logging.getLogger("sparklearn.multimodal")
MMResult = dict[str, Any]
_MM_POOL_SIZE = 4
_MM_POOL = ThreadPoolExecutor(max_workers=_MM_POOL_SIZE, thread_name_prefix="sparklearn-mm")
_MM_SLOTS = threading.BoundedSemaphore(_MM_POOL_SIZE)


class _MMPoolSaturated(RuntimeError):
    pass


async def _run_in_mm_pool(func: Callable[[], Any], timeout_s: float) -> Any:
    if not _MM_SLOTS.acquire(blocking=False):
        raise _MMPoolSaturated("multimodal worker pool saturated")

    def wrapped() -> Any:
        try:
            return func()
        finally:
            _MM_SLOTS.release()

    loop = asyncio.get_running_loop()
    future = loop.run_in_executor(_MM_POOL, wrapped)
    return await asyncio.wait_for(asyncio.shield(future), timeout=max(0.01, timeout_s))


def _trace_id(value: str) -> str:
    return value or f"mm-{uuid.uuid4().hex[:8]}"


def _error_text(error: BaseException | str) -> str:
    return str(error).replace("\r", " ").replace("\n", " ")[:240]


def _result(
    capability: str,
    trace_id: str,
    started: float,
    *,
    ok: bool,
    degraded: bool,
    data: dict[str, Any] | None = None,
    error: str = "",
) -> MMResult:
    return {
        "ok": ok,
        "degraded": degraded,
        "data": data or {},
        "error": error,
        "capability": capability,
        "elapsed_ms": int((time.monotonic() - started) * 1000),
        "trace_id": trace_id,
    }


async def _record(result: MMResult, *, agent: str) -> None:
    log.info(
        "mm_call cap=%s trace=%s ok=%s degraded=%s ms=%s error=%s",
        result["capability"],
        result["trace_id"],
        int(bool(result["ok"])),
        int(bool(result["degraded"])),
        result["elapsed_ms"],
        result["error"],
    )
    if result["ok"] and result["degraded"]:
        detail = f"{result['capability']} 处理完成（已使用本地兜底）"
    elif result["ok"]:
        detail = f"{result['capability']} 处理完成"
    else:
        detail = f"{result['capability']} 已安全降级: {result['error']}"
    try:
        await emit({
            "type": "progress",
            "agent": agent,
            "stage": result["capability"],
            "percent": 100,
            "detail": detail,
            "trace_id": result["trace_id"],
            "degraded": result["degraded"],
        })
    except Exception:  # noqa: BLE001
        log.debug("多模态 progress 事件写入失败", exc_info=True)


def _triplet_configured() -> bool:
    s = get_settings()
    return bool(s.spark_appid and s.spark_api_key and s.spark_api_secret)


def _openai_image_configured(settings: Any) -> bool:
    return bool(
        getattr(settings, "mm_openai_image_enabled", True)
        and getattr(settings, "openai_api_key", "")
        and getattr(settings, "openai_image_model", "")
    )


def capability_status() -> dict[str, dict[str, bool]]:
    s = get_settings()
    triplet = _triplet_configured()
    demo = is_demo()
    return {
        "asr": {
            "enabled": bool(getattr(s, "mm_asr_enabled", True)),
            "configured": bool(spark_asr.configured(s) and not demo),
        },
        "ocr": {
            "enabled": bool(s.mm_ocr_enabled),
            "configured": bool(
                triplet
                or demo
                or (getattr(s, "mm_local_ocr_enabled", True) and local_ocr.available())
            ),
        },
        "tts": {
            "enabled": bool(s.mm_tts_enabled),
            "configured": bool((spark_super_tts.configured(s) or triplet) and not demo),
        },
        "image": {
            "enabled": bool(s.mm_image_enabled),
            "configured": bool((triplet or _openai_image_configured(s)) and not demo),
        },
        "video": {
            "enabled": bool(s.mm_video_enabled),
            "configured": bool(seedance_client.available() and not demo),
        },
        "ppt": {
            "enabled": bool(getattr(s, "mm_ppt_enabled", True)),
            "configured": bool(spark_ppt.configured(s) and not demo),
        },
    }


async def _run_sync(
    capability: str,
    func: Callable[[], Any],
    normalize: Callable[[Any], dict[str, Any]],
    *,
    enabled: bool,
    configured: bool,
    timeout_s: float,
    trace_id: str,
    agent: str,
) -> MMResult:
    started = time.monotonic()
    trace_id = _trace_id(trace_id)
    if not enabled:
        result = _result(capability, trace_id, started, ok=False, degraded=True, error="capability disabled")
        await _record(result, agent=agent)
        return result
    if not configured:
        result = _result(capability, trace_id, started, ok=False, degraded=True, error="credentials not configured")
        await _record(result, agent=agent)
        return result
    try:
        raw = await _run_in_mm_pool(func, timeout_s)
        data = normalize(raw)
        result = _result(capability, trace_id, started, ok=True, degraded=False, data=data)
    except TimeoutError:
        result = _result(
            capability,
            trace_id,
            started,
            ok=False,
            degraded=True,
            error=f"timeout after {timeout_s:g}s",
        )
    except Exception as error:  # noqa: BLE001
        result = _result(
            capability,
            trace_id,
            started,
            ok=False,
            degraded=True,
            error=_error_text(error),
        )
    await _record(result, agent=agent)
    return result


async def ocr_image(
    image_bytes: bytes,
    *,
    hint: str = "",
    purpose: str = "tutor",
    trace_id: str = "",
) -> MMResult:
    s = get_settings()
    timeout_s = float(
        s.mm_ocr_ingest_timeout_s if purpose == "ingest" else s.mm_ocr_tutor_timeout_s
    )
    local_timeout_s = float(getattr(s, "mm_local_ocr_timeout_s", 20))
    started = time.monotonic()
    trace_id = _trace_id(trace_id)
    agent = "tutor" if purpose == "tutor" else "media"

    def normalize_spark(text: Any) -> dict[str, Any]:
        value = str(text or "").strip()
        if not value or value.startswith("("):
            raise RuntimeError(value or "OCR returned no text")
        return {"text": value, "chars": len(value), "engine": "spark_image_understanding"}

    if not s.mm_ocr_enabled:
        result = _result(
            "ocr", trace_id, started, ok=False, degraded=True, error="capability disabled"
        )
        await _record(result, agent=agent)
        return result

    attempts: list[tuple[str, Callable[[], Any], float, Callable[[Any], dict[str, Any]]]] = []
    errors: list[str] = []
    demo = is_demo()
    if demo or _triplet_configured():
        attempts.append((
            "spark",
            lambda: spark_ocr.image_to_question(
                image_bytes,
                hint=hint,
                max_tokens=4096 if purpose == "ingest" else 1024,
                timeout_s=timeout_s,
            ),
            timeout_s,
            normalize_spark,
        ))
    else:
        errors.append("spark: credentials not configured")

    local_enabled = bool(getattr(s, "mm_local_ocr_enabled", True))
    if not demo and local_enabled and local_ocr.available():
        attempts.append((
            "local",
            lambda: local_ocr.recognize(image_bytes),
            local_timeout_s,
            lambda data: {
                **dict(data),
                "chars": len(str((data or {}).get("text") or "")),
            },
        ))
    elif not demo and not local_enabled:
        errors.append("local: capability disabled")
    elif not demo:
        errors.append("local: rapidocr/onnxruntime not installed")

    for provider, call, budget, normalize in attempts:
        try:
            raw = await _run_in_mm_pool(call, budget)
            data = normalize(raw)
            if not str(data.get("text") or "").strip():
                raise RuntimeError("OCR returned no text")
            used_fallback = provider == "local"
            result = _result(
                "ocr",
                trace_id,
                started,
                ok=True,
                degraded=used_fallback,
                data=data,
                error="; ".join(errors) if used_fallback else "",
            )
            await _record(result, agent=agent)
            return result
        except TimeoutError:
            errors.append(f"{provider}: timeout after {budget:g}s")
        except Exception as error:  # noqa: BLE001
            errors.append(f"{provider}: {_error_text(error)}")

    result = _result(
        "ocr",
        trace_id,
        started,
        ok=False,
        degraded=True,
        error="; ".join(errors) or "OCR unavailable",
    )
    await _record(result, agent=agent)
    return result


async def speech_to_text(
    audio: bytes,
    *,
    encoding: str = "raw",
    sample_rate: int = 16000,
    trace_id: str = "",
) -> MMResult:
    s = get_settings()

    def normalize(text: Any) -> dict[str, Any]:
        value = str(text or "").strip()
        if not value:
            raise RuntimeError("ASR returned no text")
        return {"text": value, "chars": len(value), "provider": "spark_asr"}

    return await _run_sync(
        "asr",
        lambda: spark_asr.transcribe(
            audio,
            encoding=encoding,
            sample_rate=sample_rate,
            timeout_s=float(getattr(s, "mm_asr_timeout_s", 75)),
        ),
        normalize,
        enabled=bool(getattr(s, "mm_asr_enabled", True)),
        configured=bool(spark_asr.configured(s) and not is_demo()),
        timeout_s=float(getattr(s, "mm_asr_timeout_s", 75)),
        trace_id=trace_id,
        agent="tutor",
    )


async def tts(
    text: str,
    *,
    voice: str = "xiaoyan",
    trace_id: str = "",
) -> MMResult:
    s = get_settings()
    started = time.monotonic()
    trace_id = _trace_id(trace_id)
    enabled = bool(s.mm_tts_enabled)
    demo = is_demo()
    super_configured = bool(spark_super_tts.configured(s) and not demo)
    standard_configured = bool(_triplet_configured() and not demo)
    super_voice = str(getattr(s, "spark_super_tts_voice", "") or "x6_lingxiaoxuan_pro")
    attempts: list[tuple[str, str, Callable[[], Any]]] = []
    if super_configured:
        digest = hashlib.sha1(f"super\0{super_voice}\0{text}".encode("utf-8")).hexdigest()[:16]
        filename = f"tts_super_{digest}.mp3"
        attempts.append((
            "spark_super_tts",
            filename,
            lambda target=filename: spark_super_tts.synthesize(
                text, voice=super_voice, filename=target
            ),
        ))
    if standard_configured:
        digest = hashlib.sha1(f"standard\0{voice}\0{text}".encode("utf-8")).hexdigest()[:16]
        filename = f"tts_standard_{digest}.mp3"
        attempts.append((
            "spark_tts",
            filename,
            lambda target=filename: spark_tts.synthesize(text, voice=voice, filename=target),
        ))

    if not enabled:
        result = _result("tts", trace_id, started, ok=False, degraded=True, error="capability disabled")
        await _record(result, agent="media")
        return result
    if demo:
        result = _result("tts", trace_id, started, ok=False, degraded=True, error="real TTS disabled in demo mode")
        await _record(result, agent="media")
        return result
    if not attempts:
        result = _result("tts", trace_id, started, ok=False, degraded=True, error="credentials not configured")
        await _record(result, agent="media")
        return result

    for index, (provider, filename, _call) in enumerate(attempts):
        cached = GEN_DIR / filename
        minimum_bytes = 1024 if provider == "spark_super_tts" else 128
        if not (cached.exists() and cached.stat().st_size >= minimum_bytes):
            continue
        result = _result(
            "tts",
            trace_id,
            started,
            ok=True,
            degraded=index > 0,
            data={
                "audio_url": f"/static/gen/{filename}",
                "cached": True,
                "provider": provider,
            },
        )
        await _record(result, agent="media")
        return result

    errors: list[str] = []
    timeout_s = float(s.mm_tts_timeout_s)
    for provider, _filename, call in attempts:
        try:
            url = await _run_in_mm_pool(call, timeout_s)
            if not url:
                raise RuntimeError("TTS returned no audio")
            result = _result(
                "tts",
                trace_id,
                started,
                ok=True,
                degraded=bool(errors),
                data={"audio_url": str(url), "cached": False, "provider": provider},
                error="; ".join(errors),
            )
            await _record(result, agent="media")
            return result
        except TimeoutError:
            errors.append(f"{provider}: timeout after {timeout_s:g}s")
        except Exception as error:  # noqa: BLE001
            errors.append(f"{provider}: {_error_text(error)}")

    result = _result(
        "tts",
        trace_id,
        started,
        ok=False,
        degraded=True,
        error="; ".join(errors) or "TTS unavailable",
    )
    await _record(result, agent="media")
    return result


async def text_to_image(
    prompt: str,
    *,
    width: int = 768,
    height: int = 768,
    trace_id: str = "",
) -> MMResult:
    s = get_settings()
    started = time.monotonic()
    trace_id = _trace_id(trace_id)
    if not bool(s.mm_image_enabled):
        result = _result(
            "image", trace_id, started, ok=False, degraded=True, error="capability disabled"
        )
        await _record(result, agent="media")
        return result

    digest = hashlib.sha1(f"{width}x{height}\0{prompt}".encode("utf-8")).hexdigest()[:16]
    cache_candidates = [GEN_DIR / f"img_{digest}{suffix}" for suffix in (".jpg", ".png", ".webp")]
    cached = next((path for path in cache_candidates if path.exists() and path.stat().st_size > 0), None)
    if cached:
        result = _result(
            "image",
            trace_id,
            started,
            ok=True,
            degraded=False,
            data={"image_url": f"/static/gen/{cached.name}", "cached": True},
        )
        await _record(result, agent="media")
        return result

    def normalize(url: Any, provider: str) -> dict[str, Any]:
        if not url:
            raise RuntimeError("image generation returned no image")
        source = GEN_DIR / Path(str(url)).name
        if not source.exists() or source.stat().st_size == 0:
            raise RuntimeError("image file was not written")
        header = source.read_bytes()[:12]
        if header.startswith(b"\x89PNG\r\n\x1a\n"):
            suffix = ".png"
        elif header.startswith(b"\xff\xd8\xff"):
            suffix = ".jpg"
        elif len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WEBP":
            suffix = ".webp"
        else:
            raise RuntimeError("image file has an unsupported format")
        target = GEN_DIR / f"img_{digest}{suffix}"
        if source != target:
            source.replace(target)
        return {
            "image_url": f"/static/gen/{target.name}",
            "cached": False,
            "provider": provider,
        }

    errors: list[str] = []
    unavailable: list[str] = []
    attempts: list[tuple[str, Callable[[], Any]]] = []
    demo = is_demo()
    timeout_s = float(s.mm_image_timeout_s)
    if demo:
        unavailable.append("real image providers disabled in demo mode")
    else:
        if _openai_image_configured(s):
            attempts.append((
                "openai",
                lambda: openai_image.generate_image(
                    prompt,
                    width=width,
                    height=height,
                    filename=f"openai_img_{digest}.png",
                    timeout_s=timeout_s,
                ),
            ))
        else:
            unavailable.append("openai: credentials not configured or fallback disabled")
        if _triplet_configured():
            attempts.append((
                "spark",
                lambda: spark_image.generate_image(prompt, width=width, height=height),
            ))
        else:
            unavailable.append("spark: credentials not configured")

    for provider, call in attempts:
        try:
            raw = await _run_in_mm_pool(call, timeout_s)
            data = normalize(raw, provider)
            result = _result(
                "image",
                trace_id,
                started,
                ok=True,
                degraded=bool(errors),
                data=data,
                error="; ".join(errors),
            )
            await _record(result, agent="media")
            return result
        except TimeoutError:
            errors.append(f"{provider}: timeout after {timeout_s:g}s")
        except Exception as error:  # noqa: BLE001
            errors.append(f"{provider}: {_error_text(error)}")

    result = _result(
        "image",
        trace_id,
        started,
        ok=False,
        degraded=True,
        error="; ".join([*errors, *unavailable]) or "no image provider available",
    )
    await _record(result, agent="media")
    return result


async def video_create(
    prompt: str,
    *,
    image_url: str | None = None,
    trace_id: str = "",
) -> MMResult:
    s = get_settings()
    return await _run_sync(
        "video",
        lambda: seedance_client.create_task(prompt, image_url),
        lambda task_id: {"task_id": str(task_id), "status": "running"},
        enabled=bool(s.mm_video_enabled),
        configured=bool(seedance_client.available() and not is_demo()),
        timeout_s=float(s.mm_video_create_timeout_s),
        trace_id=trace_id,
        agent="media",
    )


async def ppt_create(query: str, *, trace_id: str = "") -> MMResult:
    s = get_settings()
    return await _run_sync(
        "ppt",
        lambda: spark_ppt.create_task(
            query,
            timeout_s=float(getattr(s, "mm_ppt_create_timeout_s", 30)),
        ),
        lambda state: dict(state),
        enabled=bool(getattr(s, "mm_ppt_enabled", True)),
        configured=bool(spark_ppt.configured(s) and not is_demo()),
        timeout_s=float(getattr(s, "mm_ppt_create_timeout_s", 30)),
        trace_id=trace_id,
        agent="doc",
    )


async def ppt_poll(task_id: str, *, trace_id: str = "") -> dict[str, Any]:
    s = get_settings()
    digest = hashlib.sha1(str(task_id).encode("utf-8")).hexdigest()[:20]
    target = GEN_DIR / f"review_ppt_{digest}.pptx"

    def fetch() -> dict[str, Any]:
        state = spark_ppt.poll_task(
            task_id,
            timeout_s=float(getattr(s, "mm_ppt_poll_timeout_s", 15)),
        )
        if state.get("status") == "ready" and state.get("url"):
            if not (target.exists() and target.stat().st_size >= 1024):
                spark_ppt.download_ppt(
                    str(state["url"]),
                    target,
                    timeout_s=float(getattr(s, "mm_ppt_download_timeout_s", 45)),
                )
            state["url"] = f"/static/gen/{target.name}"
        return state

    result = await _run_sync(
        "ppt",
        fetch,
        lambda state: dict(state),
        enabled=bool(getattr(s, "mm_ppt_enabled", True)),
        configured=bool(spark_ppt.configured(s) and not is_demo()),
        timeout_s=(
            float(getattr(s, "mm_ppt_poll_timeout_s", 15))
            + float(getattr(s, "mm_ppt_download_timeout_s", 45))
        ),
        trace_id=trace_id,
        agent="doc",
    )
    if result["ok"]:
        return result["data"]
    return {
        "status": "building",
        "task_id": task_id,
        "error": result["error"],
        "retryable": True,
    }


async def video_wait(
    task_id: str,
    *,
    budget_s: float | None = None,
    on_progress: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    trace_id: str = "",
) -> MMResult:
    s = get_settings()
    started = time.monotonic()
    trace_id = _trace_id(trace_id)
    budget = float(budget_s if budget_s is not None else s.mm_video_wait_budget_s)
    if is_demo() or not s.mm_video_enabled or not seedance_client.available():
        result = _result("video", trace_id, started, ok=False, degraded=True, error="video unavailable")
        await _record(result, agent="media")
        return result

    tick = 0
    try:
        while time.monotonic() - started < budget:
            remaining = max(0.01, budget - (time.monotonic() - started))
            try:
                state = await _run_in_mm_pool(
                    lambda: seedance_client.poll_task(task_id),
                    min(float(s.mm_video_poll_timeout_s), remaining),
                )
            except TimeoutError:
                break
            tick += 1
            status = str(state.get("status", "running"))
            if on_progress:
                await on_progress({
                    "percent": min(95, tick * 7),
                    "status": status,
                    "detail": f"Seedance task {status}",
                    "task_id": task_id,
                })
            if status == "succeeded":
                result = _result("video", trace_id, started, ok=True, degraded=False, data=state)
                await _record(result, agent="media")
                return result
            if status == "failed":
                result = _result(
                    "video",
                    trace_id,
                    started,
                    ok=False,
                    degraded=True,
                    data=state,
                    error=_error_text(state.get("error", "Seedance failed")),
                )
                await _record(result, agent="media")
                return result
            await asyncio.sleep(min(3.0, max(0.0, budget - (time.monotonic() - started))))
        result = _result(
            "video",
            trace_id,
            started,
            ok=True,
            degraded=False,
            data={"status": "running", "task_id": task_id},
        )
    except Exception as error:  # noqa: BLE001
        result = _result(
            "video",
            trace_id,
            started,
            ok=False,
            degraded=True,
            data={"status": "degraded", "task_id": task_id, "reason": _error_text(error)},
            error=_error_text(error),
        )
    await _record(result, agent="media")
    return result


async def video_poll(task_id: str, *, trace_id: str = "") -> dict[str, Any]:
    s = get_settings()
    result = await _run_sync(
        "video",
        lambda: seedance_client.poll_task(task_id),
        lambda state: dict(state),
        enabled=bool(s.mm_video_enabled),
        configured=bool(seedance_client.available() and not is_demo()),
        timeout_s=float(s.mm_video_poll_timeout_s),
        trace_id=trace_id,
        agent="media",
    )
    if result["ok"]:
        return result["data"]
    return {
        "status": "degraded",
        "task_id": task_id,
        "reason": result["error"],
    }

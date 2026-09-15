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

import requests

from ..agents.emitter import emit
from ..config import GEN_DIR, get_settings, is_demo
from ..tenant import current_user_id
from . import modern_media, openai_client, ark_video
from . import (
    local_ocr,
    spark_asr,
    spark_image,
    spark_ocr,
    spark_ppt,
    spark_super_tts,
    spark_tts,
    xiaoyunque_client,
)

log = logging.getLogger("sparklearn.multimodal")
MMResult = dict[str, Any]
_MM_POOL_SIZE = 4
_MM_POOL = ThreadPoolExecutor(max_workers=_MM_POOL_SIZE, thread_name_prefix="sparklearn-mm")
_MM_SLOTS = threading.BoundedSemaphore(_MM_POOL_SIZE)
_IMAGE_DOWNLOAD_LOCK = threading.Lock()
_VIDEO_DOWNLOAD_LOCK = threading.Lock()
_DEFAULT_MAX_IMAGE_BYTES = 32 * 1024 * 1024
_DEFAULT_MAX_VIDEO_BYTES = 256 * 1024 * 1024


class _MMPoolSaturated(RuntimeError):
    pass


def _video_target(task_id: str) -> Path:
    digest = hashlib.sha256(str(task_id).encode("utf-8")).hexdigest()[:24]
    return GEN_DIR / f"xiaoyunque_{digest}.mp4"


def _valid_mp4(path: Path) -> bool:
    try:
        if path.stat().st_size < 1024:
            return False
        with path.open("rb") as handle:
            return b"ftyp" in handle.read(64)
    except OSError:
        return False


def _download_video(
    source_url: str,
    target: Path,
    *,
    timeout_s: float,
    max_bytes: int,
) -> Path:
    """Atomically copy a provider MP4 into SparkLearn-owned storage."""
    source = str(source_url or "").strip()
    if not source.startswith("https://"):
        raise ValueError("video download URL must use HTTPS")
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(f"{target.suffix}.{uuid.uuid4().hex}.part")
    total = 0
    try:
        with requests.get(
            source,
            stream=True,
            timeout=max(1.0, float(timeout_s)),
            headers={
                "Accept": "video/mp4,video/*;q=0.9,*/*;q=0.1",
                "Accept-Encoding": "identity",
                "User-Agent": "SparkLearn-Asset-Worker/1.0",
            },
        ) as response:
            response.raise_for_status()
            content_length = response.headers.get("content-length")
            if content_length and int(content_length) > max_bytes:
                raise RuntimeError("video file exceeds configured size limit")
            with partial.open("wb") as handle:
                for chunk in response.iter_content(256 * 1024):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > max_bytes:
                        raise RuntimeError("video file exceeds configured size limit")
                    handle.write(chunk)
        if not _valid_mp4(partial):
            raise RuntimeError("video provider returned an invalid MP4 file")
        partial.replace(target)
        return target
    finally:
        partial.unlink(missing_ok=True)


def _poll_and_materialize_video(task_id: str, settings: Any) -> dict[str, Any]:
    """Return only a durable local URL after the provider task succeeds."""
    target = _video_target(task_id)
    provider = "ark" if ark_video.is_task_id(task_id) else "xiaoyunque"
    local_url = f"/static/gen/{target.name}"
    if _valid_mp4(target):
        return {
            "status": "succeeded",
            "task_id": task_id,
            "provider": provider,
            "url": local_url,
            "stored": True,
            "cached": True,
        }

    state = dict(ark_video.poll_task(task_id) if provider == "ark" else xiaoyunque_client.poll_task(task_id))
    if state.get("status") != "succeeded":
        return state

    with _VIDEO_DOWNLOAD_LOCK:
        if _valid_mp4(target):
            return {
                "status": "succeeded",
                "task_id": task_id,
                "provider": str(state.get("provider") or "xiaoyunque"),
                "url": local_url,
                "stored": True,
                "cached": True,
            }
        target.unlink(missing_ok=True)
        source_url = str(state.get("url") or "")
        if not source_url:
            raise RuntimeError("video task succeeded without a download URL")
        max_mb = max(1, int(getattr(settings, "mm_video_max_mb", 256)))
        _download_video(
            source_url,
            target,
            timeout_s=float(getattr(settings, "mm_video_download_timeout_s", 90)),
            max_bytes=min(max_mb * 1024 * 1024, _DEFAULT_MAX_VIDEO_BYTES),
        )
        durable = {key: value for key, value in state.items() if key not in {"url", "urls"}}
        durable.update({
            "status": "succeeded",
            "task_id": task_id,
            "provider": str(state.get("provider") or "xiaoyunque"),
            "url": local_url,
            "stored": True,
            "cached": False,
        })
        return durable


def _image_suffix(path: Path) -> str:
    try:
        if path.stat().st_size < 32:
            return ""
        header = path.read_bytes()[:12]
    except OSError:
        return ""
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if header.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return ".webp"
    return ""


def _download_image(
    source_url: str,
    target_stem: Path,
    *,
    timeout_s: float,
    max_bytes: int,
) -> Path:
    """Atomically copy and signature-check a provider image."""
    source = str(source_url or "").strip()
    if not source.startswith("https://"):
        raise ValueError("image download URL must use HTTPS")
    target_stem.parent.mkdir(parents=True, exist_ok=True)
    partial = target_stem.with_name(f"{target_stem.name}.{uuid.uuid4().hex}.part")
    total = 0
    try:
        with requests.get(
            source,
            stream=True,
            timeout=max(1.0, float(timeout_s)),
            headers={
                "Accept": "image/png,image/jpeg,image/webp,image/*;q=0.9,*/*;q=0.1",
                "Accept-Encoding": "identity",
                "User-Agent": "SparkLearn-Asset-Worker/1.0",
            },
        ) as response:
            response.raise_for_status()
            content_length = response.headers.get("content-length")
            if content_length and int(content_length) > max_bytes:
                raise RuntimeError("image file exceeds configured size limit")
            with partial.open("wb") as handle:
                for chunk in response.iter_content(128 * 1024):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > max_bytes:
                        raise RuntimeError("image file exceeds configured size limit")
                    handle.write(chunk)
        suffix = _image_suffix(partial)
        if not suffix:
            raise RuntimeError("image provider returned an invalid image file")
        target = target_stem.with_suffix(suffix)
        for candidate_suffix in (".png", ".jpg", ".webp"):
            candidate = target_stem.with_suffix(candidate_suffix)
            if candidate != target:
                candidate.unlink(missing_ok=True)
        partial.replace(target)
        return target
    finally:
        partial.unlink(missing_ok=True)


def _generate_xiaoyunque_image(prompt: str, digest: str, settings: Any) -> str:
    """Wait for a Nest image Run and retain only a SparkLearn-owned local file."""
    target_stem = GEN_DIR / f"xiaoyunque_img_{digest}"
    for suffix in (".png", ".jpg", ".webp"):
        cached = target_stem.with_suffix(suffix)
        if _image_suffix(cached):
            return f"/static/gen/{cached.name}"

    task_id = xiaoyunque_client.create_image_task(prompt)
    wait_budget_s = max(1.0, float(getattr(settings, "mm_xyq_image_wait_budget_s", 150)))
    poll_interval_s = max(0.2, float(getattr(settings, "mm_xyq_image_poll_interval_s", 2)))
    deadline = time.monotonic() + wait_budget_s
    while True:
        state = dict(xiaoyunque_client.poll_image_task(task_id))
        if state.get("status") == "succeeded":
            source_url = str(state.get("url") or "")
            if not source_url:
                raise RuntimeError("image task succeeded without a download URL")
            max_mb = max(1, int(getattr(settings, "mm_image_max_mb", 32)))
            with _IMAGE_DOWNLOAD_LOCK:
                for suffix in (".png", ".jpg", ".webp"):
                    cached = target_stem.with_suffix(suffix)
                    if _image_suffix(cached):
                        return f"/static/gen/{cached.name}"
                target = _download_image(
                    source_url,
                    target_stem,
                    timeout_s=float(getattr(settings, "mm_image_download_timeout_s", 60)),
                    max_bytes=min(max_mb * 1024 * 1024, _DEFAULT_MAX_IMAGE_BYTES),
                )
            return f"/static/gen/{target.name}"
        if state.get("status") == "failed":
            raise RuntimeError(str(state.get("error") or "Xiaoyunque image task failed"))
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"Xiaoyunque image task still running after {wait_budget_s:g}s")
        time.sleep(min(poll_interval_s, remaining))


async def _run_in_mm_pool(func: Callable[[], Any], timeout_s: float) -> Any:
    started = time.monotonic()
    queue_budget = min(2.0, max(0.01, timeout_s * 0.25))

    def acquire_slot() -> bool:
        try:
            return bool(_MM_SLOTS.acquire(blocking=True, timeout=queue_budget))
        except TypeError:
            # Compatibility for lightweight test semaphores and older
            # semaphore implementations without a timeout argument.
            return bool(_MM_SLOTS.acquire(blocking=False))

    if not await asyncio.to_thread(acquire_slot):
        raise _MMPoolSaturated("multimodal worker pool saturated")

    def wrapped() -> Any:
        try:
            return func()
        finally:
            _MM_SLOTS.release()

    loop = asyncio.get_running_loop()
    future = loop.run_in_executor(_MM_POOL, wrapped)
    remaining = max(0.01, timeout_s - (time.monotonic() - started))
    return await asyncio.wait_for(asyncio.shield(future), timeout=remaining)


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


def capability_status() -> dict[str, dict[str, Any]]:
    s = get_settings()
    demo = is_demo()
    result = {
        "asr": {
            "enabled": bool(getattr(s, "mm_asr_enabled", True)),
            "configured": bool(spark_asr.configured(s) and not demo),
        },
        "ocr": {
            "enabled": bool(s.mm_ocr_enabled),
            "configured": bool(
                spark_ocr.configured(s)
                or demo
                or (getattr(s, "mm_local_ocr_enabled", True) and local_ocr.available())
            ),
        },
        "tts": {
            "enabled": bool(s.mm_tts_enabled),
            "configured": bool((spark_super_tts.configured(s) or _triplet_configured()) and not demo),
        },
        "image": {
            "enabled": bool(s.mm_image_enabled),
            "configured": bool(spark_image.configured(s) and not demo),
        },
        "video": {
            "enabled": bool(s.mm_video_enabled),
            "configured": bool(xiaoyunque_client.available() and not demo),
        },
        "ppt": {
            "enabled": bool(getattr(s, "mm_ppt_enabled", True)),
            "configured": bool(spark_ppt.configured(s) and not demo),
        },
    }
    for capability in ("image", "tts", "asr", "ocr", "ppt"):
        key = "vision" if capability == "ocr" else capability
        provider = modern_media.select_provider(key, s)
        result[capability]["provider"] = provider
        if provider in {"openai", "elevenlabs", "native"}:
            result[capability]["configured"] = bool(
                (modern_media.configured(provider, s) or provider == "native") and not demo)
            result[capability]["model"] = (
                getattr(s, "elevenlabs_model", "eleven_v3") if provider == "elevenlabs" else
                "text-model + python-pptx" if provider == "native" else getattr(s, "openai_" + key + "_model", ""))
    result["video"].update(provider="xiaoyunque", model=getattr(s, "xyq_video_model", ""))
    if ark_video.selected(s):
        result["video"].update(provider="ark", model=s.ark_video_model,
                              configured=bool(ark_video.available(s) and not demo))
    return result


async def _run_modern(capability: str, provider: str, call: Callable[[], Any], *, trace_id: str, agent: str) -> MMResult:
    s = get_settings()
    def safe_call():
        try:
            return call()
        except Exception as error:
            raise RuntimeError(openai_client.error_label(error)) from None
    return await _run_sync(capability, safe_call, lambda data: dict(data),
        enabled=bool(getattr(s, "mm_" + capability + "_enabled", True)),
        configured=bool(modern_media.configured(provider, s) and not is_demo()),
        timeout_s=float(getattr(s, "openai_timeout_s", 180)) + 5, trace_id=trace_id, agent=agent)


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
    provider = modern_media.select_provider("vision", s)
    if provider == "openai":
        return await _run_modern("ocr", provider,
            lambda: modern_media.recognize(image_bytes, hint, purpose),
            trace_id=trace_id, agent="tutor" if purpose == "tutor" else "media")
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
    if provider != "local" and (demo or spark_ocr.configured(s)):
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
    provider = modern_media.select_provider("asr", s)
    if provider == "openai":
        return await _run_modern("asr", provider,
            lambda: modern_media.transcribe(audio, encoding, sample_rate), trace_id=trace_id, agent="tutor")

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
    provider = modern_media.select_provider("tts", s)
    if provider in {"openai", "elevenlabs"}:
        tenant = current_user_id() or "demo_user"
        return await _run_modern("tts", provider,
            lambda: modern_media.synthesize(text, provider, tenant), trace_id=trace_id, agent="media")
    started = time.monotonic()
    trace_id = _trace_id(trace_id)
    enabled = bool(s.mm_tts_enabled)
    demo = is_demo()
    super_configured = bool(spark_super_tts.configured(s) and not demo)
    standard_configured = bool(_triplet_configured() and not demo)
    dedicated_super_credentials = bool(
        getattr(s, "spark_super_tts_api_password", "")
        or (
            getattr(s, "spark_super_tts_appid", "")
            and getattr(s, "spark_super_tts_api_key", "")
            and getattr(s, "spark_super_tts_api_secret", "")
        )
    )
    strict_super = bool(
        super_configured
        and dedicated_super_credentials
        and getattr(s, "spark_super_tts_strict", False)
    )
    super_voice = str(getattr(s, "spark_super_tts_voice", "") or "x6_lingxiaoxuan_pro")
    speech_speed = max(0, min(100, int(getattr(s, "spark_tts_speed", 42))))
    attempts: list[tuple[str, str, Callable[[], Any]]] = []
    if super_configured:
        digest = hashlib.sha1(f"super\0{super_voice}\0{speech_speed}\0{text}".encode("utf-8")).hexdigest()[:16]
        filename = f"tts_super_{digest}.wav"
        attempts.append((
            "spark_super_tts",
            filename,
            lambda target=filename: spark_super_tts.synthesize(
                text, voice=super_voice, filename=target
            ),
        ))
    if standard_configured and not strict_super:
        digest = hashlib.sha1(f"standard\0{voice}\0{speech_speed}\0{text}".encode("utf-8")).hexdigest()[:16]
        filename = f"tts_standard_{digest}.wav"
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

    errors: list[str] = []
    timeout_s = float(s.mm_tts_timeout_s)
    for provider, filename, call in attempts:
        # Cache lookup must follow provider priority. A cached standard voice
        # from an earlier outage must not permanently mask a recovered super
        # TTS service. Only inspect the fallback cache after the preferred
        # provider has been attempted and failed in this request.
        cached = GEN_DIR / filename
        minimum_bytes = 1024 if provider == "spark_super_tts" else 128
        if cached.exists() and cached.stat().st_size >= minimum_bytes:
            result = _result(
                "tts",
                trace_id,
                started,
                ok=True,
                degraded=bool(errors),
                data={
                    "audio_url": f"/static/gen/{filename}",
                    "cached": True,
                    "provider": provider,
                },
                error="; ".join(errors),
            )
            await _record(result, agent="media")
            return result
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
        data={
            "provider": "spark_super_tts" if strict_super else "none",
            "requested_voice": super_voice if strict_super else "",
            "retryable": True,
            "strict_voice": strict_super,
        },
        error="; ".join(errors) or "TTS unavailable",
    )
    await _record(result, agent="media")
    return result


async def text_to_image(
    prompt: str,
    *,
    width: int = 768,
    height: int = 768,
    preferred_provider: str = "",
    trace_id: str = "",
) -> MMResult:
    s = get_settings()
    selected = str(preferred_provider or modern_media.select_provider("image", s)).lower()
    if selected == "openai":
        tenant = current_user_id() or "demo_user"
        return await _run_modern("image", "openai",
            lambda: modern_media.generate_image(prompt, width, height, tenant), trace_id=trace_id, agent="media")
    started = time.monotonic()
    trace_id = _trace_id(trace_id)
    if not bool(s.mm_image_enabled):
        result = _result(
            "image", trace_id, started, ok=False, degraded=True, error="capability disabled"
        )
        await _record(result, agent="media")
        return result

    preferred = "xiaoyunque" if selected == "xiaoyunque" else ""
    if selected not in {"spark", "xiaoyunque"}:
        raise ValueError("Unsupported image provider")
    if preferred not in {"", "xiaoyunque"}:
        raise ValueError(f"unsupported preferred image provider: {preferred_provider}")
    cache_scope = f"{preferred}\0" if preferred else ""
    digest = hashlib.sha1(
        f"{cache_scope}{width}x{height}\0{prompt}".encode("utf-8")
    ).hexdigest()[:16]
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
    attempts: list[tuple[str, Callable[[], Any], float]] = []
    demo = is_demo()
    timeout_s = float(s.mm_image_timeout_s)
    if demo:
        unavailable.append("real image providers disabled in demo mode")
    else:
        if preferred == "xiaoyunque":
            if bool(getattr(s, "mm_xyq_image_enabled", True)) and xiaoyunque_client.available():
                xyq_timeout_s = (
                    timeout_s
                    + float(getattr(s, "mm_xyq_image_wait_budget_s", 150))
                    + float(getattr(s, "mm_image_download_timeout_s", 60))
                    + 5
                )
                attempts.append((
                    "xiaoyunque",
                    lambda: _generate_xiaoyunque_image(prompt, digest, s),
                    xyq_timeout_s,
                ))
            else:
                unavailable.append("xiaoyunque: credentials not configured or image capability disabled")
        if spark_image.configured(s):
            attempts.append((
                "spark",
                lambda: spark_image.generate_image(prompt, width=width, height=height),
                timeout_s,
            ))
        else:
            unavailable.append("spark: credentials not configured")

    for provider, call, provider_timeout_s in attempts:
        try:
            raw = await _run_in_mm_pool(call, provider_timeout_s)
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
            errors.append(f"{provider}: timeout after {provider_timeout_s:g}s")
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
    use_ark = ark_video.selected(s)
    return await _run_sync(
        "video",
        lambda: ark_video.create_task(prompt, image_url) if use_ark else xiaoyunque_client.create_task(prompt, image_url),
        lambda task_id: {
            "task_id": str(task_id),
            "status": "running",
            "provider": "ark" if use_ark else "xiaoyunque",
            "model": s.ark_video_model if use_ark else getattr(s, "xyq_video_model", ""),
        },
        enabled=bool(s.mm_video_enabled),
        configured=bool((ark_video.available(s) if use_ark else xiaoyunque_client.available()) and not is_demo()),
        timeout_s=float(s.mm_video_create_timeout_s),
        trace_id=trace_id,
        agent="media",
    )


async def ppt_create(query: str, *, trace_id: str = "") -> MMResult:
    s = get_settings()
    if modern_media.select_provider("ppt", s) == "native":
        from ..services.native_ppt import create
        started = time.monotonic()
        try:
            if not getattr(s, "mm_ppt_enabled", True) or is_demo():
                raise RuntimeError("PPT generation is disabled or demo mode is active")
            data = await create(query)
            result = _result("ppt", _trace_id(trace_id), started, ok=True, degraded=False, data=data)
        except Exception as error:
            result = _result("ppt", _trace_id(trace_id), started, ok=False, degraded=True,
                             data={"provider": "native_pptx"}, error=openai_client.error_label(error))
        await _record(result, agent="doc")
        return result
    # Existing deployments may still carry the old 30-second environment value.
    # PPT generation is an asynchronous provider job, so keep the create request
    # alive long enough even before operators refresh their environment file.
    create_timeout_s = max(
        75.0,
        float(getattr(s, "mm_ppt_create_timeout_s", 75)),
    )
    return await _run_sync(
        "ppt",
        lambda: spark_ppt.create_task(
            query,
            timeout_s=create_timeout_s,
        ),
        lambda state: dict(state),
        enabled=bool(getattr(s, "mm_ppt_enabled", True)),
        configured=bool(spark_ppt.configured(s) and not is_demo()),
        timeout_s=create_timeout_s,
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
    available = ark_video.available(s) if ark_video.is_task_id(task_id) else xiaoyunque_client.available()
    if is_demo() or not s.mm_video_enabled or not available:
        result = _result("video", trace_id, started, ok=False, degraded=True, error="video unavailable")
        await _record(result, agent="media")
        return result

    tick = 0
    try:
        while time.monotonic() - started < budget:
            remaining = max(0.01, budget - (time.monotonic() - started))
            try:
                state = await _run_in_mm_pool(
                    lambda: _poll_and_materialize_video(task_id, s),
                    min(
                        float(s.mm_video_poll_timeout_s)
                        + float(getattr(s, "mm_video_download_timeout_s", 90)),
                        remaining,
                    ),
                )
            except TimeoutError:
                break
            tick += 1
            status = str(state.get("status", "running"))
            if on_progress:
                provider = str(state.get("provider") or "xiaoyunque")
                await on_progress({
                    "percent": min(95, tick * 7),
                    "status": status,
                    "detail": f"{provider} task {status}",
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
                    error=_error_text(state.get("error", "video provider failed")),
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
            data={
                "status": "running",
                "task_id": task_id,
                "provider": "ark" if ark_video.is_task_id(task_id) else "xiaoyunque",
            },
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
        lambda: _poll_and_materialize_video(task_id, s),
        lambda state: dict(state),
        enabled=bool(s.mm_video_enabled),
        configured=bool((ark_video.available(s) if ark_video.is_task_id(task_id) else xiaoyunque_client.available()) and not is_demo()),
        timeout_s=(
            float(s.mm_video_poll_timeout_s)
            + float(getattr(s, "mm_video_download_timeout_s", 90))
        ),
        trace_id=trace_id,
        agent="media",
    )
    if result["ok"]:
        return result["data"]
    return {
        "status": "running",
        "task_id": task_id,
        "phase": "saving",
        "error": result["error"],
        "retryable": True,
    }

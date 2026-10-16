"""Infographic generation with provider isolation and independent, bounded review."""
from __future__ import annotations

import asyncio
import hashlib
import json
import re

from ..agents.emitter import emit
from ..config import is_demo
from ..llm import multimodal_gateway as gateway
from ..llm.spark_client import llm_complete, parse_json
from ..prompt_templates import invoke_learning_prompt

RENDERER = "xiaoyunque-infographic-v1"
CHECK_NAMES = ("text", "formulas", "relations")


def unverified(reason: str) -> dict:
    return {"status": "unverified", "checks": {key: "uncertain" for key in CHECK_NAMES}, "issues": [reason]}


def _image_bytes(url: str) -> bytes:
    # Only inspect our own materialized asset; never fetch a model-provided URL.
    match = re.fullmatch(r"/static/gen/([A-Za-z0-9_.-]+\.(?:png|jpe?g|webp))", url)
    if not match:
        raise ValueError("unsupported local image path")
    path = (gateway.GEN_DIR / match[1]).resolve()
    if path.parent != gateway.GEN_DIR.resolve() or not 0 < path.stat().st_size <= 20 * 1024 * 1024:
        raise ValueError("invalid image file")
    from PIL import Image
    with Image.open(path) as image:
        image.verify()
    return path.read_bytes()


def _observations(value: object) -> dict:
    if not isinstance(value, dict) or not isinstance(value.get("text"), str) or not value["text"].strip():
        raise ValueError("missing image transcription")
    if type(value.get("legible")) is not bool:
        raise ValueError("missing legibility assessment")
    for key in ("formulas", "relations", "uncertainties"):
        if not isinstance(value.get(key), list) or not all(isinstance(item, str) and item.strip() for item in value[key]):
            raise ValueError("incomplete image observations")
    return value


def _verdict(value: object, observation: dict) -> dict:
    if not isinstance(value, dict) or not isinstance(value.get("checks"), dict):
        raise ValueError("missing review dimensions")
    checks = value["checks"]
    if set(checks) != set(CHECK_NAMES) or any(status not in {"passed", "failed", "uncertain"} for status in checks.values()):
        raise ValueError("incomplete review")
    issues = value.get("issues")
    if not isinstance(issues, list) or not all(isinstance(item, str) and item.strip() for item in issues):
        raise ValueError("invalid review findings")
    checks = dict(checks)
    issues = list(issues)
    if not observation["legible"] or observation["uncertainties"] or "[无法辨认]" in json.dumps(observation, ensure_ascii=False):
        checks = {key: status if status == "failed" else "uncertain" for key, status in checks.items()}
        issues += observation["uncertainties"] or ["图片存在无法清楚辨认的内容。"]
    if not observation["relations"]:
        checks["relations"] = "uncertain"
        issues.append("读图结果没有足够连线与分组证据，关系尚未核对。")
    if "failed" in checks.values():
        status = "failed"
    elif "uncertain" in checks.values() or issues:
        status = "unverified"
    else:
        status = "passed"
    if status != "passed" and not issues:
        issues = ["成图检查未通过，检查器未给出具体定位，请结合文字版复核。"]
    return {"status": status, "checks": checks, "issues": issues[:12]}


async def inspect_image(image_url: str, content: str, *, trace_id: str) -> dict:
    if is_demo():
        return unverified("演示模式未运行真实图片检查。")
    try:
        image = _image_bytes(image_url)
        observe = invoke_learning_prompt("image.one_page_observe")
        # Blind image reading avoids echoing expected text instead of seeing errors.
        result = await asyncio.wait_for(gateway.ocr_image(image, hint=observe.prompt,
            purpose="ingest", trace_id=trace_id), timeout=65)
        data = result.get("data") or {}
        engine = data.get("engine", "")
        if not result.get("ok") or result.get("degraded") or engine not in {"spark_image_understanding", "openai_vision"}:
            return unverified("图片理解服务不可用；普通文字识别不能证明公式和连线正确。")
        raw = data.get("text", "")
        if not isinstance(raw, str) or len(raw) > 24000:
            return unverified("读图结果不完整或超出本次核对范围。")
        observation = _observations(parse_json(raw))
        call = invoke_learning_prompt("image.one_page_check", content=content,
            observation=json.dumps(observation, ensure_ascii=False))
        compared = await asyncio.wait_for(llm_complete(call.prompt, system=call.system,
            role="reasoner", temperature=0, max_tokens=2200, json_object=True,
            reasoning_mode="disabled", allow_mock_fallback=False, allow_model_fallback=False), timeout=35)
        verdict = _verdict(parse_json(compared), observation)
        return {**verdict, "engine": engine, "image_sha256": hashlib.sha256(image).hexdigest(),
                "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
                "observation": observation, "prompt_skill": call.metadata()}
    except Exception:
        # Provider exceptions can contain URLs/credentials. Never expose them in a resource.
        return unverified("图片检查未完成，请结合文字版核对文字、公式和连线。")


async def generate_one_page(name: str, parts: list[str], *, content_status: str,
                            trace_id: str, skip_generation: bool = False) -> dict:
    from .personal_image import enabled_for_user
    personal = enabled_for_user()
    provider = "chatgpt_web" if personal else "xiaoyunque"
    provider_name = "ChatGPT" if personal else "小云雀"
    renderer = "chatgpt-web-infographic-v1" if personal else RENDERER
    pages = []
    for index, part in enumerate(parts):
        title = f"{name} · {index + 1}/{len(parts)}" if len(parts) > 1 else name
        page = {"title": title, "renderer": renderer, "provider": provider,
                "content_status": content_status, "image_status": "fallback", "attempts": []}
        pages.append(page)
        content = re.sub(r"\[\^\d+\]", "", part).strip()
        page["content_sha256"] = hashlib.sha256(content.encode()).hexdigest()
        if skip_generation or not content or len(content) > 6000:
            page["image_error"] = "本次未请求生图。" if skip_generation else "内容过多或为空，请按章节生成；文字版已保留。"
            page["verification"] = unverified(page["image_error"])
            continue
        call = invoke_learning_prompt("image.one_page", topic=title, content=content)
        prompt = call.prompt.replace("小云雀", "ChatGPT") if personal else call.prompt
        base_prompt = prompt
        page["prompt_skill"] = call.metadata()
        for attempt in range(2):
            await emit({"type": "progress", "agent": "doc", "stage": "one_page_image",
                        "text": f"正在{'修正并重新生成' if attempt else '用' + provider_name + '生成'}第 {index + 1} 张知识图…"})
            try:
                generated = await gateway.text_to_image(prompt, width=1536, height=864,
                    preferred_provider=provider, allow_provider_fallback=False, trace_id=trace_id)
            except Exception:
                generated = {"ok": False, "data": {}}
            data = generated.get("data") or {}
            if not generated.get("ok") or data.get("provider") != provider or not data.get("image_url"):
                page["attempts"].append({"attempt": attempt + 1, "status": "generation_failed"})
                if page.get("image_url"):
                    page["verification"]["issues"].append("自动修正未能生成新图片；当前展示上一张待核对图片。")
                else:
                    page["image_error"] = (data.get("detail") if personal else "") or f"{provider_name}图片未生成成功，已保留文字版与出处，请稍后重试。"
                    page["verification"] = unverified(page["image_error"])
                break  # Never retry an ambiguous paid submission automatically.
            await emit({"type": "progress", "agent": "doc", "stage": "one_page_image_check",
                        "text": f"正在核对第 {index + 1} 张图的文字、公式和关系…"})
            review = await inspect_image(data["image_url"], content, trace_id=trace_id)
            page.update(image_url=data["image_url"], image_status="ready", verification=review)
            page["attempts"].append({"attempt": attempt + 1, "image_url": data["image_url"], "verification": review})
            if review["status"] != "failed" or attempt == 1:
                break
            repair = invoke_learning_prompt("image.one_page_image_repair", base_request=base_prompt,
                issues=json.dumps(review["issues"], ensure_ascii=False))
            page["repair_prompt_skill"] = repair.metadata()
            prompt = repair.prompt
        page["generation_attempts"] = len(page["attempts"])
    return {**pages[0], "pages": pages}


# ============================================================================
# Simple mode: the learner-facing request is exactly the product template and
# ChatGPT decides how many pictures the topic needs. Quality control moves to
# an independent post-check: local OCR reads every picture without seeing the
# request, then the text model judges accuracy and coverage (three states).
# ============================================================================
SIMPLE_RENDERER = "chatgpt-web-infographic-v2"
MATERIAL_HINT_CHARS = 1500


def simple_prompt(topic: str, material_points: str = "") -> "object":
    from ..prompt_templates import render_plain_prompt
    hint = f"\n\n请以我的课程资料要点为准：\n{material_points.strip()[:MATERIAL_HINT_CHARS]}" if material_points.strip() else ""
    return render_plain_prompt("image.one_page_simple", topic=topic.strip(), material_hint=hint)


def _local_image_bytes(url: str) -> bytes | None:
    try:
        return _image_bytes(url)
    except Exception:
        return None


async def _transcribe(images: list[dict]) -> list[dict]:
    """Independent reading: OCR never receives the request or the topic."""
    from ..llm import local_ocr
    results = []
    for item in images:
        content = _local_image_bytes(str(item.get("image_url") or ""))
        text, confidence = "", 0.0
        if content and local_ocr.available():
            try:
                read = await asyncio.wait_for(asyncio.to_thread(local_ocr.recognize, content), timeout=45)
                text, confidence = read["text"], float(read.get("confidence") or 0)
            except Exception:
                text = ""
        results.append({**item, "transcript": text[:6000], "ocr_confidence": confidence})
    return results


def _image_verdict(entry: dict | None, transcript: str) -> dict:
    if not transcript.strip():
        return {"status": "unverified", "issues": ["本图文字未能自动识别，请直接阅读原图核对。"]}
    if not isinstance(entry, dict):
        return {"status": "unverified", "issues": ["自动核对没有给出这张图的结论，请结合文字版阅读。"]}
    raw = str(entry.get("status") or "")
    issues = [str(x).strip() for x in entry.get("issues") or [] if str(x).strip()][:8]
    unsure = [str(x).strip() for x in entry.get("uncertain") or [] if str(x).strip()][:6]
    status = "failed" if raw == "failed" and issues else "passed" if raw == "passed" and not issues else "unverified"
    if status == "unverified" and not issues:
        issues = unsure or ["部分内容无法自动确认，请结合原图阅读。"]
    return {"status": status, "issues": issues + ([] if status != "failed" else unsure), "title": str(entry.get("title") or "")[:40]}


async def review_images(topic: str, images: list[dict], *, material_points: str = "", trace_id: str = "") -> dict:
    transcribed = await _transcribe(images)
    blocks = [f"【图{item['index']}】\n{item['transcript'] or '（未识别到文字）'}" for item in transcribed]
    review: dict = {}
    if not is_demo() and any(item["transcript"].strip() for item in transcribed):
        call = invoke_learning_prompt("image.one_page_review", topic=topic,
            material_section=(f"课程资料要点（学习者选定，优先以此为准）：\n{material_points[:MATERIAL_HINT_CHARS]}\n" if material_points.strip() else ""),
            transcripts="\n\n".join(blocks)[:24000])
        try:
            raw = await asyncio.wait_for(llm_complete(call.prompt, system=call.system, role="reasoner",
                temperature=0, max_tokens=3600, json_object=True, reasoning_mode="disabled",
                allow_mock_fallback=False), timeout=90)
            value = parse_json(raw)
            review = value if isinstance(value, dict) else {}
            review["prompt_skill"] = call.metadata()
        except Exception:
            review = {}
    by_index = {int(entry.get("index") or 0): entry for entry in review.get("images") or [] if isinstance(entry, dict)}
    checked = []
    for item in transcribed:
        verdict = _image_verdict(by_index.get(int(item["index"])), item["transcript"]) if review else (
            {"status": "unverified", "issues": ["演示模式未运行真实核对。" if is_demo() else "自动核对暂未完成，请结合原图阅读。"]})
        checked.append({**item, "verification": verdict})
    coverage = review.get("coverage") if isinstance(review.get("coverage"), dict) else {"status": "unknown", "missing": []}
    missing = [str(x).strip() for x in coverage.get("missing") or [] if str(x).strip()][:6]
    statuses = [item["verification"]["status"] for item in checked]
    overall = "failed" if "failed" in statuses else "passed" if statuses and all(s == "passed" for s in statuses) and coverage.get("status") == "complete" else "unverified"
    issues = [f"图{item['index']}：{issue}" for item in checked for issue in item["verification"]["issues"]
              if item["verification"]["status"] != "passed"]
    if missing:
        issues.append("可能缺少的要点：" + "；".join(missing))
    text_version = str(review.get("text_version") or "").strip()
    if not text_version:
        text_version = "\n\n".join(f"## 图{item['index']}\n\n" + (item["transcript"] or "（未识别到文字）") for item in transcribed)
    return {"images": checked, "verification": {"status": overall, "checks": {"accuracy": overall, "coverage": str(coverage.get("status") or "unknown")}, "issues": issues[:12]},
            "coverage": {"status": str(coverage.get("status") or "unknown"), "missing": missing},
            "text_version": text_version, "prompt_skill": review.get("prompt_skill")}


async def generate_simple_one_page(topic: str, *, material_points: str = "", trace_id: str = "",
                                   skip_generation: bool = False) -> dict:
    call = simple_prompt(topic, material_points)
    page = {"title": topic, "renderer": SIMPLE_RENDERER, "provider": "chatgpt_web", "prompt_mode": "simple",
            "content_status": "source_bound" if material_points.strip() else "general_knowledge",
            "image_status": "fallback", "attempts": [], "prompt_skill": call.metadata(),
            "prompt_text": call.prompt}
    if skip_generation:
        page["image_error"] = "本次未请求生图。"
        page["verification"] = unverified(page["image_error"])
        return {**page, "pages": [page]}
    await emit({"type": "progress", "agent": "doc", "stage": "one_page_image",
                "text": "正在请 ChatGPT 生成一图看懂；内容多时会自动拆成多张…"})
    try:
        generated = await gateway.text_to_image(call.prompt, width=1536, height=864,
            preferred_provider="chatgpt_web", allow_provider_fallback=False, trace_id=trace_id, multi=True)
    except Exception:
        generated = {"ok": False, "data": {}}
    data = generated.get("data") or {}
    images = [dict(item) for item in data.get("images") or [] if isinstance(item, dict) and item.get("image_url")]
    if not images and data.get("image_url"):
        images = [{"index": 1, "image_url": data["image_url"], "sha256": data.get("sha256", ""),
                   "width": data.get("width"), "height": data.get("height")}]
    if not generated.get("ok") or not images:
        page["attempts"].append({"attempt": 1, "status": "generation_failed"})
        page["image_error"] = data.get("detail") or "ChatGPT 图片未生成成功，已保留文字版，请稍后重试。"
        page["verification"] = unverified(page["image_error"])
        page["generation_attempts"] = 1
        return {**page, "pages": [page]}
    await emit({"type": "progress", "agent": "doc", "stage": "one_page_image_check",
                "text": f"已取回 {len(images)} 张图，正在独立读图并核对准确性与覆盖度…"})
    review = await review_images(topic, images, material_points=material_points, trace_id=trace_id)
    gallery = [{"index": item["index"], "url": item["image_url"], "width": item.get("width"), "height": item.get("height"),
                "title": item["verification"].get("title", ""), "transcript": item.get("transcript", "")[:4000],
                "verification": {k: v for k, v in item["verification"].items() if k != "title"}} for item in review["images"]]
    page.update(image_url=images[0]["image_url"], image_status="ready", images=gallery,
                verification=review["verification"], coverage=review["coverage"],
                text_version=review["text_version"], generation_attempts=1,
                review_prompt_skill=review.get("prompt_skill"),
                conversation_url=data.get("conversation_url", ""))
    page["attempts"].append({"attempt": 1, "status": "ready", "images": len(gallery)})
    return {**page, "pages": [page]}

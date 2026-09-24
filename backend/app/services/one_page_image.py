"""Xiaoyunque infographic generation with independent, bounded image review."""
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
    pages = []
    for index, part in enumerate(parts):
        title = f"{name} · {index + 1}/{len(parts)}" if len(parts) > 1 else name
        page = {"title": title, "renderer": RENDERER, "provider": "xiaoyunque",
                "content_status": content_status, "image_status": "fallback", "attempts": []}
        pages.append(page)
        content = re.sub(r"\[\^\d+\]", "", part).strip()
        page["content_sha256"] = hashlib.sha256(content.encode()).hexdigest()
        if skip_generation or not content or len(content) > 6000:
            page["image_error"] = "本次未请求生图。" if skip_generation else "内容过多或为空，请按章节生成；文字版已保留。"
            page["verification"] = unverified(page["image_error"])
            continue
        call = invoke_learning_prompt("image.one_page", topic=title, content=content)
        prompt = call.prompt
        page["prompt_skill"] = call.metadata()
        for attempt in range(2):
            await emit({"type": "progress", "agent": "doc", "stage": "one_page_image",
                        "text": f"正在{'修正并重新生成' if attempt else '用小云雀生成'}第 {index + 1} 张知识图…"})
            try:
                generated = await gateway.text_to_image(prompt, width=1536, height=864,
                    preferred_provider="xiaoyunque", allow_provider_fallback=False, trace_id=trace_id)
            except Exception:
                generated = {"ok": False, "data": {}}
            data = generated.get("data") or {}
            if not generated.get("ok") or data.get("provider") != "xiaoyunque" or not data.get("image_url"):
                page["attempts"].append({"attempt": attempt + 1, "status": "generation_failed"})
                if page.get("image_url"):
                    page["verification"]["issues"].append("自动修正未能生成新图片；当前展示上一张待核对图片。")
                else:
                    page["image_error"] = "小云雀图片未生成成功，已保留文字版与出处，请稍后重试。"
                    page["verification"] = unverified(page["image_error"])
                break  # Never retry an ambiguous paid submission automatically.
            await emit({"type": "progress", "agent": "doc", "stage": "one_page_image_check",
                        "text": f"正在核对第 {index + 1} 张图的文字、公式和关系…"})
            review = await inspect_image(data["image_url"], content, trace_id=trace_id)
            page.update(image_url=data["image_url"], image_status="ready", verification=review)
            page["attempts"].append({"attempt": attempt + 1, "image_url": data["image_url"], "verification": review})
            if review["status"] != "failed" or attempt == 1:
                break
            repair = invoke_learning_prompt("image.one_page_image_repair", base_request=call.prompt,
                issues=json.dumps(review["issues"], ensure_ascii=False))
            page["repair_prompt_skill"] = repair.metadata()
            prompt = repair.prompt
        page["generation_attempts"] = len(page["attempts"])
    return {**pages[0], "pages": pages}

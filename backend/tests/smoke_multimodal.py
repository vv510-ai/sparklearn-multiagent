r"""真实多模态网关冒烟；不进入默认 pytest，不打印任何密钥。

示例:
  python tests/smoke_multimodal.py --image C:\path\to\lecture.png
  python tests/smoke_multimodal.py --image C:\path\to\lecture.png --video
"""
from __future__ import annotations

import argparse
import asyncio
import json
import struct
import sys
import zlib
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="backslashreplace")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import GEN_DIR, is_demo  # noqa: E402
from app.llm import multimodal_gateway as gateway  # noqa: E402

GOLDEN_DIR = Path(__file__).resolve().parent / "golden"


def _summary(result: dict) -> dict:
    data = dict(result.get("data") or {})
    if "text" in data:
        data["text_preview"] = str(data.pop("text"))[:160]
    return {
        "ok": result.get("ok"),
        "degraded": result.get("degraded"),
        "capability": result.get("capability"),
        "elapsed_ms": result.get("elapsed_ms"),
        "error": result.get("error"),
        "data": data,
    }


def _generated_path(url: str) -> Path:
    return GEN_DIR / Path(url).name


def _valid_image(path: Path) -> bool:
    data = path.read_bytes()
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        offset = 8
        width = height = 0
        compressed = bytearray()
        while offset + 12 <= len(data):
            length = struct.unpack(">I", data[offset:offset + 4])[0]
            kind = data[offset + 4:offset + 8]
            payload = data[offset + 8:offset + 8 + length]
            if len(payload) != length:
                return False
            if kind == b"IHDR" and length >= 8:
                width, height = struct.unpack(">II", payload[:8])
            elif kind == b"IDAT":
                compressed.extend(payload)
            elif kind == b"IEND":
                break
            offset += length + 12
        try:
            zlib.decompress(bytes(compressed))
        except zlib.error:
            return False
        return width > 0 and height > 0
    return data.startswith(b"\xff\xd8\xff") and data.endswith(b"\xff\xd9")


async def _run_golden() -> None:
    failures: list[str] = []
    lecture_images = sorted(GOLDEN_DIR.glob("lecture_*.png"))
    if len(lecture_images) != 2:
        failures.append(f"expected 2 lecture images, found {len(lecture_images)}")

    for image_path in lecture_images:
        result = await gateway.ocr_image(
            image_path.read_bytes(),
            hint="请完整转写讲义文字,保留标题、公式、代码和列表层级。",
            purpose="ingest",
            trace_id=f"golden-ocr-{image_path.stem}",
        )
        print(f"GOLDEN_OCR {image_path.name}", json.dumps(_summary(result), ensure_ascii=False))
        chars = int((result.get("data") or {}).get("chars") or 0)
        if not result.get("ok") or chars < 20:
            failures.append(f"OCR {image_path.name}: ok={result.get('ok')} chars={chars} error={result.get('error')}")

    narration = (GOLDEN_DIR / "narration.txt").read_text(encoding="utf-8").strip()
    tts = await gateway.tts(narration, trace_id="golden-tts")
    print("GOLDEN_TTS", json.dumps(_summary(tts), ensure_ascii=False))
    audio_url = str((tts.get("data") or {}).get("audio_url") or "")
    audio_path = _generated_path(audio_url) if audio_url else Path()
    if not tts.get("ok") or not audio_url or not audio_path.exists() or audio_path.stat().st_size == 0:
        failures.append(f"TTS: ok={tts.get('ok')} error={tts.get('error')}")

    prompts = json.loads((GOLDEN_DIR / "cover_prompts.json").read_text(encoding="utf-8"))
    if not isinstance(prompts, list) or len(prompts) != 2:
        failures.append("expected 2 cover prompts")
        prompts = []
    for item in prompts:
        prompt_id = str(item.get("id") or "cover")
        result = await gateway.text_to_image(
            str(item.get("prompt") or ""),
            width=768,
            height=768,
            trace_id=f"golden-image-{prompt_id}",
        )
        print(f"GOLDEN_IMAGE {prompt_id}", json.dumps(_summary(result), ensure_ascii=False))
        image_url = str((result.get("data") or {}).get("image_url") or "")
        output_path = _generated_path(image_url) if image_url else Path()
        valid = bool(image_url and output_path.exists() and _valid_image(output_path))
        if not result.get("ok") or not valid:
            failures.append(f"IMAGE {prompt_id}: ok={result.get('ok')} valid={valid} error={result.get('error')}")

    if failures:
        print("GOLDEN_FAIL", json.dumps(failures, ensure_ascii=False, indent=2))
        raise SystemExit(1)
    print("GOLDEN_PASS", json.dumps({"ocr": 2, "tts": 1, "image": 2}, ensure_ascii=False))


async def main() -> None:
    parser = argparse.ArgumentParser(description="SparkLearn multimodal live smoke")
    parser.add_argument("--image", type=Path, help="OCR 测试图片路径")
    parser.add_argument("--video", action="store_true", help="创建并短时轮询真实小云雀视频任务")
    parser.add_argument("--video-budget", type=float, default=15, help="请求内视频等待预算(秒)")
    parser.add_argument("--golden", action="store_true", help="运行仓库内多模态金样验收")
    args = parser.parse_args()

    print(json.dumps({
        "demo_mode": is_demo(),
        "capabilities": gateway.capability_status(),
    }, ensure_ascii=False))

    if args.golden:
        await _run_golden()
        return

    if args.image:
        if not args.image.exists():
            raise SystemExit(f"image not found: {args.image}")
        ocr = await gateway.ocr_image(
            args.image.read_bytes(),
            hint="请完整转写讲义文字,保留公式和代码。",
            purpose="ingest",
            trace_id="smoke-ocr",
        )
        print("OCR", json.dumps(_summary(ocr), ensure_ascii=False))

    tts = await gateway.tts(
        "小知多模态网关冒烟验证。",
        trace_id="smoke-tts",
    )
    print("TTS", json.dumps(_summary(tts), ensure_ascii=False))

    image = await gateway.text_to_image(
        "数据结构课程二叉树遍历教学插画,简洁白底示意图",
        trace_id="smoke-image",
    )
    print("IMAGE", json.dumps(_summary(image), ensure_ascii=False))

    if args.video:
        created = await gateway.video_create(
            "clean educational animation explaining binary tree traversal",
            trace_id="smoke-video-create",
        )
        print("VIDEO_CREATE", json.dumps(_summary(created), ensure_ascii=False))
        if created.get("ok"):
            waited = await gateway.video_wait(
                str(created["data"]["task_id"]),
                budget_s=args.video_budget,
                trace_id="smoke-video-wait",
            )
            print("VIDEO_WAIT", json.dumps(_summary(waited), ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())

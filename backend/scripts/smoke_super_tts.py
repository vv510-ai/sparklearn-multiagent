"""Live smoke test for iFlytek super-realistic TTS.

This script is intentionally separate from pytest because it uses real quota.
It never prints credentials and only passes when the super TTS provider returns
a playable MP3 artifact without falling back to standard or browser speech.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import GEN_DIR, is_demo  # noqa: E402
from app.llm import multimodal_gateway as gateway  # noqa: E402


def _audio_path(url: str) -> Path:
    return GEN_DIR / Path(url).name


async def run(text: str) -> dict:
    if is_demo():
        raise RuntimeError("super TTS smoke requires demo_mode=false")

    result = await gateway.tts(text, trace_id="smoke-super-tts")
    data = dict(result.get("data") or {})
    audio_url = str(data.get("audio_url") or "")
    provider = str(data.get("provider") or "")
    audio_path = _audio_path(audio_url) if audio_url else Path()
    size = audio_path.stat().st_size if audio_url and audio_path.is_file() else 0
    summary = {
        "ok": bool(result.get("ok")),
        "degraded": bool(result.get("degraded")),
        "provider": provider,
        "elapsed_ms": int(result.get("elapsed_ms") or 0),
        "audio_url": audio_url,
        "audio_bytes": size,
        "error": str(result.get("error") or ""),
    }
    print(json.dumps(summary, ensure_ascii=False))

    if not summary["ok"]:
        raise RuntimeError(summary["error"] or "TTS request failed")
    if summary["degraded"] or provider != "spark_super_tts":
        raise RuntimeError(f"unexpected TTS fallback provider: {provider or 'none'}")
    if size < 1024:
        raise RuntimeError("super TTS returned an invalid or empty MP3")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a real super TTS smoke test")
    parser.add_argument(
        "--text",
        default="\u4f60\u597d\uff0c\u8fd9\u662f\u4e00\u6bb5\u8d85\u62df\u4eba\u8bed\u97f3\u5408\u6210\u9a8c\u6536\u97f3\u9891\u3002",
        help="Short Chinese text to synthesize with real provider quota",
    )
    args = parser.parse_args()
    asyncio.run(run(args.text))


if __name__ == "__main__":
    main()

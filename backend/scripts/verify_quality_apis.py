"""Verify configured model access; paid generation requires explicit --live.

Run from backend: .venv/Scripts/python.exe scripts/verify_quality_apis.py --live text
Each invocation submits at most one job per requested capability. No automatic retry.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.llm import ark_video, modern_media, openai_client, spark_client


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", nargs="+", choices=["text", "image", "tts", "video", "ppt"], default=[])
    parser.add_argument("--output", default="../.tmp/guochuang/quality-api-check.json")
    args = parser.parse_args()
    results = []
    s = get_settings()
    if not args.live:
        try:
            with openai_client.client() as client:
                models = {m.id for m in client.models.list()}
            results.append({"capability": "catalog", "ok": True, "note": "Catalog visibility does not prove generation quota",
                            "selected_visible": {name: name in models for name in [s.openai_text_model, s.openai_image_model, s.openai_asr_model, s.openai_tts_model]}})
        except Exception as error:
            results.append({"capability": "catalog", "ok": False, "error": openai_client.error_label(error)})
    for capability in dict.fromkeys(args.live):
        try:
            if capability == "text":
                if spark_client.active_provider() != "openai":
                    raise ValueError("Set LLM_PROVIDER=openai before testing the OpenAI quality profile")
                data = {"model": s.openai_text_model, "text": await spark_client.llm_complete(
                    "用两句话解释二叉树的中序遍历，以根A、左孩子B、右孩子C举例。", max_tokens=1000, allow_mock_fallback=False)}
            elif capability == "image":
                data = await asyncio.to_thread(modern_media.generate_image,
                    "Create an educational diagram: root A, left child B, right child C. Three blue circles and two connecting lines on ivory. Below, write only: B → A → C. No other nodes.",
                    1024, 1024, "quality-api-synthetic-test")
            elif capability == "tts":
                data = await asyncio.to_thread(modern_media.synthesize,
                    "中序遍历，先访问左子树，再访问根结点，最后访问右子树。", "openai", "quality-api-synthetic-test")
            elif capability == "video":
                task_id = await asyncio.to_thread(ark_video.create_task,
                    "An educational animation: three blue circles form a binary tree on an ivory background. No people or text. Fixed camera.")
                data = {"task_id": task_id, "submitted": True, "completed": False,
                        "note": "Save this task id; poll it instead of resubmitting a paid job"}
            else:
                from app.services.native_ppt import create
                data = await create("为二叉树遍历制作3页复习PPT。资料：先序是根左右，中序是左根右，后序是左右根。只使用这些事实，不编造学习效果。")
            results.append({"capability": capability, "ok": True, "data": data})
        except Exception as error:
            # Central transport errors are already sanitized; keep only their
            # class here to avoid third-party response bodies in saved reports.
            results.append({"capability": capability, "ok": False, "error": openai_client.error_label(error)})
        # Persist immediately after every result, especially paid video submit.
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps({"date":dt.datetime.now(dt.timezone.utc).isoformat(), "results":results}, ensure_ascii=False, indent=2), encoding="utf-8")
        if not results[-1]["ok"]:
            break
    if not args.live:
        output = Path(args.output); output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps({"results":results}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"results":results,"output":str(output.resolve())}, ensure_ascii=False, indent=2))
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

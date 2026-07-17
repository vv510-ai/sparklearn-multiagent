"""Run one real Xiaoyunque video task without exposing the access key.

Usage from ``backend/`` after setting ``XYQ_ACCESS_KEY`` in the environment:
    python tests/smoke_xiaoyunque.py --wait 300

This is deliberately separate from pytest because it consumes real quota.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.llm import xiaoyunque_client  # noqa: E402


def _safe(result: dict) -> dict:
    return {
        key: value
        for key, value in result.items()
        if key in {"status", "provider", "task_id", "thread_id", "run_id", "url", "error"}
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Xiaoyunque video live smoke")
    parser.add_argument("--wait", type=float, default=300, help="maximum poll time in seconds")
    parser.add_argument("--interval", type=float, default=10, help="poll interval in seconds")
    parser.add_argument("--task-id", default="", help="resume polling an existing task")
    parser.add_argument(
        "--prompt",
        default=(
            "A clean five-second educational 2D animation of three blue nodes "
            "forming a binary tree, white background, no text, 16:9."
        ),
    )
    args = parser.parse_args()

    if not xiaoyunque_client.available():
        raise SystemExit("XYQ_ACCESS_KEY is not configured")

    task_id = str(args.task_id or "").strip()
    if task_id:
        if not xiaoyunque_client.is_task_id(task_id):
            raise SystemExit("invalid Xiaoyunque task id")
        print("RESUME", json.dumps({"status": "running", "provider": "xiaoyunque", "task_id": task_id}))
    else:
        task_id = xiaoyunque_client.create_task(args.prompt)
        print("CREATE", json.dumps({"status": "running", "provider": "xiaoyunque", "task_id": task_id}))

    deadline = time.monotonic() + max(0.0, args.wait)
    while True:
        result = xiaoyunque_client.poll_task(task_id)
        print("POLL", json.dumps(_safe(result), ensure_ascii=False))
        if result.get("status") == "succeeded":
            return
        if result.get("status") == "failed":
            raise SystemExit(1)
        if time.monotonic() >= deadline:
            raise SystemExit(2)
        time.sleep(max(1.0, args.interval))


if __name__ == "__main__":
    main()

"""Debug run APIs for reading trace artifacts created under backend/runs."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from ..auth import require_current_user_id
from ..config import RUNS_DIR

router = APIRouter(prefix="/api/debug", tags=["debug"])

_SESSION_RE = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _run_dir(session_id: str) -> Path:
    if not _SESSION_RE.match(session_id):
        raise HTTPException(400, "invalid session_id")
    root = RUNS_DIR.resolve()
    path = (RUNS_DIR / session_id).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise HTTPException(400, "invalid session_id") from exc
    if not path.exists() or not path.is_dir():
        raise HTTPException(404, "debug run not found")
    return path


def read_run_report(session_id: str, user_id: str | None = None) -> dict[str, Any]:
    path = _run_dir(session_id)
    state = _read_json(path / "state.summary.json", {})
    if user_id is not None and str(state.get("user_id") or "") != str(user_id):
        raise HTTPException(404, "debug run not found")
    summary = _read_json(path / "summary.json", {})
    timeline = _read_json(path / "timeline.json", [])
    return {
        "session_id": session_id,
        "run_dir": str(path),
        "debug_report": _read_text(path / "debug_report.md"),
        "summary": summary,
        "state": state,
        "agent_status": _read_json(path / "agent_status.json", {}),
        "resources": _read_json(path / "resources" / "index.json", []),
        "timeline": timeline[:80] if isinstance(timeline, list) else [],
    }


@router.get("/runs/{session_id}")
async def get_run_report(session_id: str):
    return read_run_report(session_id, require_current_user_id())

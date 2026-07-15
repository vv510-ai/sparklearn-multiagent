"""Turn evaluation events into an explainable learning-evidence ledger."""
from __future__ import annotations

from typing import Any

from sqlalchemy import select

from ..models.db import session
from ..models.entities import EventLog
from .knowledge_graph import kp_name

_DEFAULT_MASTERY = 0.30
_PHASE_PRIORITY = ("spaced_review", "retest", "initial")


def _integer(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _mastery(value: Any, fallback: float) -> float:
    try:
        return round(min(1.0, max(0.0, float(value))), 3)
    except (TypeError, ValueError):
        return round(fallback, 3)


def _phase(payload: dict[str, Any]) -> str:
    phases = {
        str(value).strip()
        for value in (payload.get("evidence_phases") or [])
        if str(value).strip()
    }
    for phase in _PHASE_PRIORITY:
        if phase in phases:
            return phase
    return "initial"


def _per_kp(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("per_kp") or {}
    values = raw.values() if isinstance(raw, dict) else raw if isinstance(raw, list) else []
    return [value for value in values if isinstance(value, dict)]


def build_learning_evidence(user_id: str, limit: int = 12) -> dict[str, Any]:
    """Return recent evidence rounds plus totals across the full event history.

    ``quiz_eval`` events already contain the exact signals used by BKT. Walking
    them from oldest to newest lets us reconstruct the mastery value entering
    each round while keeping the ledger compatible with historical records.
    """
    with session() as db:
        rows = db.execute(
            select(EventLog)
            .where(EventLog.user_id == user_id, EventLog.etype == "quiz_eval")
            .order_by(EventLog.created_at.asc(), EventLog.id.asc())
        ).scalars().all()

    previous_mastery: dict[str, float] = {}
    records: list[dict[str, Any]] = []
    summary = {
        "rounds": 0,
        "answers": 0,
        "raw_correct": 0,
        "mastery_correct": 0,
        "supported": 0,
        "independent": 0,
        "by_phase": {"initial": 0, "retest": 0, "spaced_review": 0},
    }

    for row in rows:
        payload = row.payload if isinstance(row.payload, dict) else {}
        phase = _phase(payload)
        points: list[dict[str, Any]] = []
        for raw in _per_kp(payload):
            kp = str(raw.get("kp") or "").strip()
            if not kp:
                continue
            before = previous_mastery.get(kp, _DEFAULT_MASTERY)
            after = _mastery(raw.get("mastery"), before)
            previous_mastery[kp] = after
            answered = _integer(raw.get("n"))
            raw_correct = min(answered, _integer(raw.get("right")))
            # Events created before supported/revealed answers were introduced
            # only stored ``right``; at that time every correct answer entered
            # BKT, so ``right`` is the truthful compatibility fallback.
            mastery_correct = min(
                answered,
                _integer(raw.get("mastery_right", raw.get("right"))),
            )
            supported = min(answered, _integer(raw.get("supported")))
            points.append({
                "kp": kp,
                "name": kp_name(kp),
                "answers": answered,
                "raw_correct": raw_correct,
                "mastery_correct": mastery_correct,
                "supported": supported,
                "mastery_before": round(before, 3),
                "mastery_after": after,
                "mastery_delta": round(after - before, 3),
                "level": str(raw.get("level") or ""),
            })

        if not points:
            continue
        answered = sum(point["answers"] for point in points)
        raw_correct = sum(point["raw_correct"] for point in points)
        mastery_correct = sum(point["mastery_correct"] for point in points)
        supported = sum(point["supported"] for point in points)
        errors = payload.get("errors") if isinstance(payload.get("errors"), dict) else {}
        record = {
            "id": row.id,
            "created_at": row.created_at.isoformat() if row.created_at else "",
            "phase": phase,
            "answers": answered,
            "raw_correct": raw_correct,
            "mastery_correct": mastery_correct,
            "supported": supported,
            "independent": max(0, answered - supported),
            "errors": errors,
            "knowledge_points": points,
        }
        records.append(record)
        summary["rounds"] += 1
        summary["answers"] += answered
        summary["raw_correct"] += raw_correct
        summary["mastery_correct"] += mastery_correct
        summary["supported"] += supported
        summary["independent"] += max(0, answered - supported)
        summary["by_phase"][phase] = summary["by_phase"].get(phase, 0) + 1

    return {
        "items": list(reversed(records[-limit:])),
        "summary": summary,
    }

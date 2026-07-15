"""Durable spaced-review scheduling for quiz questions.

The schedule uses independent retrieval practice at 1, 3, 7, 14 and 30 days.
Any incorrect review resets the item to the short one-day interval.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import select

from ..models.db import session
from ..models.entities import Resource, ReviewItem
from .knowledge_graph import kp_name

INTERVAL_DAYS = (1, 3, 7, 14, 30)


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def as_utc(value: dt.datetime | None) -> dt.datetime:
    if value is None:
        return utc_now()
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(dt.timezone.utc)


def _history(data: dict[str, Any] | None, event: dict[str, Any]) -> dict[str, Any]:
    result = dict(data or {})
    events = [item for item in result.get("history", []) if isinstance(item, dict)]
    result["history"] = [*events, event][-20:]
    return result


def schedule_initial_reviews(
    user_id: str,
    quiz_resource_id: str,
    source_attempt_id: int,
    answers: list[dict],
    *,
    at: dt.datetime | None = None,
) -> int:
    """Create/reset due-now items for answers lacking independent evidence."""
    current = as_utc(at)
    scheduled = 0
    with session() as s:
        for answer in answers:
            if bool(answer.get("mastery_correct", answer.get("correct"))):
                continue
            question_id = str(answer.get("question_id") or "")
            if not question_id:
                continue
            row = s.execute(select(ReviewItem).where(
                ReviewItem.user_id == user_id,
                ReviewItem.quiz_resource_id == quiz_resource_id,
                ReviewItem.question_id == question_id,
            )).scalar_one_or_none()
            if row is None:
                row = ReviewItem(user_id=user_id, quiz_resource_id=quiz_resource_id,
                                 question_id=question_id)
                s.add(row)
            row.kp = str(answer.get("kp") or "")
            row.source_attempt_id = source_attempt_id
            row.stage = 0
            row.status = "scheduled"
            row.due_at = current
            row.last_correct = 0
            row.data = _history(row.data, {
                "phase": "initial",
                "correct": False,
                "at": current.isoformat(),
            })
            row.data = {
                **row.data,
                "misconception": str(answer.get("misconception") or ""),
                "error_tags": list(answer.get("error_tags") or []),
            }
            scheduled += 1
        s.commit()
    return scheduled


def apply_review_results(
    user_id: str,
    results: list[dict],
    *,
    phase: str,
    quiz_resource_id: str = "",
    at: dt.datetime | None = None,
) -> list[dict]:
    """Advance or reset schedules after an independent retest/review."""
    current = as_utc(at)
    schedules: list[dict] = []
    with session() as s:
        for result in results:
            row = None
            review_item_id = result.get("review_item_id")
            if review_item_id:
                row = s.get(ReviewItem, int(review_item_id))
                if row and row.user_id != user_id:
                    row = None
            if row is None:
                resource_id = quiz_resource_id or str(result.get("quiz_resource_id") or "")
                question_id = str(result.get("question_id") or "")
                row = s.execute(select(ReviewItem).where(
                    ReviewItem.user_id == user_id,
                    ReviewItem.quiz_resource_id == resource_id,
                    ReviewItem.question_id == question_id,
                )).scalar_one_or_none()
                if row is None and resource_id and question_id:
                    row = ReviewItem(
                        user_id=user_id,
                        quiz_resource_id=resource_id,
                        question_id=question_id,
                        kp=str(result.get("kp") or ""),
                        stage=0,
                        status="scheduled",
                        due_at=current,
                    )
                    s.add(row)
                    s.flush()
            if row is None:
                continue

            correct = bool(result.get("mastery_correct", result.get("correct")))
            if correct:
                next_stage = int(row.stage or 0) + 1
                if next_stage > len(INTERVAL_DAYS):
                    row.stage = next_stage
                    row.status = "mastered"
                    row.due_at = current
                    interval_days = None
                else:
                    interval_days = INTERVAL_DAYS[next_stage - 1]
                    row.stage = next_stage
                    row.status = "scheduled"
                    row.due_at = current + dt.timedelta(days=interval_days)
            else:
                interval_days = 1
                row.stage = 0
                row.status = "scheduled"
                row.due_at = current + dt.timedelta(days=interval_days)
                row.lapse_count = int(row.lapse_count or 0) + 1

            row.last_correct = int(correct)
            row.data = _history(row.data, {
                "phase": phase,
                "correct": correct,
                "at": current.isoformat(),
                "next_interval_days": interval_days,
            })
            schedules.append({
                "review_item_id": row.id,
                "question_id": row.question_id,
                "correct": correct,
                "stage": row.stage,
                "status": row.status,
                "due_at": as_utc(row.due_at).isoformat(),
                "interval_days": interval_days,
                "lapse_count": row.lapse_count,
            })
        s.commit()
    return schedules


def review_queue(user_id: str, *, limit: int = 10, at: dt.datetime | None = None) -> dict:
    """Return due questions without answers plus aggregate schedule counts."""
    current = as_utc(at)
    with session() as s:
        rows = s.execute(
            select(ReviewItem)
            .where(ReviewItem.user_id == user_id)
            .order_by(ReviewItem.due_at.asc(), ReviewItem.id.asc())
        ).scalars().all()
        resources = {
            row.id: row
            for row in s.execute(select(Resource).where(
                Resource.id.in_({item.quiz_resource_id for item in rows})
            )).scalars().all()
        } if rows else {}

    scheduled_rows = [row for row in rows if row.status == "scheduled"]
    due_rows = [row for row in scheduled_rows if as_utc(row.due_at) <= current]
    upcoming_rows = [row for row in scheduled_rows if as_utc(row.due_at) > current]
    items = []
    for row in due_rows[:max(1, min(limit, 50))]:
        resource = resources.get(row.quiz_resource_id)
        payload = resource.payload if resource and isinstance(resource.payload, dict) else {}
        question = next((item for item in payload.get("questions", [])
                         if isinstance(item, dict) and str(item.get("id")) == row.question_id), None)
        if not question:
            continue
        data = row.data if isinstance(row.data, dict) else {}
        reason = str(data.get("misconception") or "")
        if not reason:
            tags = data.get("error_tags") if isinstance(data.get("error_tags"), list) else []
            reason = str(tags[0]) if tags else "需要巩固"
        items.append({
            "id": row.id,
            "quiz_resource_id": row.quiz_resource_id,
            "question_id": row.question_id,
            "kp": row.kp,
            "kp_name": kp_name(row.kp),
            "stage": row.stage,
            "due_at": as_utc(row.due_at).isoformat(),
            "lapse_count": row.lapse_count,
            "reason": reason,
            "question": {
                "id": row.question_id,
                "type": question.get("type", ""),
                "stem": question.get("stem", ""),
                "options": list(question.get("options") or []),
                "kp": question.get("kp", row.kp),
                "difficulty": question.get("difficulty", 0),
            },
        })

    return {
        "items": items,
        "summary": {
            "due": len(due_rows),
            "upcoming": len(upcoming_rows),
            "mastered": sum(row.status == "mastered" for row in rows),
            "next_due_at": (as_utc(upcoming_rows[0].due_at).isoformat()
                            if upcoming_rows else None),
            "interval_days": list(INTERVAL_DAYS),
        },
    }

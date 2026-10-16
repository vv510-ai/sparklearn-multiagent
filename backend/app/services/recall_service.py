"""Persistent flashcard/mnemonic recall, scoped to the original resource owner.

ReviewItem is the shared schedule store. Ratings here are recall evidence,
not an exam score or a claim of independently assessed concept mastery.
"""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import re
import unicodedata

from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from ..auth import enforce_user_scope
from ..models.db import session
from ..models.entities import Resource, ReviewItem
from .course_library import blocked_payload, WITHDRAWN
from .learning_scope import event_in_scope
from .review_scheduler import VERSION, schedule
from .review_service import as_utc, utc_now


def _resource(db, user: str, resource_id: str, *, lock: bool = False) -> Resource:
    enforce_user_scope(user)
    query = select(Resource).where(Resource.id == resource_id, Resource.user_id == user)
    row = db.scalar(query.with_for_update() if lock else query)
    if row is None or not event_in_scope(row.payload or {}):
        raise HTTPException(404, "复习资源不存在")
    if blocked_payload(row.payload or {}):
        raise HTTPException(410, WITHDRAWN)
    if row.kind not in {"flashcards", "song"}:
        raise HTTPException(400, "这份资源不支持闪卡或口诀复习")
    return row


def _cards(resource: Resource) -> list[dict]:
    payload = resource.payload or {}
    items = []
    if resource.kind == "flashcards":
        artifact = payload.get("flashcards") or {}
        if not artifact.get("blocked"):
            for card in artifact.get("cards") or []:
                if isinstance(card, dict) and card.get("front") and card.get("back"):
                    items.append({"front": str(card["front"]), "back": str(card["back"]),
                                  "hint": str(card.get("hint") or ""), "mode": "self"})
    else:
        song = payload.get("song") or {}
        for card in song.get("cloze") or []:
            if not isinstance(card, dict):
                continue
            line, answer = str(card.get("line") or ""), str(card.get("answer") or "")
            if answer.strip() and answer in line:
                items.append({"front": line.replace(answer, "____"), "back": answer, "hint": "", "mode": "cloze"})
        if not items:
            for card in song.get("mnemonic") or []:
                if isinstance(card, dict) and card.get("line"):
                    items.append({"front": "回忆这条口诀的含义：" + str(card["line"]) if card.get("meaning") else "回忆一条记忆口诀",
                                  "back": str(card.get("meaning") or card["line"]), "hint": "", "mode": "self"})
    for index, card in enumerate(items):
        # Include content so a different prompt/answer cannot inherit old strength.
        identity = json.dumps([resource.kind, index, card["front"], card["back"]], ensure_ascii=False)
        card["key"] = "recall:" + hashlib.sha256(identity.encode()).hexdigest()[:32]
    return items[:60]


def _public(card: dict, row: ReviewItem | None) -> dict:
    data = row.data or {} if row else {}
    return {**{key: value for key, value in card.items() if key != "back" or card["mode"] == "self"},
            "registered": row is not None, "revision": int(data.get("revision", 0)),
            "due_at": as_utc(row.due_at).isoformat() if row else None,
            "attempts": int((data.get("schedule") or {}).get("attempts", 0)),
            "scheduler": (data.get("schedule") or {}).get("scheduler", VERSION)}


def get_recall(user: str, resource_id: str, *, due_only: bool = False) -> dict:
    current = utc_now()
    with session() as db:
        resource = _resource(db, user, resource_id)
        rows = {row.question_id: row for row in db.scalars(select(ReviewItem).where(
            ReviewItem.user_id == user, ReviewItem.quiz_resource_id == resource_id)).all()}
        cards = _cards(resource)
        items = [_public(card, rows.get(card["key"])) for card in cards
                 if not due_only or (card["key"] in rows and rows[card["key"]].status == "scheduled"
                                     and as_utc(rows[card["key"]].due_at) <= current)]
        return {"resource_id": resource_id, "kind": resource.kind, "title": resource.title,
                "items": items, "total": len(cards), "registered": sum(card["key"] in rows for card in cards),
                "scheduler": VERSION}


def enroll(user: str, resource_id: str) -> dict:
    with session() as db:
        resource = _resource(db, user, resource_id, lock=True)
        cards = _cards(resource)
        if not cards:
            raise HTTPException(400, "这份资源还没有可复习的内容")
        existing = set(db.scalars(select(ReviewItem.question_id).where(
            ReviewItem.user_id == user, ReviewItem.quiz_resource_id == resource_id)).all())
        for card in cards:
            if card["key"] not in existing:
                db.add(ReviewItem(user_id=user, quiz_resource_id=resource_id, question_id=card["key"],
                    kp=resource.kp, due_at=utc_now(), status="scheduled",
                    data={"recall_kind": resource.kind, "revision": 0, "history": [], "schedule": {}}))
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(409, "复习计划已在另一页面更新，请刷新") from exc
    return get_recall(user, resource_id)


def _normalized(value: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value)).casefold()


def record(user: str, resource_id: str, req) -> dict:
    current = utc_now()
    fingerprint = hashlib.sha256(json.dumps(req.model_dump(mode="json", exclude={"request_id", "revision"}),
        ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    with session() as db:
        resource = _resource(db, user, resource_id, lock=True)
        card = next((item for item in _cards(resource) if item["key"] == req.card_key), None)
        if card is None:
            raise HTTPException(404, "这张复习卡不存在")
        row = db.scalar(select(ReviewItem).where(ReviewItem.user_id == user,
            ReviewItem.quiz_resource_id == resource_id, ReviewItem.question_id == card["key"]).with_for_update())
        if row is None:
            raise HTTPException(409, "请先将这组内容加入复习")
        data = copy.deepcopy(row.data or {})
        operation = (data.get("operations") or {}).get(str(req.request_id))
        if operation:
            if operation["fingerprint"] != fingerprint:
                raise HTTPException(409, "同一次提交的内容已变化，请重新操作")
            return operation["result"]
        if int(data.get("revision", 0)) != req.revision:
            raise HTTPException(409, "另一页面已更新复习记录，请刷新后继续")
        correct = _normalized(req.answer) == _normalized(card["back"]) if card["mode"] == "cloze" else req.rating != "again"
        prior = dict(data.get("schedule") or {})
        prior["due_at"] = as_utc(row.due_at).isoformat()
        early = as_utc(row.due_at) > current
        track, audit = schedule(prior, {"early": early, "used_help": req.used_help, "correct": correct},
                                req.rating, current, f"recall:{user}:{resource_id}:{card['key']}")
        result = {"card_key": card["key"], "revision": req.revision + 1, "correct": correct,
                  "answer": card["back"], "due_at": track["due_at"], "attempts": track["attempts"],
                  "scheduler": track.get("scheduler", VERSION),
                  "evidence": "keyword_recall" if card["mode"] == "cloze" else "self_reported",
                  **{key: value for key, value in audit.items() if key != "fsrs_log"}}
        data.update(schedule=track, revision=req.revision + 1)
        data["history"] = [*(data.get("history") or []), {"phase": "recall", "at": current.isoformat(),
            "correct": correct, "used_help": req.used_help, "early": early,
            "rating": req.rating, "evidence": result["evidence"], **audit}][-40:]
        operations = {**(data.get("operations") or {}), str(req.request_id): {"fingerprint": fingerprint, "result": result}}
        data["operations"] = dict(list(operations.items())[-20:])
        updated = db.execute(update(ReviewItem).where(ReviewItem.id == row.id,
            func.coalesce(ReviewItem.data["revision"].as_integer(), 0) == req.revision).values(
                data=data, due_at=dt.datetime.fromisoformat(track["due_at"]),
                last_correct=int(correct and not req.used_help),
                lapse_count=int(row.lapse_count or 0) + int(audit["scheduling_applied"] and audit["effective_rating"] == "again")))
        if updated.rowcount != 1:
            db.rollback()
            raise HTTPException(409, "复习记录刚刚更新，请刷新后继续")
        db.commit()
        return result


def recall_queue(user: str) -> dict:
    current = utc_now()
    with session() as db:
        pairs = db.execute(select(ReviewItem, Resource).join(Resource, Resource.id == ReviewItem.quiz_resource_id).where(
            ReviewItem.user_id == user, Resource.user_id == user, Resource.kind.in_(["flashcards", "song"]),
            ReviewItem.status == "scheduled").order_by(ReviewItem.due_at)).all()
        groups = {}
        for row, resource in pairs:
            if not event_in_scope(resource.payload or {}) or blocked_payload(resource.payload or {}):
                continue
            if row.question_id not in {card["key"] for card in _cards(resource)}:
                continue
            group = groups.setdefault(resource.id, {"resource_id": resource.id, "title": resource.title,
                "kind": resource.kind, "due": 0, "upcoming": 0, "next_due_at": as_utc(row.due_at).isoformat()})
            group["due" if as_utc(row.due_at) <= current else "upcoming"] += 1
        return {"items": list(groups.values()), "due": sum(item["due"] for item in groups.values()),
                "upcoming": sum(item["upcoming"] for item in groups.values()), "scheduler": VERSION}

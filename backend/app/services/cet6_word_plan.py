"""Stable daily new-word plans; review workload is independent of the quota."""
from __future__ import annotations

import copy
import datetime as dt

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from ..models.db import session
from ..models.entities import VocabularyCard, VocabularyDay
from ..schemas.cet6 import Preferences
from . import cet6_learning as learning

STUDY_ZONE = dt.timezone(dt.timedelta(hours=8))


def day_key(when=None):
    return (when or learning.now()).astimezone(STUDY_ZONE).date().isoformat()


def save_target(user, notebook, revision, target):
    learning.check(user, notebook)
    current = learning.profile(user, notebook)
    if current["revision"] != revision:
        raise HTTPException(409, "另一页面已修改学习设置，请刷新目标后重试。")
    learning.save_profile(user, notebook, revision, Preferences(**{
        **current["preferences"], "daily_new_words": target,
    }))
    return today(user, notebook)


def today(user, notebook):
    learning.check(user, notebook)
    from .cet6_vocabulary import entries
    from .vocabulary_lessons import curated_words

    catalog = entries()
    ready = curated_words()
    profile = learning.profile(user, notebook)
    prefs = profile["preferences"]
    target = prefs["daily_new_words"]
    current = learning.now()
    day = day_key(current)
    key = learning.stable_id("word-day", user, notebook, day)
    for _ in range(4):
        with session() as db:
            cards = db.scalars(select(VocabularyCard).where(
                VocabularyCard.user_id == user, VocabularyCard.notebook_id == notebook)).all()
            learnt = {c.entry_id for c in cards if c.data.get("tracks")}
            completed = list(dict.fromkeys(c.entry_id for c in sorted(cards,
                key=lambda c: c.data.get("introduced_at", "")) if c.data.get("introduced_on") == day))
            row = db.scalar(select(VocabularyDay).where(VocabularyDay.id == key,
                VocabularyDay.user_id == user, VocabularyDay.notebook_id == notebook))
            if row:
                pool = [i for i in row.data["entry_ids"] if i in catalog]
            else:
                previous = db.scalar(select(VocabularyDay).where(VocabularyDay.user_id == user,
                    VocabularyDay.notebook_id == notebook, VocabularyDay.day < day)
                    .order_by(VocabularyDay.day.desc()).limit(1))
                carry = [i for i in (previous.data["entry_ids"] if previous else [])
                         if i in catalog and i not in learnt]
                pool = list(dict.fromkeys(completed + carry[:max(0, target - len(completed))]))
            # Raising the target appends to the saved pool. Lowering it hides the
            # excess pending words without erasing completed or in-progress work.
            available = sorted((e for e in catalog.values() if e["senses"] and e["id"] not in learnt
                and e["id"] not in pool), key=lambda e: (
                    e["word"].casefold() not in ready,
                    e["level"] != ("foundation" if prefs["mode"] == "foundation" else "cet6"),
                    e.get("frequency") or 999999, e["id"]))
            pool += [e["id"] for e in available[:max(0, target - len(pool))]]
            if row is None:
                db.add(VocabularyDay(id=key, user_id=user, notebook_id=notebook,
                    day=day, data={"entry_ids": pool, "created_at": current.isoformat()}, revision=0))
                try:
                    db.commit()
                except IntegrityError:
                    db.rollback()
                    continue
            elif pool != row.data["entry_ids"]:
                data = {**copy.deepcopy(row.data), "entry_ids": pool}
                changed = db.execute(update(VocabularyDay).where(VocabularyDay.id == key,
                    VocabularyDay.user_id == user, VocabularyDay.revision == row.revision)
                    .values(data=data, revision=row.revision + 1))
                if changed.rowcount != 1:
                    db.rollback()
                    continue
                db.commit()
            remaining = [i for i in pool if i not in learnt][:max(0, target - len(completed))]
            review_due = sum(t.get("due_at", "z") <= current.isoformat()
                for c in cards for t in c.data.get("tracks", {}).values())
            review_done = sum(bool(h.get("is_review")) and day_key(dt.datetime.fromisoformat(h["submitted_at"])) == day
                for c in cards for h in c.data.get("history", []) if h.get("submitted_at"))
            return {"day": day, "timezone": "Asia/Shanghai", "target": target,
                "new_done": len(completed), "new_remaining": len(remaining), "new_ids": remaining,
                "completed_ids": completed, "review_due": review_due, "review_done": review_done,
                "profile_revision": profile["revision"],
                "available_new": len(catalog) - len(learnt)}
    raise HTTPException(409, "今日计划正在另一页面更新，请重试。")

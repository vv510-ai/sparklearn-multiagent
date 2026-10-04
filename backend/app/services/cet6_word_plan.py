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
from . import cet6_word_groups as groups

STUDY_ZONE = dt.timezone(dt.timedelta(hours=8))


def day_key(when=None):
    return (when or learning.now()).astimezone(STUDY_ZONE).date().isoformat()


def save_target(user, notebook, revision, target, word_order=None):
    learning.check(user, notebook)
    current = learning.profile(user, notebook)
    if current["revision"] != revision:
        raise HTTPException(409, "另一页面已修改学习设置，请刷新目标后重试。")
    learning.save_profile(user, notebook, revision, Preferences(**{
        **current["preferences"], "daily_new_words": target,
        "word_order": word_order or current["preferences"]["word_order"],
    }))
    return today(user, notebook)


def today(user, notebook):
    learning.check(user, notebook)
    from .cet6_vocabulary import entries
    catalog = entries()
    profile = learning.profile(user, notebook)
    prefs = profile["preferences"]
    target = prefs["daily_new_words"]
    order = prefs["word_order"]
    current = learning.now()
    day = day_key(current)
    key = learning.stable_id("word-day", user, notebook, day)
    for _ in range(4):
        with session() as db:
            cards = db.scalars(select(VocabularyCard).where(
                VocabularyCard.user_id == user, VocabularyCard.notebook_id == notebook)).all()
            learnt = {c.entry_id for c in cards if c.data.get("tracks")}
            days = db.scalars(select(VocabularyDay).where(VocabularyDay.user_id == user,
                VocabularyDay.notebook_id == notebook).order_by(VocabularyDay.day.desc())).all()
            # Already opened rounds are immutable snapshots, including yesterday's.
            protected = list(dict.fromkeys([c.entry_id for c in cards if c.data.get("active") and c.entry_id not in learnt]
                + [item["entry_id"] for d in reversed(days) for r in d.data.get("rounds", []) if r["kind"] == "new"
                   for item in r["items"] if item["entry_id"] in catalog and item["entry_id"] not in learnt]))
            completed = list(dict.fromkeys(c.entry_id for c in sorted(cards,
                key=lambda c: c.data.get("introduced_at", "")) if c.data.get("introduced_on") == day))
            row = next((d for d in days if d.id == key), None)
            if row:
                pool = [i for i in row.data["entry_ids"] if i in catalog]
                if row.data.get("word_order") != order:
                    pool = list(dict.fromkeys(completed + protected))
            else:
                previous = next((d for d in days if d.day < day), None)
                carry = [i for i in (previous.data["entry_ids"] if previous and previous.data.get("word_order") == order else [])
                         if i in catalog and i not in learnt]
                pool = list(dict.fromkeys(completed + protected + carry[:max(0, target - len(completed))]))
            # Raising the target appends to the saved pool. Lowering it hides the
            # excess pending words without erasing completed or in-progress work.
            available = groups.ordered((e for e in catalog.values() if e["senses"] and e["id"] not in learnt
                and e["id"] not in pool), order, f"{user}:{notebook}:{day}")
            pool += [e["id"] for e in available[:max(0, target - len(pool))]]
            if row is None:
                db.add(VocabularyDay(id=key, user_id=user, notebook_id=notebook,
                    day=day, data={"entry_ids": pool, "word_order": order, "created_at": current.isoformat()}, revision=0))
                try:
                    db.commit()
                except IntegrityError:
                    db.rollback()
                    continue
            elif pool != row.data["entry_ids"] or row.data.get("word_order") != order:
                data = {**copy.deepcopy(row.data), "entry_ids": pool, "word_order": order}
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
                "available_new": len(set(catalog) - learnt), "word_order": order,
                "coverage": groups.coverage(catalog, learnt),
                "next_family": groups.family(remaining[0], learnt) if remaining and order == "family" else None,
                "protected_count": len(protected)}
    raise HTTPException(409, "今日计划正在另一页面更新，请重试。")

"""Shared FSRS-6 scheduling for words, questions, flashcards and mnemonic recall.

py-fsrs 6.3.2 (MIT), default weights and 90% desired retention. No fitted
personal memory model is claimed. Legacy due dates survive until due practice.
"""
import copy
import hashlib
from datetime import datetime, timezone

from fsrs import Card, Rating, Scheduler

VERSION = "fsrs-6/py-fsrs-6.3.2/default-v1"
SCHEDULER = Scheduler(desired_retention=0.9, enable_fuzzing=False)
RATINGS = {"again": Rating.Again, "hard": Rating.Hard, "good": Rating.Good, "easy": Rating.Easy}


def schedule(old: dict, active: dict, rating: str, current: datetime, card_key: str):
    """Return serializable state/audit; never mutate prior state or reward help."""
    if rating not in RATINGS:
        raise ValueError("invalid recall rating")
    current = current.replace(tzinfo=timezone.utc) if current.tzinfo is None else current.astimezone(timezone.utc)
    helped = bool(active.get("used_help"))
    passed = rating != "again" and active.get("correct", active.get("mode") != "spelling")
    effective = rating if passed and not helped else "again"
    track = copy.deepcopy(old)
    track["attempts"] = old.get("attempts", 0) + 1
    track["independent_due_reviews"] = old.get("independent_due_reviews", 0) + int(bool(old) and not active["early"] and not helped)
    if active["early"] and old.get("due_at"):
        return track, {"effective_rating": effective, "scheduling_applied": False,
                       "scheduling_reason": "提前练习，保留原复习时间", "fsrs_log": None}
    card = Card.from_dict(old["fsrs"]) if old.get("fsrs") else Card(
        card_id=int(hashlib.sha256(card_key.encode()).hexdigest()[:12], 16), due=current)
    card, log = SCHEDULER.review_card(card, RATINGS[effective], review_datetime=current)
    track.update(scheduler=VERSION, fsrs=card.to_dict(), due_at=card.due.isoformat())
    track.pop("stage", None)
    reason = "借助提示，安排重新学习" if helped else "本次未回忆正确，安排重新学习" if not passed else "按本次回忆与历史记录安排"
    return track, {"effective_rating": effective, "scheduling_applied": True,
                   "scheduling_reason": reason, "fsrs_log": log.to_dict()}

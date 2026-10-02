"""FSRS card scheduling, with explicit boundaries for assisted/early practice.

py-fsrs 6.3.2 (MIT), FSRS-6 default weights; no personal parameter fitting.
Meaning and spelling states are stored separately by the vocabulary service.
"""
import copy
import hashlib
from datetime import datetime

from fsrs import Card, Rating, Scheduler

VERSION = "fsrs-6/py-fsrs-6.3.2/default-v1"
SCHEDULER = Scheduler(desired_retention=0.9, enable_fuzzing=False)
RATINGS = {"again": Rating.Again, "hard": Rating.Hard, "good": Rating.Good, "easy": Rating.Easy}


def schedule(old: dict, active: dict, rating: str, current: datetime, card_key: str):
    """Return a new track and audit metadata without mutating the stored state."""
    helped = bool(active.get("used_help"))
    passed = rating != "again" and (active["mode"] != "spelling" or active.get("correct", False))
    effective = rating if passed and not helped else "again"
    track = copy.deepcopy(old)
    track["attempts"] = old.get("attempts", 0) + 1
    track["independent_due_reviews"] = old.get("independent_due_reviews", 0) + int(bool(old) and not active["early"] and not helped)
    if active["early"] and old.get("due_at"):
        # Extra practice must not repeatedly push away an already planned review.
        return track, {"effective_rating": effective, "scheduling_applied": False, "scheduling_reason": "提前练习，保留原复习时间", "fsrs_log": None}
    card = Card.from_dict(old["fsrs"]) if old.get("fsrs") else Card(
        card_id=int(hashlib.sha256(card_key.encode()).hexdigest()[:12], 16), due=current)
    # Legacy schedules stay intact until their next due review. Missing model state
    # starts conservatively as a new card; no invented historical memory strength.
    card, log = SCHEDULER.review_card(card, RATINGS[effective], review_datetime=current)
    track.update(scheduler=VERSION, fsrs=card.to_dict(), due_at=card.due.isoformat())
    track.pop("stage", None)
    reason = "借助提示，安排重新学习" if helped else "本次未回忆正确，安排重新学习" if not passed else "按本次回忆与历史记录安排"
    return track, {"effective_rating": effective, "scheduling_applied": True, "scheduling_reason": reason, "fsrs_log": log.to_dict()}

import copy
from datetime import datetime, timedelta, timezone

from app.services.vocabulary_scheduler import schedule, VERSION


def test_fsrs_graduates_and_uses_recall_difficulty():
    now = datetime(2026, 10, 2, 8, tzinfo=timezone.utc)
    active = {"mode": "meaning", "early": False, "used_help": False}
    hard, _ = schedule({}, active, "hard", now, "card:meaning")
    good, _ = schedule({}, active, "good", now, "card:meaning")
    easy, _ = schedule({}, active, "easy", now, "card:meaning")
    assert now < datetime.fromisoformat(hard["due_at"]) < datetime.fromisoformat(good["due_at"]) < datetime.fromisoformat(easy["due_at"])
    assert easy["fsrs"]["state"] == 2 and easy["scheduler"] == VERSION
    due = datetime.fromisoformat(good["due_at"])
    graduated, audit = schedule(good, active, "good", due, "card:meaning")
    assert graduated["fsrs"]["state"] == 2
    assert datetime.fromisoformat(graduated["due_at"]) - due >= timedelta(days=1)
    assert graduated["independent_due_reviews"] == 1
    assert audit["fsrs_log"]["review_datetime"] == due.isoformat()
    assert isinstance(graduated["fsrs"], dict)


def test_assisted_wrong_and_early_practice_cannot_inflate_memory_state():
    now = datetime(2026, 10, 2, 8, tzinfo=timezone.utc)
    active = {"mode": "spelling", "correct": True, "early": False, "used_help": False}
    track, _ = schedule({}, active, "easy", now, "card:spelling")
    previous = copy.deepcopy(track)
    early, audit = schedule(track, {**active, "early": True}, "easy", now + timedelta(minutes=5), "card:spelling")
    assert early["due_at"] == track["due_at"] and early["fsrs"] == track["fsrs"]
    assert audit["scheduling_applied"] is False and early["independent_due_reviews"] == 0
    assert track == previous
    due = datetime.fromisoformat(track["due_at"])
    helped, audit = schedule(track, {**active, "used_help": True}, "easy", due, "card:spelling")
    assert audit["effective_rating"] == "again" and helped["independent_due_reviews"] == 0
    assert datetime.fromisoformat(helped["due_at"]) - due <= timedelta(minutes=10)
    wrong, audit = schedule(track, {**active, "correct": False}, "good", due, "card:spelling")
    assert audit["effective_rating"] == "again" and wrong["fsrs"]["state"] == 3


def test_legacy_due_and_counts_survive_lazy_migration():
    now = datetime(2026, 10, 2, 8, tzinfo=timezone.utc)
    due = now + timedelta(days=3)
    old = {"due_at": due.isoformat(), "stage": 2, "attempts": 5, "independent_due_reviews": 3}
    active = {"mode": "meaning", "early": True, "used_help": False}
    preserved, _ = schedule(old, active, "good", now, "legacy")
    assert preserved["due_at"] == due.isoformat() and "fsrs" not in preserved
    migrated, _ = schedule(preserved, {**active, "early": False}, "good", due, "legacy")
    assert migrated["attempts"] == 7 and migrated["independent_due_reviews"] == 4
    assert migrated["scheduler"] == VERSION and "stage" not in migrated

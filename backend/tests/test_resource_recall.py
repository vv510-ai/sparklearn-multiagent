"""Real persistence, grading, scheduling and ownership for reusable recalls."""
import copy
import datetime as dt
import uuid

import pytest

from app.models.db import session
from app.models.entities import Resource, ReviewItem
from app.services import recall_service
from app.services.review_scheduler import VERSION
from tests.test_learning_spaces import learner, prepare  # noqa: F401


def seed(client, user, kind="flashcards"):
    book, _, course = prepare(client, user)
    rid = "recall-test-" + uuid.uuid4().hex[:20]
    payload = {"notebook_id": book["id"], "course_revision": course["revision"]}
    if kind == "flashcards":
        payload["flashcards"] = {"cards": [{"id": str(i), "front": f"第{i + 1}张：变量赋值的含义？",
            "back": "把名字与对象关联", "hint": "回想名字与值的关系"} for i in range(4)]}
    else:
        payload["song"] = {"cloze": [{"line": "变量名字绑定对象", "answer": "对象"},
            {"line": "重新赋值改变绑定", "answer": "绑定"}], "mnemonic": [{"line": "名字绑定对象", "meaning": "变量关联对象"}]}
    with session() as db:
        db.add(Resource(id=rid, user_id=user, kind=kind, kp="py_variables", title="回忆验收", payload=payload))
        db.commit()
    return book, rid


def get(client, user, rid):
    response = client.get(f"/api/eval/recall/{rid}", params={"user_id": user})
    assert response.status_code == 200, response.text
    return response.json()


def submit(client, user, rid, card, rating="good", **extra):
    body = {"user_id": user, "card_key": card["key"], "revision": card["revision"],
            "rating": rating, "request_id": uuid.uuid4().hex, **extra}
    response = client.post(f"/api/eval/recall/{rid}", json=body)
    assert response.status_code == 200, response.text
    return response.json(), body


def test_flashcards_four_ratings_persist_and_join_same_course_queue(learner):
    client, user = learner
    book, rid = seed(client, user)
    assert get(client, user, rid)["registered"] == 0
    enrolled = client.post(f"/api/eval/recall/{rid}/enroll", json={"user_id": user})
    assert enrolled.status_code == 200, enrolled.text
    assert client.post(f"/api/eval/recall/{rid}/enroll", json={"user_id": user}).json()["registered"] == 4
    queue = client.get("/api/eval/review-queue", params={"user_id": user, "notebook_id": book["id"]}).json()
    assert queue["recall"]["due"] == 4 and queue["items"] == []
    assert "back" not in str(queue["recall"])
    due = []
    for card, rating in zip(enrolled.json()["items"], ["again", "hard", "good", "easy"]):
        result, body = submit(client, user, rid, card, rating)
        assert result["scheduler"] == VERSION and result["effective_rating"] == rating
        assert result["evidence"] == "self_reported"
        assert client.post(f"/api/eval/recall/{rid}", json=body).json() == result
        stale = client.post(f"/api/eval/recall/{rid}", json={**body, "request_id": uuid.uuid4().hex})
        assert stale.status_code == 409
        due.append(dt.datetime.fromisoformat(result["due_at"]))
    assert due == sorted(due) and len(set(due)) == 4
    loaded = get(client, user, rid)
    assert all(card["attempts"] == 1 and card["revision"] == 1 for card in loaded["items"])
    with session() as db:
        rows = db.query(ReviewItem).filter(ReviewItem.quiz_resource_id == rid).all()
        assert len(rows) == 4 and all(isinstance(row.data["schedule"]["fsrs"], dict) for row in rows)
    assert client.get("/api/eval/mistake-book", params={"user_id": user, "notebook_id": book["id"]}).json()["items"] == []


def test_mnemonic_server_checks_answer_and_does_not_count_help_as_easy(learner, monkeypatch):
    client, user = learner
    _, rid = seed(client, user, "song")
    current = dt.datetime.now(dt.timezone.utc)
    monkeypatch.setattr(recall_service, "utc_now", lambda: current)
    enrolled = client.post(f"/api/eval/recall/{rid}/enroll", json={"user_id": user}).json()
    first, second = enrolled["items"]
    assert "back" not in first and "____" in first["front"]
    wrong, _ = submit(client, user, rid, first, "easy", answer="错误答案")
    assert not wrong["correct"] and wrong["effective_rating"] == "again"
    assert dt.datetime.fromisoformat(wrong["due_at"]) - current <= dt.timedelta(minutes=10)
    helped, _ = submit(client, user, rid, second, "easy", answer="绑定", used_help=True)
    assert helped["correct"] and helped["effective_rating"] == "again"
    with session() as db:
        row = db.query(ReviewItem).filter(ReviewItem.quiz_resource_id == rid, ReviewItem.question_id == second["key"]).one()
        assert row.data["schedule"]["independent_due_reviews"] == 0
        assert row.last_correct == 0


def test_early_recall_preserves_due_and_memory_state(learner):
    client, user = learner
    _, rid = seed(client, user)
    cards = client.post(f"/api/eval/recall/{rid}/enroll", json={"user_id": user}).json()["items"]
    first, _ = submit(client, user, rid, cards[0], "easy")
    with session() as db:
        row = db.query(ReviewItem).filter(ReviewItem.quiz_resource_id == rid, ReviewItem.question_id == cards[0]["key"]).one()
        before = copy.deepcopy(row.data["schedule"])
    current = get(client, user, rid)["items"][0]
    again, _ = submit(client, user, rid, current, "easy")
    assert not again["scheduling_applied"] and again["due_at"] == first["due_at"]
    with session() as db:
        after = db.get(ReviewItem, row.id).data["schedule"]
        assert after["fsrs"] == before["fsrs"]
        assert after["attempts"] == 2 and after["independent_due_reviews"] == before["independent_due_reviews"]


def test_recall_does_not_cross_notebooks_or_owners(learner):
    client, user = learner
    first_book, rid = seed(client, user)
    second_book, _ = seed(client, user)
    client.post(f"/api/eval/recall/{rid}/enroll", json={"user_id": user})
    queue = client.get("/api/eval/review-queue", params={"user_id": user, "notebook_id": second_book["id"]}).json()
    assert queue["recall"]["due"] == 0 and queue["recall"]["items"] == []
    assert client.get(f"/api/eval/recall/{rid}", params={"user_id": "another-owner"}).status_code in {403, 404}
    with session() as db:
        rows = db.query(ReviewItem).filter(ReviewItem.quiz_resource_id == rid).all()
        assert len(rows) == 4 and all(row.user_id == user for row in rows)


def test_changed_retry_payload_cannot_replace_saved_recall(learner):
    client, user = learner
    _, rid = seed(client, user)
    card = client.post(f"/api/eval/recall/{rid}/enroll", json={"user_id": user}).json()["items"][0]
    first, body = submit(client, user, rid, card, "hard")
    changed = client.post(f"/api/eval/recall/{rid}", json={**body, "rating": "easy"})
    assert changed.status_code == 409
    after = get(client, user, rid)["items"][0]
    assert after["revision"] == 1 and after["due_at"] == first["due_at"]


def test_legacy_resource_without_notebook_rejects_impersonation(learner):
    client, user = learner
    _, rid = seed(client, user)
    with session() as db:
        resource = db.get(Resource, rid)
        resource.payload = {"flashcards": resource.payload["flashcards"]}
        db.commit()
    card = client.post(f"/api/eval/recall/{rid}/enroll", json={"user_id": user}).json()["items"][0]
    logged_in = client.post("/api/auth/register", json={"email": f"other-{uuid.uuid4().hex}@example.test",
        "password": "Recall-Other-20261017!", "name": "另一账号"})
    assert logged_in.status_code == 201
    client.headers["Authorization"] = f"Bearer {logged_in.json()['access_token']}"
    assert client.get(f"/api/eval/recall/{rid}", params={"user_id": user}).status_code == 403
    assert client.post(f"/api/eval/recall/{rid}/enroll", json={"user_id": user}).status_code == 403
    assert client.post(f"/api/eval/recall/{rid}", json={"user_id": user, "card_key": card["key"],
        "revision": 0, "rating": "easy", "request_id": uuid.uuid4().hex}).status_code == 403
    with session() as db:
        row = db.query(ReviewItem).filter(ReviewItem.quiz_resource_id == rid, ReviewItem.question_id == card["key"]).one()
        assert row.data["revision"] == 0

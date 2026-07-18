"""Contracts for the durable 1/3/7/14/30-day review queue."""
from __future__ import annotations

import datetime as dt
import os
import sys

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tests._stubs import install  # noqa: E402

install()

from app.main import app  # noqa: E402
from app.models.db import init_db, session  # noqa: E402
from app.models.entities import Resource, ReviewItem  # noqa: E402
from app.services.profile_service import ensure_user  # noqa: E402


USER_ID = "spaced_review_contract_user"
QUIZ_ID = "spaced_review_contract_quiz"
QUESTION = {
    "id": "q-review-1",
    "type": "single",
    "stem": "二叉搜索树的中序遍历结果是什么顺序？",
    "options": ["A. 随机", "B. 升序", "C. 降序", "D. 层序"],
    "answer": "B",
    "kp": "binary_tree",
    "difficulty": 2,
    "explain": "二叉搜索树满足左子树小于根、右子树大于根。",
    "error_tags": ["遍历性质混淆"],
}


def _seed() -> None:
    init_db()
    ensure_user(USER_ID)
    with session() as db:
        db.query(ReviewItem).filter(ReviewItem.user_id == USER_ID).delete()
        db.merge(Resource(
            id=QUIZ_ID,
            user_id=USER_ID,
            kind="quiz",
            kp="binary_tree",
            title="Spaced review contract quiz",
            payload={"questions": [QUESTION]},
            citations=[],
            safety={},
        ))
        db.commit()


def _make_due(review_item_id: int) -> None:
    with session() as db:
        row = db.get(ReviewItem, review_item_id)
        assert row is not None
        row.due_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=1)
        db.commit()


def test_review_queue_hides_answers_and_advances_or_resets_intervals():
    _seed()
    with TestClient(app) as client:
        submitted = client.post("/api/eval/submit", json={
            "user_id": USER_ID,
            "quiz_resource_id": QUIZ_ID,
            "kp": "binary_tree",
            "answers": [{
                "question_id": QUESTION["id"],
                "answer": "A",
                "correct": True,
            }],
        })
        assert submitted.status_code == 200, submitted.text
        assert submitted.json()["review"]["scheduled"] == 1

        queue_response = client.get("/api/eval/review-queue", params={"user_id": USER_ID})
        assert queue_response.status_code == 200, queue_response.text
        queue = queue_response.json()
        assert queue["summary"]["due"] == 1
        assert queue["summary"]["interval_days"] == [1, 3, 7, 14, 30]
        item = queue["items"][0]
        assert item["reason"] == "遍历性质混淆"
        assert "answer" not in item["question"]
        assert "explain" not in item["question"]

        first_review = client.post("/api/eval/review", json={
            "user_id": USER_ID,
            "items": [{
                "review_item_id": item["id"], "answer": "B", "seconds": 5,
                "confidence": "unsure",
            }],
        })
        assert first_review.status_code == 200, first_review.text
        first_report = first_review.json()
        first_schedule = first_report["review"]["schedule"][0]
        assert first_report["items"][0]["evidence_phase"] == "spaced_review"
        assert first_report["items"][0]["confidence"] == "unsure"
        assert first_report["items"][0]["calibration_signal"] == "uncertain_correct"
        assert first_report["calibration"]["recorded"] == 1
        assert first_schedule["correct"] is True
        assert first_schedule["stage"] == 1
        assert first_schedule["interval_days"] == 1

        future_queue = client.get("/api/eval/review-queue", params={"user_id": USER_ID}).json()
        assert future_queue["summary"]["due"] == 0
        assert future_queue["summary"]["upcoming"] == 1
        assert future_queue["summary"]["next_due_at"]

        too_early = client.post("/api/eval/review", json={
            "user_id": USER_ID,
            "items": [{"review_item_id": item["id"], "answer": "B"}],
        })
        assert too_early.status_code == 400

        _make_due(item["id"])
        second_review = client.post("/api/eval/review", json={
            "user_id": USER_ID,
            "items": [{"review_item_id": item["id"], "answer": "B"}],
        })
        assert second_review.status_code == 200, second_review.text
        second_schedule = second_review.json()["review"]["schedule"][0]
        assert second_schedule["stage"] == 2
        assert second_schedule["interval_days"] == 3

        _make_due(item["id"])
        lapsed = client.post("/api/eval/review", json={
            "user_id": USER_ID,
            "items": [{"review_item_id": item["id"], "answer": "A"}],
        })
        assert lapsed.status_code == 200, lapsed.text
        lapsed_schedule = lapsed.json()["review"]["schedule"][0]
        assert lapsed_schedule["correct"] is False
        assert lapsed_schedule["stage"] == 0
        assert lapsed_schedule["interval_days"] == 1
        assert lapsed_schedule["lapse_count"] == 1

    with session() as db:
        row = db.get(ReviewItem, item["id"])
        assert row is not None
        phases = [event["phase"] for event in row.data["history"]]
        assert phases[-3:] == ["spaced_review", "spaced_review", "spaced_review"]


def test_mistake_book_keeps_history_favorites_and_immediate_practice():
    _seed()
    with TestClient(app) as client:
        submitted = client.post("/api/eval/submit", json={
            "user_id": USER_ID,
            "quiz_resource_id": QUIZ_ID,
            "kp": "binary_tree",
            "answers": [{
                "question_id": QUESTION["id"],
                "answer": "A",
                "correct": False,
                "confidence": "confident",
            }],
        })
        assert submitted.status_code == 200, submitted.text

        book = client.get("/api/eval/mistake-book", params={"user_id": USER_ID})
        assert book.status_code == 200, book.text
        payload = book.json()
        assert payload["summary"] == {"total": 1, "pending": 1, "resolved": 0, "favorite": 0}
        item = payload["items"][0]
        assert item["last_answer"] == "A"
        assert item["expected"] == "B"
        assert item["reason"] == "遍历性质混淆"

        favorite = client.post(f"/api/eval/mistake-book/{item['id']}/favorite", json={
            "user_id": USER_ID,
            "favorite": True,
        })
        assert favorite.status_code == 200, favorite.text
        assert favorite.json()["favorite"] is True

        practiced = client.post(f"/api/eval/mistake-book/{item['id']}/practice", json={
            "user_id": USER_ID,
            "answer": "B",
            "seconds": 8,
            "confidence": "unsure",
        })
        assert practiced.status_code == 200, practiced.text
        practice_payload = practiced.json()
        assert practice_payload["correct"] is True
        assert practice_payload["schedule"]["interval_days"] == 1
        assert practice_payload["report"]["items"][0]["evidence_phase"] == "spaced_review"

        refreshed = client.get("/api/eval/mistake-book", params={"user_id": USER_ID}).json()
        assert refreshed["summary"] == {"total": 1, "pending": 0, "resolved": 1, "favorite": 1}
        assert refreshed["items"][0]["favorite"] is True

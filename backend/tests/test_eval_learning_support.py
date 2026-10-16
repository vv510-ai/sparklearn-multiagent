"""Contracts for the attempt -> hint/reveal -> reflection learning loop."""
from __future__ import annotations

import os
import sys

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tests._stubs import install  # noqa: E402

install()

from app.main import app  # noqa: E402
from app.models.db import init_db, session  # noqa: E402
from app.models.entities import EventLog, Profile, QuizAttempt, Resource, ReviewItem  # noqa: E402
from app.services.profile_service import ensure_user  # noqa: E402


USER_ID = "hitl_learning_contract_user"
QUIZ_ID = "hitl_learning_contract_quiz"
QUESTION = {
    "id": "q-hitl-1",
    "type": "single",
    "stem": "层序遍历通常借助哪种数据结构？",
    "options": ["A. 栈", "B. 队列", "C. 集合", "D. 哈希表"],
    "answer": "B",
    "kp": "binary_tree",
    "difficulty": 1,
    "explain": "层序遍历按先进先出的顺序访问待处理节点。",
    "error_tags": ["遍历结构混淆"],
}


def _seed_quiz() -> None:
    init_db()
    ensure_user(USER_ID)
    with session() as db:
        db.query(ReviewItem).filter(ReviewItem.user_id == USER_ID).delete()
        db.query(QuizAttempt).filter(QuizAttempt.user_id == USER_ID).delete()
        db.query(EventLog).filter(EventLog.user_id == USER_ID).delete()
        db.query(Profile).filter(Profile.user_id == USER_ID).delete()
        db.merge(Resource(
            id=QUIZ_ID,
            user_id=USER_ID,
            kind="quiz",
            kp="binary_tree",
            title="Human-in-the-loop contract quiz",
            payload={"questions": [QUESTION]},
            citations=[],
            safety={},
        ))
        db.commit()


def test_support_requires_attempt_and_hint_does_not_reveal_answer():
    _seed_quiz()
    with TestClient(app) as client:
        rejected = client.post("/api/eval/support", json={
            "user_id": USER_ID,
            "quiz_resource_id": QUIZ_ID,
            "question_id": QUESTION["id"],
            "mode": "reveal",
            "attempt": "",
        })
        assert rejected.status_code == 400

        hinted = client.post("/api/eval/support", json={
            "user_id": USER_ID,
            "quiz_resource_id": QUIZ_ID,
            "question_id": QUESTION["id"],
            "mode": "hint",
            "attempt": "A",
        })
        assert hinted.status_code == 200, hinted.text
        hint = hinted.json()
        assert hint["mode"] == "hint"
        assert hint["hint"]
        assert "expected" not in hint
        assert "队列" not in hint["hint"]


def test_reveal_is_preserved_as_non_independent_mastery_evidence():
    _seed_quiz()
    with TestClient(app) as client:
        revealed = client.post("/api/eval/support", json={
            "user_id": USER_ID,
            "quiz_resource_id": QUIZ_ID,
            "question_id": QUESTION["id"],
            "mode": "reveal",
            "attempt": "B",
        })
        assert revealed.status_code == 200, revealed.text
        assert revealed.json()["expected"] == "B"

        missing_reflection = client.post("/api/eval/submit", json={
            "user_id": USER_ID,
            "quiz_resource_id": QUIZ_ID,
            "kp": "binary_tree",
            "answers": [{
                "question_id": QUESTION["id"],
                "answer": "B",
                "correct": True,
                "revealed": True,
                "misconception": "",
            }],
        })
        assert missing_reflection.status_code == 400

        submitted = client.post("/api/eval/submit", json={
            "user_id": USER_ID,
            "quiz_resource_id": QUIZ_ID,
            "kp": "binary_tree",
            "answers": [{
                "question_id": QUESTION["id"],
                "answer": "B",
                "correct": False,
                "seconds": 9,
                "hint_used": False,
                "revealed": True,
                "misconception": "条件看漏了",
            }],
            "behavior": {"surface": "quiz_player"},
        })
        assert submitted.status_code == 200, submitted.text
        report = submitted.json()

        incomplete = client.post("/api/eval/retest", json={
            "user_id": USER_ID,
            "quiz_resource_id": QUIZ_ID,
            "attempt_id": report["attempt_id"],
            "answers": [],
        })
        assert incomplete.status_code == 400

        retested = client.post("/api/eval/retest", json={
            "user_id": USER_ID,
            "quiz_resource_id": QUIZ_ID,
            "attempt_id": report["attempt_id"],
            "answers": [{
                "question_id": QUESTION["id"],
                "answer": "B",
                "seconds": 6,
                "confidence": "confident",
            }],
        })
        assert retested.status_code == 200, retested.text
        retest_report = retested.json()

        duplicate = client.post("/api/eval/retest", json={
            "user_id": USER_ID,
            "quiz_resource_id": QUIZ_ID,
            "attempt_id": report["attempt_id"],
            "answers": [{
                "question_id": QUESTION["id"],
                "answer": "B",
            }],
        })
        assert duplicate.status_code == 409

    assert report["accuracy"] == 1.0  # backend grading ignores client `correct`
    assert report["behavior"]["support"] == {
        "hinted": 0,
        "revealed": 1,
        "independent": 0,
        "misconceptions": ["条件看漏了"],
    }
    item = report["items"][0]
    assert item["correct"] is True
    assert item["mastery_correct"] is False
    assert item["support_level"] == "revealed"
    assert item["misconception"] == "条件看漏了"
    assert "条件看漏了" in item["error_tags"]
    assert report["per_kp"][0]["right"] == 1
    assert report["per_kp"][0]["mastery_right"] == 0
    assert report["review"]["scheduled"] == 1
    assert report["retest"] == {
        "status": "ready",
        "eligible_question_ids": [QUESTION["id"]],
    }

    assert retest_report["retest"] == {
        "status": "completed",
        "eligible": 1,
        "recovered": 1,
        "remaining": 0,
    }
    assert retest_report["accuracy"] == 1.0
    assert retest_report["items"][0]["mastery_correct"] is True
    assert retest_report["items"][0]["support_level"] == "independent"
    assert retest_report["items"][0]["evidence_phase"] == "retest"
    assert retest_report["items"][0]["confidence"] == "confident"
    assert retest_report["items"][0]["calibration_signal"] == "confident_correct"
    assert retest_report["calibration"]["recorded"] == 1
    assert retest_report["per_kp"][0]["mastery"] > report["per_kp"][0]["mastery"]
    assert retest_report["review"]["schedule"][0]["stage"] == 1
    assert retest_report["review"]["schedule"][0]["scheduler"].startswith("fsrs-6/")
    assert retest_report["review"]["schedule"][0]["interval_days"] > 0
    with session() as db:
        persisted = db.get(QuizAttempt, report["attempt_id"])
        assert persisted is not None
        assert persisted.detail["retest"]["summary"]["recovered"] == 1


def test_independent_correct_answer_does_not_offer_retest():
    _seed_quiz()
    with TestClient(app) as client:
        submitted = client.post("/api/eval/submit", json={
            "user_id": USER_ID,
            "quiz_resource_id": QUIZ_ID,
            "kp": "binary_tree",
            "answers": [{
                "question_id": QUESTION["id"],
                "answer": "B",
                "correct": False,
            }],
        })
        assert submitted.status_code == 200, submitted.text
        report = submitted.json()
        assert report["retest"] == {
            "status": "not_needed",
            "eligible_question_ids": [],
        }
        assert report["review"]["scheduled"] == 0

        retested = client.post("/api/eval/retest", json={
            "user_id": USER_ID,
            "quiz_resource_id": QUIZ_ID,
            "attempt_id": report["attempt_id"],
            "answers": [],
        })
        assert retested.status_code == 400

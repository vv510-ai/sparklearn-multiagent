"""Contracts for confidence capture and metacognitive calibration."""
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
from app.services.metacognition_service import summarize_calibration  # noqa: E402
from app.services.profile_service import ensure_user  # noqa: E402


USER_ID = "metacognition_contract_user"
QUIZ_ID = "metacognition_contract_quiz"
QUESTION = {
    "id": "q-confidence-1",
    "type": "single",
    "stem": "二叉搜索树的中序遍历结果通常是什么顺序？",
    "options": ["A. 随机", "B. 升序", "C. 降序", "D. 层序"],
    "answer": "B",
    "kp": "binary_tree",
    "difficulty": 2,
    "explain": "中序遍历会按键值升序访问二叉搜索树。",
    "error_tags": ["遍历性质混淆"],
}


def _seed() -> None:
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
            title="Metacognition contract quiz",
            payload={"questions": [QUESTION]},
            citations=[],
            safety={},
        ))
        db.commit()


def test_confident_wrong_answer_updates_profile_and_evidence():
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
                "confidence": "confident",
            }],
        })
        profile = client.get(f"/api/profile/{USER_ID}")
        evidence = client.get("/api/eval/evidence", params={"user_id": USER_ID})

    assert submitted.status_code == 200, submitted.text
    report = submitted.json()
    assert report["items"][0]["correct"] is False
    assert report["items"][0]["confidence"] == "confident"
    assert report["items"][0]["calibration_signal"] == "confident_wrong"
    assert report["calibration"] == {
        "recorded": 1,
        "score": 0.1,
        "confident_wrong": 1,
        "uncertain_correct": 0,
        "confident_correct": 0,
        "uncertainty_matched": 0,
        "metacognition_before": 0.5,
        "metacognition_after": 0.4,
    }
    assert profile.status_code == 200
    assert profile.json()["metacognition"] == 0.4

    assert evidence.status_code == 200
    evidence_body = evidence.json()
    assert evidence_body["summary"]["confidence_recorded"] == 1
    assert evidence_body["summary"]["confident_wrong"] == 1
    assert evidence_body["summary"]["calibration_score"] == 0.1
    assert evidence_body["items"][0]["calibration"]["metacognition_after"] == 0.4


def test_calibration_distinguishes_underconfidence_and_rejects_unknown_level():
    summary = summarize_calibration([
        {"answer": "B", "correct": True, "confidence": "unsure"},
        {"answer": "A", "correct": False, "confidence": "guess"},
        {"answer": "", "correct": False, "confidence": "confident"},
        {"answer": "A", "correct": False, "confidence": "confident", "support_level": "hinted"},
    ])
    assert summary == {
        "recorded": 2,
        "score": 0.65,
        "confident_wrong": 0,
        "uncertain_correct": 1,
        "confident_correct": 0,
        "uncertainty_matched": 1,
    }

    _seed()
    with TestClient(app) as client:
        rejected = client.post("/api/eval/submit", json={
            "user_id": USER_ID,
            "quiz_resource_id": QUIZ_ID,
            "answers": [{
                "question_id": QUESTION["id"],
                "answer": "B",
                "correct": True,
                "confidence": "certain-ish",
            }],
        })
    assert rejected.status_code == 422

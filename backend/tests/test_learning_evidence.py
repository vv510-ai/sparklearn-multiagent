"""Contracts for the explainable learning-evidence ledger."""
from __future__ import annotations

import os
import sys

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tests._stubs import install  # noqa: E402

install()

from app.main import app  # noqa: E402
from app.models.db import init_db, session  # noqa: E402
from app.models.entities import EventLog  # noqa: E402
from app.services.profile_service import ensure_user  # noqa: E402


USER_ID = "learning_evidence_contract_user"


def _seed_events() -> None:
    init_db()
    ensure_user(USER_ID)
    with session() as db:
        db.query(EventLog).filter(EventLog.user_id == USER_ID).delete()
        db.add_all([
            EventLog(user_id=USER_ID, etype="quiz_eval", payload={
                "per_kp": {
                    "binary_tree": {
                        "kp": "binary_tree", "name": "二叉树", "n": 2,
                        "right": 2, "mastery_right": 1, "supported": 1,
                        "confidence_recorded": 2, "confident_wrong": 1,
                        "uncertain_correct": 1,
                        "mastery": 0.42, "level": "学习中",
                    },
                },
                "errors": {"条件看漏了": 1},
                "calibration": {
                    "recorded": 2, "score": 0.4, "confident_wrong": 1,
                    "uncertain_correct": 1, "metacognition_before": 0.5,
                    "metacognition_after": 0.475,
                },
                "evidence_phases": ["initial"],
            }),
            EventLog(user_id=USER_ID, etype="quiz_eval", payload={
                "per_kp": {
                    "binary_tree": {
                        "kp": "binary_tree", "name": "二叉树", "n": 1,
                        "right": 1, "mastery_right": 1, "supported": 0,
                        "confidence_recorded": 1, "confident_wrong": 0,
                        "uncertain_correct": 0,
                        "mastery": 0.66, "level": "学习中",
                    },
                },
                "errors": {},
                "calibration": {
                    "recorded": 1, "score": 0.9, "confident_wrong": 0,
                    "uncertain_correct": 0, "metacognition_before": 0.475,
                    "metacognition_after": 0.5813,
                },
                "evidence_phases": ["retest"],
            }),
            EventLog(user_id=USER_ID, etype="quiz_eval", payload={
                "per_kp": {
                    "binary_tree": {
                        "kp": "binary_tree", "name": "二叉树", "n": 1,
                        "right": 0, "mastery_right": 0, "supported": 0,
                        "mastery": 0.51, "level": "学习中",
                    },
                },
                "errors": {"遍历性质混淆": 1},
                "evidence_phases": ["spaced_review"],
            }),
            EventLog(user_id=USER_ID, etype="ask", payload={"text": "not evidence"}),
        ])
        db.commit()


def test_evidence_reconstructs_mastery_changes_and_support_gap():
    _seed_events()
    with TestClient(app) as client:
        response = client.get("/api/eval/evidence", params={"user_id": USER_ID, "limit": 2})

    assert response.status_code == 200, response.text
    body = response.json()
    assert [item["phase"] for item in body["items"]] == ["spaced_review", "retest"]
    assert body["summary"] == {
        "rounds": 3,
        "answers": 4,
        "raw_correct": 3,
        "mastery_correct": 2,
        "supported": 1,
        "independent": 3,
        "confidence_recorded": 3,
        "confident_wrong": 1,
        "uncertain_correct": 1,
        "calibration_score": 0.567,
        "by_phase": {"initial": 1, "retest": 1, "spaced_review": 1},
    }

    latest = body["items"][0]
    point = latest["knowledge_points"][0]
    assert point["mastery_before"] == 0.66
    assert point["mastery_after"] == 0.51
    assert point["mastery_delta"] == -0.15
    assert latest["errors"] == {"遍历性质混淆": 1}

    retest = body["items"][1]
    assert retest["knowledge_points"][0]["mastery_before"] == 0.42
    assert retest["calibration"]["score"] == 0.9
    assert all("answer" not in item and "expected" not in item for item in body["items"])
    assert all(
        "answer" not in point and "expected" not in point
        for item in body["items"] for point in item["knowledge_points"]
    )


def test_evidence_empty_state_and_limit_validation():
    empty_user = f"{USER_ID}_empty"
    init_db()
    with TestClient(app) as client:
        response = client.get("/api/eval/evidence", params={"user_id": empty_user})
        rejected = client.get("/api/eval/evidence", params={"user_id": empty_user, "limit": 0})

    assert response.status_code == 200
    assert response.json()["items"] == []
    assert response.json()["summary"]["rounds"] == 0
    assert rejected.status_code == 422


def test_legacy_evidence_uses_historical_bkt_rule():
    legacy_user = f"{USER_ID}_legacy"
    init_db()
    ensure_user(legacy_user)
    with session() as db:
        db.query(EventLog).filter(EventLog.user_id == legacy_user).delete()
        db.add(EventLog(user_id=legacy_user, etype="quiz_eval", payload={
            "per_kp": {
                "binary_tree": {
                    "kp": "binary_tree", "n": 2, "right": 1,
                    "mastery": 0.37, "level": "学习中",
                },
            },
            "errors": {},
        }))
        db.commit()

    with TestClient(app) as client:
        response = client.get("/api/eval/evidence", params={"user_id": legacy_user})

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["phase"] == "initial"
    assert item["raw_correct"] == 1
    assert item["mastery_correct"] == 1
    assert item["supported"] == 0
    assert item["knowledge_points"][0]["name"] == "二叉树"

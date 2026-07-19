from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.models.db import session
from app.models.entities import (
    AuthAccount,
    DemoBaseline,
    EventLog,
    PathPlan,
    PersonalizationDecision,
    Profile,
    QuizAttempt,
    Resource,
    ReviewItem,
    User,
)


def _enable_real_auth(monkeypatch) -> None:
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    monkeypatch.setenv("AUTH_SECRET", "test-only-auth-secret-with-at-least-32-characters")
    config.get_settings.cache_clear()


def _submission(resource: dict, values: list[str], user_id: str) -> dict:
    questions = resource["payload"]["questions"]
    assert len(questions) == len(values) == 5
    return {
        "user_id": user_id,
        "quiz_resource_id": resource["id"],
        "kp": resource["kp"],
        "answers": [
            {
                "question_id": question["id"],
                "answer": answer,
                "correct": False,
                "seconds": 3,
                "confidence": "confident",
            }
            for question, answer in zip(questions, values, strict=True)
        ],
    }


def _delete_user(user_id: str) -> None:
    with session() as db:
        for model in (
            ReviewItem,
            QuizAttempt,
            EventLog,
            PersonalizationDecision,
            DemoBaseline,
            Resource,
            PathPlan,
            Profile,
            AuthAccount,
        ):
            db.query(model).filter(model.user_id == user_id).delete(synchronize_session=False)
        user = db.get(User, user_id)
        if user:
            db.delete(user)
        db.commit()


def test_fixed_final_review_sets_are_guarded_and_restore_cleanly(monkeypatch):
    _enable_real_auth(monkeypatch)
    marker = uuid.uuid4().hex
    user_id = ""
    try:
        with TestClient(app) as client:
            registered = client.post(
                "/api/auth/register",
                json={
                    "email": f"final-review-{marker}@example.com",
                    "password": "correct-horse",
                    "name": "终审演示账号",
                },
            )
            assert registered.status_code == 201, registered.text
            user_id = registered.json()["user"]["id"]
            headers = {"Authorization": f"Bearer {registered.json()['access_token']}"}

            unprepared = client.get("/api/demo/final-review", headers=headers)
            assert unprepared.status_code == 200
            assert unprepared.json()["ready"] is False
            assert unprepared.json()["checks"] == {
                "account": True,
                "quiz_sets": False,
                "baseline": False,
                "answer_order": True,
            }

            prepared = client.post("/api/demo/final-review/prepare", json={}, headers=headers)
            assert prepared.status_code == 200, prepared.text
            state = prepared.json()
            assert state["ready"] is True
            assert state["completed_set_ids"] == []
            assert [item["id"] for item in state["sets"]] == [
                "final-binary-tree-v1",
                "final-sorting-adv-v1",
            ]
            assert [item["question_count"] for item in state["sets"]] == [5, 5]
            assert state["sets"][0]["operator_answers"] == ["B", "DEBCA", "B", "A", "错"]
            assert state["sets"][1]["operator_answers"] == [
                "A", "错", "时间 O(n^2)；空间 O(1)", "B", "B",
            ]

            tree = state["sets"][0]["resource"]
            sorting = state["sets"][1]["resource"]
            assert [question["id"] for question in tree["payload"]["questions"]] == [
                "q015", "q016", "q039", "q040", "q041",
            ]
            assert [question["id"] for question in sorting["payload"]["questions"]] == [
                "q012", "q013", "q014", "q048", "q049",
            ]

            baseline_profile = client.get(f"/api/profile/{user_id}", headers=headers).json()

            # Correct target pattern is still rejected when the second group is attempted first.
            too_early = client.post(
                "/api/eval/submit",
                json=_submission(sorting, ["A", "错", "时间 O(n^2)；空间 O(1)", "B", "B"], user_id),
                headers=headers,
            )
            assert too_early.status_code == 409
            assert "先完成二叉树" in too_early.json()["detail"]

            # A wrong tree pattern is rejected before attempts/profile/path are mutated.
            wrong_tree = client.post(
                "/api/eval/submit",
                json=_submission(tree, ["A", "DEBCA", "B", "A", "错"], user_id),
                headers=headers,
            )
            assert wrong_tree.status_code == 409
            assert "本次未写入画像" in wrong_tree.json()["detail"]
            with session() as db:
                assert db.query(QuizAttempt).filter(QuizAttempt.user_id == user_id).count() == 0

            tree_result = client.post(
                "/api/eval/submit",
                json=_submission(tree, ["B", "DEBCA", "B", "A", "错"], user_id),
                headers=headers,
            )
            assert tree_result.status_code == 200, tree_result.text
            assert tree_result.json()["accuracy"] == 1.0

            sorting_result = client.post(
                "/api/eval/submit",
                json=_submission(sorting, ["A", "错", "时间 O(n^2)；空间 O(1)", "B", "B"], user_id),
                headers=headers,
            )
            assert sorting_result.status_code == 200, sorting_result.text
            assert sorting_result.json()["accuracy"] == 0.2

            completed = client.get("/api/demo/final-review", headers=headers).json()
            assert completed["completed_set_ids"] == [
                "final-binary-tree-v1", "final-sorting-adv-v1",
            ]
            assert completed["next_set_id"] == ""
            with session() as db:
                assert db.query(QuizAttempt).filter(QuizAttempt.user_id == user_id).count() == 2
                assert db.query(ReviewItem).filter(ReviewItem.user_id == user_id).count() == 4
                assert db.get(PathPlan, user_id) is not None

            restored = client.post("/api/demo/final-review/restore", json={}, headers=headers)
            assert restored.status_code == 200, restored.text
            assert restored.json()["completed_set_ids"] == []
            assert restored.json()["next_set_id"] == "final-binary-tree-v1"

            after_profile = client.get(f"/api/profile/{user_id}", headers=headers).json()
            assert {key: value for key, value in after_profile.items() if not key.startswith("_")} == {
                key: value for key, value in baseline_profile.items() if not key.startswith("_")
            }
            assert after_profile["_version"] == baseline_profile["_version"]
            with session() as db:
                assert db.query(QuizAttempt).filter(QuizAttempt.user_id == user_id).count() == 0
                assert db.query(ReviewItem).filter(ReviewItem.user_id == user_id).count() == 0
                assert db.get(PathPlan, user_id) is None
                assert db.get(DemoBaseline, user_id) is not None
    finally:
        if user_id:
            _delete_user(user_id)
        config.get_settings.cache_clear()

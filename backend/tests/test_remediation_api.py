"""API contract for diagnosis -> source-grounded micro-lesson -> retest."""
from __future__ import annotations

import os
import sys

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tests._stubs import install  # noqa: E402

install()

from app.api import evaluate as evaluate_api  # noqa: E402
from app.main import app  # noqa: E402
from app.models.db import init_db, session  # noqa: E402
from app.models.entities import EventLog, Profile, QuizAttempt, Resource, ReviewItem  # noqa: E402
from app.services.profile_service import ensure_user  # noqa: E402


USER_ID = "remediation_contract_user"
QUIZ_ID = "remediation_contract_quiz"
SUBMIT_USER_ID = "remediation_submit_contract_user"
SUBMIT_QUIZ_ID = "remediation_submit_contract_quiz"


def _seed_attempt() -> int:
    init_db()
    ensure_user(USER_ID)
    with session() as db:
        db.query(EventLog).filter(EventLog.user_id == USER_ID).delete()
        db.query(QuizAttempt).filter(QuizAttempt.user_id == USER_ID).delete()
        db.query(Profile).filter(Profile.user_id == USER_ID).delete()
        db.merge(Resource(
            id=QUIZ_ID,
            user_id=USER_ID,
            kind="quiz",
            kp="heap",
            title="堆诊断测验",
            payload={"questions": [], "source_ids": []},
            citations=[],
            safety={},
        ))
        attempt = QuizAttempt(
            user_id=USER_ID,
            quiz_resource_id=QUIZ_ID,
            kp="heap",
            score=0,
            detail={
                "answers": [],
                "diagnosis": {
                    "status": "needed",
                    "action": "remediate",
                    "blocked_kp": "heap",
                    "blocked_name": "堆与优先队列",
                    "prerequisite_gap": "binary_tree",
                    "prerequisite_name": "二叉树",
                    "remediation_kp": "binary_tree",
                    "remediation_name": "二叉树",
                    "misconception": "父子关系判断错误",
                    "reason": "先补二叉树，再回到堆。",
                },
            },
        )
        db.add(attempt)
        db.commit()
        return int(attempt.id)


def test_remediation_generation_is_persisted_and_idempotent(monkeypatch):
    attempt_id = _seed_attempt()
    calls = 0

    async def fake_doc_run(state):
        nonlocal calls
        calls += 1
        assert state["knowledge_points"] == ["binary_tree"]
        assert state["prompt_template"] == "remediation"
        assert state["skip_multimodal"] is True
        assert state["required_retrieval_terms"] == ["二叉树", "binary_tree"]
        resource = {
            "id": "remediation-doc-1",
            "kind": "doc",
            "kp": "binary_tree",
            "title": "临时标题",
            "payload": {
                "markdown": "# 为什么先补这一点\n\n二叉树是理解堆父子关系的基础。[^1]",
                "grounded": True,
            },
            "citations": ["课程讲义 · 二叉树 p.1"],
        }
        return {"generated_resources": {resource["id"]: resource}, "safety_flags": []}

    monkeypatch.setattr(evaluate_api.doc_agent, "run", fake_doc_run)

    with TestClient(app) as client:
        first = client.post("/api/eval/remediation", json={
            "user_id": USER_ID,
            "attempt_id": attempt_id,
        })
        assert first.status_code == 200, first.text
        payload = first.json()
        assert payload["next_action"] == "retest"
        assert payload["reused"] is False
        assert payload["resource"]["title"] == "二叉树·补救微课"
        assert payload["resource"]["payload"]["remediation"]["origin_attempt_id"] == attempt_id

        second = client.post("/api/eval/remediation", json={
            "user_id": USER_ID,
            "attempt_id": attempt_id,
        })
        assert second.status_code == 200, second.text
        assert second.json()["reused"] is True

    assert calls == 1
    with session() as db:
        attempt = db.get(QuizAttempt, attempt_id)
        assert attempt.detail["remediation"]["resource_id"] == "remediation-doc-1"
        assert db.get(Resource, "remediation-doc-1") is not None


def test_submit_diagnoses_prerequisite_gap_and_persists_cycle_state():
    init_db()
    ensure_user(SUBMIT_USER_ID)
    with session() as db:
        db.query(EventLog).filter(EventLog.user_id == SUBMIT_USER_ID).delete()
        db.query(ReviewItem).filter(ReviewItem.user_id == SUBMIT_USER_ID).delete()
        db.query(QuizAttempt).filter(QuizAttempt.user_id == SUBMIT_USER_ID).delete()
        db.query(Profile).filter(Profile.user_id == SUBMIT_USER_ID).delete()
        db.merge(Resource(
            id=SUBMIT_QUIZ_ID,
            user_id=SUBMIT_USER_ID,
            kind="quiz",
            kp="heap",
            title="堆诊断测验",
            payload={
                "source_ids": [],
                "questions": [{
                    "id": "heap-q1",
                    "type": "single",
                    "stem": "堆的父子节点关系依赖哪种基础结构？",
                    "options": ["A. 二叉树", "B. 数组排序", "C. 哈希表", "D. 图遍历"],
                    "answer": "A",
                    "explain": "堆具有完全二叉树的结构约束。",
                    "kp": "heap",
                    "difficulty": 2,
                    "error_tags": ["父子关系判断错误"],
                }],
            },
            citations=[],
            safety={},
        ))
        db.commit()

    with TestClient(app) as client:
        response = client.post("/api/eval/submit", json={
            "user_id": SUBMIT_USER_ID,
            "quiz_resource_id": SUBMIT_QUIZ_ID,
            "kp": "heap",
            "answers": [{
                "question_id": "heap-q1",
                "answer": "B",
                "correct": True,
                "seconds": 12,
                "hint_used": False,
                "revealed": False,
                "misconception": "概念没记牢",
                "confidence": "confident",
            }],
            "behavior": {"dwell_seconds": 12},
        })

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["accuracy"] == 0
    assert payload["diagnosis"]["action"] == "remediate"
    assert payload["diagnosis"]["blocked_kp"] == "heap"
    assert payload["diagnosis"]["prerequisite_gap"] == "binary_tree"
    assert payload["path"]["next_kp"] == "binary_tree"
    assert payload["path"]["generated_by"] == "diagnostic-remediation"

    with session() as db:
        attempt = db.get(QuizAttempt, int(payload["attempt_id"]))
        assert attempt.detail["diagnosis"]["remediation_kp"] == "binary_tree"

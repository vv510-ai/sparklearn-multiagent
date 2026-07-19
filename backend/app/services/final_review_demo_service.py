"""Repeatable final-review demo quiz sets and learner-owned baseline restore."""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select

from ..models.db import init_db, session
from ..models.entities import (
    DemoBaseline,
    EventLog,
    PathPlan,
    PersonalizationDecision,
    Profile,
    QuizAttempt,
    Resource,
    ReviewItem,
)
from .profile_service import ensure_user, get_profile

BASELINE_KIND = "final_review_v1"
DEMO_VERSION = "final-review-2026-07-v1"
_SEED_QUIZ_PATH = Path(__file__).resolve().parents[1] / "data" / "seed_quiz.json"

_SET_SPECS: tuple[dict[str, Any], ...] = (
    {
        "id": "final-binary-tree-v1",
        "title": "终审固定题组一：二叉树",
        "kp": "binary_tree",
        "order": 1,
        "question_ids": ["q015", "q016", "q039", "q040", "q041"],
        "target_pattern": [True, True, True, True, True],
        "operator_answers": ["B", "DEBCA", "B", "A", "错"],
        "pattern_label": "对 → 对 → 对 → 对 → 对",
    },
    {
        "id": "final-sorting-adv-v1",
        "title": "终审固定题组二：高级排序",
        "kp": "sorting_adv",
        "order": 2,
        "question_ids": ["q012", "q013", "q014", "q048", "q049"],
        "target_pattern": [False, True, False, False, False],
        "operator_answers": ["A", "错", "时间 O(n^2)；空间 O(1)", "B", "B"],
        "pattern_label": "错 → 对 → 错 → 错 → 错",
    },
)
_SPEC_BY_ID = {str(spec["id"]): spec for spec in _SET_SPECS}


def _resource_id(user_id: str, set_id: str) -> str:
    digest = hashlib.sha256(f"{DEMO_VERSION}\0{user_id}\0{set_id}".encode()).hexdigest()[:16]
    return f"final_{digest}"


def _seed_questions() -> dict[str, dict[str, Any]]:
    try:
        payload = json.loads(_SEED_QUIZ_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise RuntimeError("固定题库暂时不可用") from exc
    questions = payload.get("questions", []) if isinstance(payload, dict) else []
    return {
        str(question.get("id")): copy.deepcopy(question)
        for question in questions
        if isinstance(question, dict) and question.get("id")
    }


def _questions_for(spec: dict[str, Any]) -> list[dict[str, Any]]:
    bank = _seed_questions()
    questions: list[dict[str, Any]] = []
    for question_id in spec["question_ids"]:
        question = bank.get(str(question_id))
        if not question or str(question.get("kp")) != str(spec["kp"]):
            raise RuntimeError(f"固定题目 {question_id} 缺失或知识点不一致")
        questions.append(question)
    if len(questions) != 5:
        raise RuntimeError(f"题组 {spec['id']} 必须恰好包含 5 题")
    return questions


def _resource_payload(spec: dict[str, Any]) -> dict[str, Any]:
    return {
        "questions": _questions_for(spec),
        "difficulty": 3,
        "source_ids": [],
        "learning_goal": "终审演示固定测验",
        "topic_label": "二叉树" if spec["kp"] == "binary_tree" else "高级排序",
        "custom_topic": False,
        "transfer_retest": False,
        "quiz_set_id": spec["id"],
        "demo_final_review": {
            "version": DEMO_VERSION,
            "set_id": spec["id"],
            "order": spec["order"],
            "target_pattern": spec["target_pattern"],
        },
        "generation_scope": {
            "notebook_id": "",
            "session_id": "final-review",
            "conversation_focus": "终审演示固定测验",
            "source_ids": [],
            "artifact_scope": "current_topic",
        },
    }


def _max_id(db, model: type, user_id: str) -> int:
    value = db.execute(
        select(func.max(model.id)).where(model.user_id == user_id),
    ).scalar_one_or_none()
    return int(value or 0)


def _iso(value: dt.datetime | None) -> str:
    return value.isoformat() if value else ""


def _parse_datetime(value: Any) -> dt.datetime:
    try:
        return dt.datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return dt.datetime.now(dt.timezone.utc)


def _review_snapshot(row: ReviewItem) -> dict[str, Any]:
    return {
        "id": row.id,
        "quiz_resource_id": row.quiz_resource_id,
        "question_id": row.question_id,
        "kp": row.kp,
        "source_attempt_id": row.source_attempt_id,
        "stage": row.stage,
        "status": row.status,
        "due_at": _iso(row.due_at),
        "lapse_count": row.lapse_count,
        "last_correct": row.last_correct,
        "data": copy.deepcopy(row.data or {}),
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def _capture_baseline(db, user_id: str) -> dict[str, Any]:
    profile = db.get(Profile, user_id)
    path = db.get(PathPlan, user_id)
    reviews = (
        db.query(ReviewItem)
        .filter(ReviewItem.user_id == user_id)
        .order_by(ReviewItem.id)
        .all()
    )
    return {
        "version": DEMO_VERSION,
        "profile": {
            "data": copy.deepcopy(profile.data or {}) if profile else {},
            "version": int(profile.version or 0) if profile else 0,
        },
        "path": {
            "exists": path is not None,
            "data": copy.deepcopy(path.data or {}) if path else {},
        },
        "cutoffs": {
            "event_log": _max_id(db, EventLog, user_id),
            "quiz_attempt": _max_id(db, QuizAttempt, user_id),
            "personalization_decision": _max_id(db, PersonalizationDecision, user_id),
        },
        "reviews": [_review_snapshot(row) for row in reviews],
    }


def _resource_dict(resource: Resource) -> dict[str, Any]:
    return {
        "id": resource.id,
        "kind": resource.kind,
        "kp": resource.kp,
        "title": resource.title,
        "payload": copy.deepcopy(resource.payload or {}),
        "citations": copy.deepcopy(resource.citations or []),
        "created_at": resource.created_at.isoformat() if resource.created_at else None,
    }


def prepare_final_review(user_id: str) -> dict[str, Any]:
    """Upsert both fixed sets and capture the learner's baseline exactly once."""
    ensure_user(user_id)
    get_profile(user_id)  # Materialize/normalize the profile before snapshotting it.
    init_db()
    with session() as db:
        for spec in _SET_SPECS:
            resource_id = _resource_id(user_id, str(spec["id"]))
            resource = db.get(Resource, resource_id)
            payload = _resource_payload(spec)
            if resource is None:
                db.add(Resource(
                    id=resource_id,
                    user_id=user_id,
                    kind="quiz",
                    kp=str(spec["kp"]),
                    title=str(spec["title"]),
                    payload=payload,
                    citations=[],
                    safety={"flags": []},
                ))
            elif resource.user_id != user_id:
                raise HTTPException(409, "固定题组归属冲突")
            else:
                resource.kind = "quiz"
                resource.kp = str(spec["kp"])
                resource.title = str(spec["title"])
                resource.payload = payload
                resource.citations = []
                resource.safety = {"flags": []}

        baseline = db.get(DemoBaseline, user_id)
        if baseline is None:
            baseline = DemoBaseline(
                user_id=user_id,
                kind=BASELINE_KIND,
                data=_capture_baseline(db, user_id),
            )
            db.add(baseline)
        elif baseline.kind != BASELINE_KIND or (baseline.data or {}).get("version") != DEMO_VERSION:
            raise HTTPException(409, "已有其他版本的演示基线，请联系开发同学确认后再继续")
        db.commit()
    return final_review_status(user_id)


def _restore_reviews(db, user_id: str, snapshots: list[dict[str, Any]]) -> None:
    db.query(ReviewItem).filter(ReviewItem.user_id == user_id).delete(synchronize_session=False)
    for item in snapshots:
        db.add(ReviewItem(
            id=int(item["id"]),
            user_id=user_id,
            quiz_resource_id=str(item.get("quiz_resource_id") or ""),
            question_id=str(item.get("question_id") or ""),
            kp=str(item.get("kp") or ""),
            source_attempt_id=int(item.get("source_attempt_id") or 0),
            stage=int(item.get("stage") or 0),
            status=str(item.get("status") or "scheduled"),
            due_at=_parse_datetime(item.get("due_at")),
            lapse_count=int(item.get("lapse_count") or 0),
            last_correct=int(item.get("last_correct") if item.get("last_correct") is not None else -1),
            data=copy.deepcopy(item.get("data") or {}),
            created_at=_parse_datetime(item.get("created_at")),
            updated_at=_parse_datetime(item.get("updated_at")),
        ))


def restore_final_review(user_id: str) -> dict[str, Any]:
    """Restore profile, path, evidence, attempts, and mistake/review state."""
    ensure_user(user_id)
    with session() as db:
        baseline = db.get(DemoBaseline, user_id)
        if baseline is None or baseline.kind != BASELINE_KIND:
            raise HTTPException(409, "还没有可恢复的演示基线，请先准备终审题组")
        snapshot = copy.deepcopy(baseline.data or {})
        if snapshot.get("version") != DEMO_VERSION:
            raise HTTPException(409, "演示基线版本不匹配，请暂停正式答题")

        profile_snapshot = snapshot.get("profile") or {}
        profile = db.get(Profile, user_id)
        if profile is None:
            profile = Profile(user_id=user_id)
            db.add(profile)
        profile.data = copy.deepcopy(profile_snapshot.get("data") or {})
        profile.version = int(profile_snapshot.get("version") or 0)

        path_snapshot = snapshot.get("path") or {}
        path = db.get(PathPlan, user_id)
        if path_snapshot.get("exists"):
            if path is None:
                path = PathPlan(user_id=user_id)
                db.add(path)
            path.data = copy.deepcopy(path_snapshot.get("data") or {})
        elif path is not None:
            db.delete(path)

        cutoffs = snapshot.get("cutoffs") or {}
        db.query(EventLog).filter(
            EventLog.user_id == user_id,
            EventLog.id > int(cutoffs.get("event_log") or 0),
        ).delete(synchronize_session=False)
        db.query(QuizAttempt).filter(
            QuizAttempt.user_id == user_id,
            QuizAttempt.id > int(cutoffs.get("quiz_attempt") or 0),
        ).delete(synchronize_session=False)
        db.query(PersonalizationDecision).filter(
            PersonalizationDecision.user_id == user_id,
            PersonalizationDecision.id > int(cutoffs.get("personalization_decision") or 0),
        ).delete(synchronize_session=False)
        _restore_reviews(db, user_id, list(snapshot.get("reviews") or []))
        db.commit()
    return final_review_status(user_id)


def _baseline_for_user(db, user_id: str) -> tuple[DemoBaseline | None, dict[str, Any]]:
    baseline = db.get(DemoBaseline, user_id)
    snapshot = copy.deepcopy(baseline.data or {}) if baseline else {}
    if baseline and (baseline.kind != BASELINE_KIND or snapshot.get("version") != DEMO_VERSION):
        return baseline, {}
    return baseline, snapshot


def final_review_status(user_id: str) -> dict[str, Any]:
    ensure_user(user_id)
    with session() as db:
        baseline, snapshot = _baseline_for_user(db, user_id)
        cutoff = int((snapshot.get("cutoffs") or {}).get("quiz_attempt") or 0)
        sets: list[dict[str, Any]] = []
        completed_ids: list[str] = []
        resources_ready = True
        for spec in _SET_SPECS:
            resource_id = _resource_id(user_id, str(spec["id"]))
            resource = db.get(Resource, resource_id)
            valid_resource = bool(
                resource
                and resource.user_id == user_id
                and resource.kind == "quiz"
                and isinstance(resource.payload, dict)
                and resource.payload.get("quiz_set_id") == spec["id"]
                and len(resource.payload.get("questions") or []) == 5
            )
            resources_ready = resources_ready and valid_resource
            completed = bool(
                valid_resource
                and db.query(QuizAttempt).filter(
                    QuizAttempt.user_id == user_id,
                    QuizAttempt.quiz_resource_id == resource_id,
                    QuizAttempt.id > cutoff,
                ).first()
            )
            if completed:
                completed_ids.append(str(spec["id"]))
            sets.append({
                "id": spec["id"],
                "title": spec["title"],
                "order": spec["order"],
                "question_count": 5,
                "pattern_label": spec["pattern_label"],
                "operator_answers": list(spec["operator_answers"]),
                "completed": completed,
                "resource": _resource_dict(resource) if valid_resource and resource else None,
            })

        checks = {
            "account": True,
            "quiz_sets": resources_ready,
            "baseline": bool(snapshot),
            "answer_order": all(len(spec["operator_answers"]) == 5 for spec in _SET_SPECS),
        }
        ready = all(checks.values())
        next_set_id = next((str(item["id"]) for item in sets if not item["completed"]), "")
        return {
            "version": DEMO_VERSION,
            "ready": ready,
            "checks": checks,
            "baseline": {
                "exists": bool(snapshot),
                "created_at": baseline.created_at.isoformat() if baseline and baseline.created_at else None,
            },
            "completed_set_ids": completed_ids,
            "next_set_id": next_set_id,
            "sets": sets,
        }


def enforce_final_review_submission(
    user_id: str,
    resource_id: str,
    enriched_answers: list[dict[str, Any]],
) -> None:
    """Fail before any mutations when a fixed demo submission deviates from plan."""
    with session() as db:
        resource = db.get(Resource, resource_id)
        payload = resource.payload if resource and isinstance(resource.payload, dict) else {}
        demo_meta = payload.get("demo_final_review") if isinstance(payload, dict) else None
        if not isinstance(demo_meta, dict):
            return
        set_id = str(demo_meta.get("set_id") or "")
        spec = _SPEC_BY_ID.get(set_id)
        if not spec or demo_meta.get("version") != DEMO_VERSION:
            raise HTTPException(409, "题组版本未确认，请暂停正式答题")
        baseline, snapshot = _baseline_for_user(db, user_id)
        if baseline is None or not snapshot:
            raise HTTPException(409, "账号或答题前基线尚未确认，请暂停正式答题")
        if not resource or resource.user_id != user_id:
            raise HTTPException(404, "固定题组不存在")

        expected_ids = list(spec["question_ids"])
        submitted_ids = [str(answer.get("question_id") or "") for answer in enriched_answers]
        if submitted_ids != expected_ids or len(enriched_answers) != 5:
            raise HTTPException(409, "必须按固定顺序完成当前 5 题后才能正式提交")
        if any(
            not str(answer.get("answer") or "").strip()
            or not str(answer.get("confidence") or "").strip()
            for answer in enriched_answers
        ):
            raise HTTPException(409, "每题答案与作答把握都确认后才能正式提交")
        if any(answer.get("hint_used") or answer.get("revealed") for answer in enriched_answers):
            raise HTTPException(409, "终审固定题组需独立作答，使用提示后请先恢复演示基线")

        cutoff = int((snapshot.get("cutoffs") or {}).get("quiz_attempt") or 0)
        existing = db.query(QuizAttempt).filter(
            QuizAttempt.user_id == user_id,
            QuizAttempt.quiz_resource_id == resource_id,
            QuizAttempt.id > cutoff,
        ).first()
        if existing:
            raise HTTPException(409, "当前题组已提交；如需重录，请先恢复演示基线")

        if int(spec["order"]) > 1:
            previous = _SET_SPECS[int(spec["order"]) - 2]
            previous_attempt = db.query(QuizAttempt).filter(
                QuizAttempt.user_id == user_id,
                QuizAttempt.quiz_resource_id == _resource_id(user_id, str(previous["id"])),
                QuizAttempt.id > cutoff,
            ).first()
            if previous_attempt is None:
                raise HTTPException(409, "请先完成二叉树 5 题，再提交高级排序题组")

        actual_pattern = [bool(answer.get("correct")) for answer in enriched_answers]
        if actual_pattern != list(spec["target_pattern"]):
            raise HTTPException(409, f"作答结果应为“{spec['pattern_label']}”；本次未写入画像，请核对后重试")

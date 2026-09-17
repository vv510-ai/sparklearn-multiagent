"""Fresh textbook exercises, transactional scoring and delayed new-question checks.

Uses the assessment snapshot and existing quiz evidence/calendar pipeline. A
question is never reissued after scoring, including after restarting assessment.
"""
from __future__ import annotations

import copy
import datetime as dt

from fastapi import HTTPException
from sqlalchemy import select, update

from ..models.db import session
from ..models.entities import AssessmentSession, EventLog
from .learning_scope import notebook_id, profile_row


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def public_progress(data: dict) -> dict:
    return {kp: {k: v for k, v in record.items() if k in (
        "answered", "independent", "correct", "next_due_at", "last_result", "exhausted")}
        for kp, record in data.get("textbook_practice", {}).items()}


def _save(db, row, data):
    revision = row.revision
    changed = db.execute(update(AssessmentSession).where(
        AssessmentSession.id == row.id, AssessmentSession.revision == revision).values(revision=revision + 1))
    if changed.rowcount != 1:
        raise HTTPException(409, "练习已更新，请重新读取；已提交的作答会保留")
    row.data, row.revision = data, revision + 1


def _history(db, user_id, data, kp):
    rows = db.scalars(select(EventLog).where(EventLog.user_id == user_id, EventLog.etype == "quiz_eval").order_by(EventLog.id)).all()
    return [row.payload["textbook_practice"] for row in rows
            if row.payload.get("notebook_id") == data.get("notebook_id")
            and row.payload.get("textbook_practice", {}).get("kp") == kp]


def _public_question(question):
    return {k: question[k] for k in ("id", "kp", "stem", "code", "options", "type")}


def begin(user_id: str, assessment_id: str, kp: str) -> dict:
    from .assessment_service import _owned, evidence_key
    with session() as db:
        row = _owned(db, user_id, assessment_id)
        data = copy.deepcopy(row.data)
        if data["status"] != "completed":
            raise HTTPException(409, "先完成起点测评，再开始新题练习")
        course = data.get("course_snapshot") or {}
        profile_row(db, user_id)  # Serialize practice across assessments in this notebook.
        tasks = [t for day in data["plan"]["days"] for t in day["tasks"]] + data["plan"]["deferred"]
        if kp not in {t["kp"] for t in tasks}:
            raise HTTPException(422, "请选择当前计划内的知识点")
        pool = [q for q in course.get("practice_bank", []) if q["kp"] == kp]
        if not pool:
            raise HTTPException(422, "这门课尚未配置经过核对的新题，请继续使用课程练习入口")
        records = data.setdefault("textbook_practice", {})
        record = records.setdefault(kp, {})
        history = _history(db, user_id, data, kp)
        seen = {h["key"] for h in history}
        available = [q for q in pool if evidence_key(kp, q["stem"] + "\n" + q["code"]) not in seen]
        record.update(answered=len(history), independent=sum(h["independent"] for h in history),
                      correct=sum(h["correct"] and h["independent"] for h in history),
                      next_due_at=history[-1].get("next_due_at") if history else None,
                      exhausted=not available)
        if not available:
            status, question = "exhausted", None
        elif record["next_due_at"] and now() < dt.datetime.fromisoformat(record["next_due_at"]):
            status, question = "scheduled", None
        else:
            # Another completed assessment window may already have submitted
            # this pending item. Resume only questions still absent from history.
            status, question = "active", next((q for q in available if q["id"] == record.get("pending")), available[0])
            record["pending"] = question["id"]
            record["issued_at"] = now().isoformat()
        if status != "active":
            record["pending"] = None
        _save(db, row, data)
        db.commit()
        return {"status": status, "question": _public_question(question) if question else None,
                "progress": public_progress(data)[kp]}


def answer(user_id: str, assessment_id: str, question_id: str, choice: str | None, assisted: bool) -> dict:
    from .assessment_service import _owned, _public, _refresh_from_practice, evidence_key
    from .bkt import bkt_update
    from .path_service import plan_path
    with session() as db:
        row = _owned(db, user_id, assessment_id)
        data = copy.deepcopy(row.data)
        if data["status"] != "completed":
            raise HTTPException(409, "请先完成起点测评")
        course = data.get("course_snapshot") or {}
        profile = profile_row(db, user_id)
        question = next((q for q in course.get("practice_bank", []) if q["id"] == question_id), None)
        if not question:
            raise HTTPException(404, "新题不存在")
        kp = question["kp"]
        record = data.get("textbook_practice", {}).get(kp, {})
        last = record.get("last_result")
        if last and last["question_id"] == question_id:
            if last["choice"] != choice or last["assisted"] != assisted:
                raise HTTPException(409, "该题已提交，不能修改已计入的作答")
            return {"result": last, "assessment": _public(row)}
        if record.get("pending") != question_id:
            raise HTTPException(409, "请先打开当前新题；不要提交已经做过的题")
        if choice is not None and choice not in "ABCD" or choice == "":
            raise HTTPException(422, "请选择有效选项，或选择还不会")
        key = evidence_key(kp, question["stem"] + "\n" + question["code"])
        history = _history(db, user_id, data, kp)
        if key in {h["key"] for h in history}:
            raise HTTPException(409, "这道题已经提交过，请重新读取练习")
        correct, independent = choice == question["answer"], not assisted
        count = len(history) + 1
        next_due = (now() + dt.timedelta(days=1 if count == 3 else 3)).isoformat() if count % 3 == 0 else None
        if count >= sum(q["kp"] == kp for q in course["practice_bank"]):
            next_due = None
        result = {"question_id": question_id, "choice": choice, "assisted": assisted, "correct": correct,
                  "independent": independent, "answer": question["answer"], "explain": question["explain"],
                  "citations": [{k: v for k, v in e.items() if k != "text"} for e in course.get("evidence", {}).get(kp, [])],
                  "message": "已记录为借助资料完成；不会增加独立掌握证据。" if assisted else
                             "本次新题已计入学习证据；请结合后续新题与延迟复测判断。"}
        record.update(pending=None, answered=count, independent=sum(h["independent"] for h in history) + int(independent),
                      correct=sum(h["correct"] and h["independent"] for h in history) + int(correct and independent),
                      next_due_at=next_due, last_result=result,
                      exhausted=count >= sum(q["kp"] == kp for q in course["practice_bank"]))
        _save(db, row, data)
        if independent and profile:
            value = copy.deepcopy(profile.data)
            value["knowledge_mastery"][kp] = bkt_update(value["knowledge_mastery"].get(kp, .3), correct)
            profile.data, profile.version = value, profile.version + 1
            profile.path = plan_path(value, generated_by="textbook_practice")
        db.add(EventLog(user_id=user_id, etype="quiz_eval", payload={
            "notebook_id": notebook_id(), "course_revision": course["revision"],
            "learning_evidence": [{"key": key, "kp": kp, "correct": correct,
                                   "support_level": "independent" if independent else "assisted"}],
            "per_kp": {kp: {"n": 1, "right": int(correct)}},
            "textbook_practice": {"key": key, "kp": kp, "question_id": question_id,
                                  "correct": correct, "independent": independent, "at": now().isoformat(),
                                  "phase": "practice" if count <= 3 else "delayed_retest", "next_due_at": next_due}}))
        db.flush()
        _refresh_from_practice(db, row)
        # Three independent correct new answers complete this learning step.
        # Retention remains pending until the scheduled later round.
        batch = [*history, {"independent": independent, "correct": correct}][-3:]
        if count % 3 == 0 and all(h["independent"] and h["correct"] for h in batch):
            updated = copy.deepcopy(row.data)
            tasks = [t for day in updated["plan"]["days"] for t in day["tasks"]]
            for task in tasks:
                if task["kp"] == kp and task["kind"] in ("study", "transfer", "diagnose"):
                    task["done"] = all(next((p["done"] for p in tasks if p["id"] == dep), False) for dep in task["requires"])
            row.data = updated
        db.commit()
        return {"result": result, "assessment": _public(row)}

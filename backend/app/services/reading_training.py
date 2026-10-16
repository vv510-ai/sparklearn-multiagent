"""Private, source-labelled reading practice; never writes mastery estimates.

Immutable material/first submissions, CAS transitions and idempotent retries.
"""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
from functools import lru_cache
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from ..models.db import session
from ..models.entities import ReadingTraining
from ..schemas.reading import ReadingAction, ReadingMaterial
from .learning_scope import ensure_space, course_scope
from .review_service import review_queue
from .review_scheduler import schedule
from .study_paths import course_key


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def fingerprint(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@lru_cache(maxsize=1)
def examples() -> dict:
    raw = json.loads((Path(__file__).parents[1] / "data" / "reading_examples_v1.json").read_text(encoding="utf-8"))
    return {item["id"]: ReadingMaterial.model_validate(item["material"]).model_dump(mode="json") for item in raw}


def check_course(user: str, notebook: str):
    if course_key(ensure_space(user, notebook).course) != "cet6":
        raise HTTPException(404, "请在大学英语六级课程中打开阅读训练。")


def find(db, user: str, notebook: str, item: str) -> ReadingTraining:
    row = db.scalar(select(ReadingTraining).where(ReadingTraining.id == item,
        ReadingTraining.user_id == user, ReadingTraining.notebook_id == notebook))
    if row is None:
        raise HTTPException(404, "找不到这份阅读记录，请从当前课程重新打开。")
    return row


def _summary(row: ReadingTraining) -> dict:
    data = row.data
    first = data.get("first")
    review = data.get("review", {})
    return {"id": row.id, "title": data["material"]["title"], "source": data["material"]["source"],
            "demo": data["demo"], "source_type": data["material"]["source_type"],
            "phase": data["phase"], "due_at": review.get("due_at"),
            "first": {k: first[k] for k in ("correct", "total", "submitted_at", "elapsed_seconds", "used_help")} if first else None,
            "reviews": len([r for r in data.get("reviews", []) if not r["early"] and not r.get("used_help")]),
            "updated_at": data["updated_at"], "sample_id": row.material_id if data["demo"] else ""}


def library(user: str, notebook: str) -> dict:
    check_course(user, notebook)
    with session() as db:
        rows = db.scalars(select(ReadingTraining).where(ReadingTraining.user_id == user,
            ReadingTraining.notebook_id == notebook)).all()
        items = [_summary(row) for row in rows]
    used = {i["sample_id"] for i in items}
    current = utc_now().isoformat()
    items.sort(key=lambda i: (0 if i["phase"] != "done" else 1 if i["due_at"] and i["due_at"] <= current else 2,
                             i["due_at"] or i["updated_at"]))
    with course_scope(user, notebook):
        legacy = review_queue(user, limit=5)["summary"]["due"]
    return {"items": items,
            "examples": [{"id": k, "title": v["title"], "source": v["source"], "questions": len(v["questions"])}
                         for k, v in examples().items() if k not in used],
            "due": sum(bool(i["due_at"] and i["due_at"] <= current) for i in items),
            "legacy_due": legacy,
            "private_completed": sum(i["phase"] == "done" and not i["demo"] for i in items),
            "demo_completed": sum(i["phase"] == "done" and i["demo"] for i in items),
            "server_time": current}


def _create(user: str, notebook: str, material_id: str, material: dict, demo: bool) -> dict:
    check_course(user, notebook)
    key = str(uuid5(NAMESPACE_URL, f"learnloop-reading:{user}:{notebook}:{material_id}"))
    version = fingerprint(material)
    with session() as db:
        row = db.get(ReadingTraining, key)
        if row:
            if row.data["version"] != version:
                raise HTTPException(409, "这次导入编号已用于不同内容，请重新导入。")
            return public(row)
        if len(db.scalars(select(ReadingTraining.id).where(ReadingTraining.user_id == user,
                ReadingTraining.notebook_id == notebook)).all()) >= 200:
            raise HTTPException(409, "本课程已保存 200 篇阅读，请先使用已有材料。")
        row = ReadingTraining(id=key, user_id=user, notebook_id=notebook, material_id=material_id,
            revision=0, data={"material": material, "version": version, "demo": demo,
                "phase": "answer", "draft": {}, "uncertain": [], "used_help": False, "elapsed_seconds": 0, "note": "", "reviews": [],
                "updated_at": utc_now().isoformat(), "operations": {}})
        db.add(row)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            row = find(db, user, notebook, key)
            if row.data["version"] != version:
                raise HTTPException(409, "导入内容已变化，请重新导入。")
        return public(row)


def start_example(user: str, notebook: str, sample: str) -> dict:
    if sample not in examples():
        raise HTTPException(404, "体验示例不存在。")
    return _create(user, notebook, sample, copy.deepcopy(examples()[sample]), True)


def import_material(user: str, notebook: str, request_id: str, material: ReadingMaterial) -> dict:
    return _create(user, notebook, request_id, material.model_dump(mode="json"), False)


def _exercises(data: dict, kind: str) -> list[dict]:
    questions = {q["id"]: q for q in data["material"]["questions"]}
    result = []
    focus_ids = data["focus_ids"][:2] if kind == "drill" else data["focus_ids"]
    for question_id in focus_ids:
        q = questions[question_id]
        short = q.get(kind)
        result.append({**(short or {"context": "\n\n".join(data["material"]["paragraphs"]),
            "prompt": q["prompt"], "options": q["options"], "answer": q["answer"], "explanation": q["explanation"]}),
            "id": question_id, "kind": "short" if short else "original"})
    return result


def public(row: ReadingTraining) -> dict:
    data = row.data
    material = copy.deepcopy(data["material"])
    material["questions"] = [{k: q[k] for k in ("id", "skill", "prompt", "options")} for q in material["questions"]]
    response = {**_summary(row), "notebook_id": row.notebook_id, "revision": row.revision,
                "version": data["version"], "material": material, "draft": data["draft"],
                "uncertain": data["uncertain"], "used_help": data.get("used_help", False), "note": data["note"], "focus_ids": data.get("focus_ids", []),
                "first": data.get("first"), "elapsed_seconds": data.get("elapsed_seconds", 0), "review": data.get("review"), "history": data.get("reviews", []),
                "active_review": data.get("active_review"), "exercise_answers": data.get("exercise_answers", {})}
    if data["phase"] in {"feedback", "drill", "drill_feedback", "done"}:
        response["feedback"] = [{k: v for k, v in q.items() if k not in {"drill", "recall"}}
                                for q in data["material"]["questions"]]
    kind = "recall" if data["phase"] == "recall" else "drill"
    if data["phase"] in {"drill", "drill_feedback", "recall"}:
        response["exercises"] = [{k: v for k, v in q.items() if data["phase"] == "drill_feedback" or k not in {"answer", "explanation"}}
                                 for q in _exercises(data, kind)]
    if data["phase"] == "recall":
        # The same questions may recur: do not leak previous correct selections
        # through history, first-answer snapshots or the original draft.
        response["draft"] = {}
        response["note"] = ""
        response["first"] = {k: v for k, v in data["first"].items() if k != "answers"}
        response["history"] = [{k: v for k, v in record.items() if k != "answers"} for record in data["reviews"]]
    if data.get("last_review") and data["phase"] == "done":
        response["last_review"] = data["last_review"]
    return response


def detail(user: str, notebook: str, item: str) -> dict:
    check_course(user, notebook)
    with session() as db:
        return public(find(db, user, notebook, item))


def _validate_answers(answers: dict, questions: list[dict], *, complete: bool):
    expected = {q["id"]: q for q in questions}
    if (complete and set(answers) != set(expected)) or not set(answers).issubset(expected):
        raise HTTPException(422, "请完成所有题目；答案只能属于当前练习。")
    if any(isinstance(value, bool) or value < 0 or value >= len(expected[key]["options"]) for key, value in answers.items()):
        raise HTTPException(422, "答案必须对应当前题目的选项。")


def act(user: str, notebook: str, item: str, req: ReadingAction) -> dict:
    check_course(user, notebook)
    operation_id = str(req.request_id)
    operation_hash = fingerprint(req.model_dump(mode="json", exclude={"request_id", "revision"}))
    now = utc_now()
    with session() as db:
        row = find(db, user, notebook, item)
        data = copy.deepcopy(row.data)
        if data["version"] != req.version:
            raise HTTPException(409, "材料版本不一致，请保留草稿后重新打开。")
        previous = data["operations"].get(operation_id)
        if previous:
            if previous != operation_hash:
                raise HTTPException(409, "同一次请求的内容已变化，请重新操作。")
            return public(row)
        if row.revision != req.revision:
            raise HTTPException(409, "另一页面已保存新进度。当前草稿保留，请重新加载后核对。")
        phase = data["phase"]
        questions = data["material"]["questions"]
        if req.action in {"draft", "submit"} and phase == "answer":
            _validate_answers(req.answers, questions, complete=req.action == "submit")
            if not set(req.uncertain).issubset({q["id"] for q in questions}):
                raise HTTPException(422, "不确定标记只能属于当前题目。")
            data["draft"] = req.answers
            data["uncertain"] = sorted(set(req.uncertain))
            data["used_help"] = bool(data.get("used_help") or req.used_help)
            data["elapsed_seconds"] = req.elapsed_seconds
            if req.action == "submit":
                missed = [q["id"] for q in questions if req.answers[q["id"]] != q["answer"]]
                data["first"] = {"answers": req.answers, "uncertain": data["uncertain"],
                    "correct": len(questions) - len(missed), "total": len(questions),
                    "elapsed_seconds": req.elapsed_seconds, "used_help": data["used_help"], "submitted_at": now.isoformat()}
                focus = list(dict.fromkeys(missed + data["uncertain"])) or [q["id"] for q in questions]
                data["focus_ids"] = focus
                data["phase"] = "feedback"
        elif req.action == "draft" and phase == "feedback":
            data["note"] = req.note.strip()
        elif req.action == "draft" and phase == "drill":
            _validate_answers(req.answers, _exercises(data, "drill"), complete=False)
            data["exercise_answers"] = req.answers
        elif req.action == "reflect" and phase == "feedback":
            data["note"] = req.note.strip()
            data["phase"] = "drill"
            data["exercise_answers"] = {}
        elif req.action == "drill" and phase == "drill":
            _validate_answers(req.answers, _exercises(data, "drill"), complete=True)
            data["exercise_answers"] = req.answers
            data["phase"] = "drill_feedback"
        elif req.action == "finish" and phase == "drill_feedback":
            data["phase"] = "done"
            # Feedback was just visible; schedule fresh recall without treating
            # seeing an answer as independent success.
            data["review"], _ = schedule({}, {"early": False, "used_help": True},
                                        "again", now, f"reading:{user}:{item}")
        elif req.action == "start_review" and phase == "done":
            review = data["review"]
            due_at = review.get("due_at")
            data["phase"] = "recall"
            data["exercise_answers"] = {}
            data["used_help"] = False
            data["active_review"] = {"early": not due_at or now < dt.datetime.fromisoformat(due_at),
                "started_at": now.isoformat(), "scheduled_due_at": due_at}
        elif req.action in {"review_draft", "review_submit"} and phase == "recall":
            exercises = _exercises(data, "recall")
            _validate_answers(req.answers, exercises, complete=req.action == "review_submit")
            data["exercise_answers"] = req.answers
            data["used_help"] = bool(data.get("used_help") or req.used_help)
            if req.action == "review_submit":
                correct = sum(req.answers[q["id"]] == q["answer"] for q in exercises)
                early = data["active_review"]["early"]
                record = {"answers": req.answers, "correct": correct, "total": len(exercises),
                    "early": early, "used_help": data["used_help"], "submitted_at": now.isoformat(),
                    "kind": "original" if all(q["kind"] == "original" for q in exercises) else "short"}
                data["reviews"].append(record)
                data["last_review"] = {**record, "feedback": exercises}
                data["review"], audit = schedule(data["review"],
                    {"early": early, "used_help": data["used_help"], "correct": correct == len(exercises)},
                    "good" if correct == len(exercises) else "again", now, f"reading:{user}:{item}")
                data["reviews"][-1].update(audit)
                data["last_review"].update(audit)
                data["phase"] = "done"
                data.pop("active_review", None)
        else:
            raise HTTPException(409, "这一步已完成或顺序不符，请重新加载当前进度。")
        data["updated_at"] = now.isoformat()
        data["operations"][operation_id] = operation_hash
        data["operations"] = dict(list(data["operations"].items())[-64:])
        changed = db.execute(update(ReadingTraining).where(ReadingTraining.id == item,
            ReadingTraining.user_id == user, ReadingTraining.notebook_id == notebook,
            ReadingTraining.revision == req.revision).values(data=data, revision=req.revision + 1))
        if changed.rowcount != 1:
            db.rollback()
            current = find(db, user, notebook, item)
            if current.data["operations"].get(operation_id) == operation_hash:
                return public(current)
            raise HTTPException(409, "进度刚刚更新，请保留草稿后重新加载。")
        db.commit()
        db.refresh(row)
        return public(row)

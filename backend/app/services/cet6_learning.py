"""Notebook-private CET6 preferences and explainable next actions."""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
from uuid import NAMESPACE_URL, uuid5

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from ..models.db import session
from ..models.entities import Cet6Profile, VocabularyCard, Cet6Practice, ReadingTraining
from ..schemas.cet6 import Preferences
from .learning_scope import ensure_space
from .study_paths import course_key

LABELS = {"listening": "听力", "reading": "阅读", "writing": "写作", "translation": "翻译", "vocabulary": "词汇"}


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def check(user: str, notebook: str):
    if course_key(ensure_space(user, notebook).course) != "cet6":
        raise HTTPException(404, "请在六级课程中打开这项学习。")


def stable_id(kind: str, user: str, notebook: str, key: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"learnloop:{kind}:{user}:{notebook}:{key}"))


def profile(user: str, notebook: str) -> dict:
    with session() as db:
        row = db.scalar(select(Cet6Profile).where(Cet6Profile.notebook_id == notebook, Cet6Profile.user_id == user))
        return {"revision": row.revision if row else 0, "preferences": {**Preferences().model_dump(mode="json"), **(copy.deepcopy(row.data) if row else {})}}


def save_profile(user: str, notebook: str, revision: int, preferences: Preferences) -> dict:
    check(user, notebook)
    data = preferences.model_dump(mode="json")
    with session() as db:
        row = db.scalar(select(Cet6Profile).where(Cet6Profile.notebook_id == notebook, Cet6Profile.user_id == user))
        if row is None:
            if revision:
                raise HTTPException(409, "目标记录已变化，请重新读取后核对。")
            row = Cet6Profile(notebook_id=notebook, user_id=user, data=Preferences().model_dump(mode="json"), revision=0)
            db.add(row)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                row = db.scalar(select(Cet6Profile).where(Cet6Profile.notebook_id == notebook, Cet6Profile.user_id == user))
        if row is None or row.revision != revision:
            if row and row.revision == revision + 1 and row.data == data:
                return {"revision": row.revision, "preferences": data}
            raise HTTPException(409, "另一页面已修改目标。你的输入仍保留，请重新读取后核对。")
        changed = db.execute(update(Cet6Profile).where(Cet6Profile.notebook_id == notebook,
            Cet6Profile.user_id == user, Cet6Profile.revision == revision).values(data=data, revision=revision + 1))
        if changed.rowcount != 1:
            db.rollback()
            raise HTTPException(409, "目标刚刚更新，请重新读取后核对。")
        db.commit()
        return {"revision": revision + 1, "preferences": data}


def receipt(data: dict, request, revision: int) -> bool:
    """Return true for an identical retry; reject reuse and stale writers."""
    body = request.model_dump(mode="json")
    digest = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    previous = data.get("operations", {}).get(str(request.request_id))
    if previous:
        if previous != digest:
            raise HTTPException(409, "同一次保存的内容已变化，请重新打开学习记录。")
        return True
    if request.revision != revision:
        raise HTTPException(409, "另一页面已更新记录。请保留输入后重新打开，避免覆盖新进度。")
    data["operations"] = {**dict(list(data.get("operations", {}).items())[-39:]), str(request.request_id): digest}
    return False


def commit_data(db, model, row, data):
    changed = db.execute(update(model).where(model.id == row.id, model.user_id == row.user_id,
        model.notebook_id == row.notebook_id, model.revision == row.revision).values(data=data, revision=row.revision + 1))
    if changed.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "另一页面刚更新了记录，请保留输入后重新打开。")
    db.commit()
    db.refresh(row)


def overview(user: str, notebook: str) -> dict:
    check(user, notebook)
    result = profile(user, notebook)
    prefs = result["preferences"]
    current = now().isoformat()
    with session() as db:
        words = db.scalars(select(VocabularyCard).where(VocabularyCard.user_id == user, VocabularyCard.notebook_id == notebook)).all()
        readings = db.scalars(select(ReadingTraining).where(ReadingTraining.user_id == user, ReadingTraining.notebook_id == notebook)).all()
        practices = db.scalars(select(Cet6Practice).where(Cet6Practice.user_id == user, Cet6Practice.notebook_id == notebook)).all()
        pending = sorted([r for r in readings if r.data["phase"] != "done"], key=lambda r: r.data.get("updated_at", ""), reverse=True)
        unfinished = sorted([p for p in practices if p.data.get("phase") != "done"], key=lambda r: r.data.get("updated_at", ""), reverse=True)
        active_words = sorted([w for w in words if w.data.get("active")], key=lambda w: w.data.get("updated_at", ""), reverse=True)
        word_due = sum(any(t.get("due_at", "z") <= current for t in w.data.get("tracks", {}).values()) for w in words)
        reading_due = [r for r in readings if r.data.get("review", {}).get("due_at", "z") and r.data.get("review", {}).get("due_at", "z") <= current]
        practice_due = [p for p in practices if p.data.get("due_at", "z") <= current]
        recent = sorted([{"kind": "reading", "at": r.data["first"]["submitted_at"], "independent": not r.data["first"].get("used_help"),
            "ratio": r.data["first"]["correct"] / r.data["first"]["total"]} for r in readings if r.data.get("first")] +
            [{"kind": p.data["kind"], "at": p.data["first"]["submitted_at"], "independent": not p.data["first"].get("used_help")} for p in practices if p.data.get("first")],
            key=lambda r: r["at"], reverse=True)[:10]
        if pending:
            recommended = {"kind": "reading", "id": pending[0].id, "title": "接着完成上次的阅读", "reason": "已有首次作答或订正尚未完成，先接上原来的思路。"}
        elif unfinished:
            recommended = {"kind": unfinished[0].data["kind"], "id": unfinished[0].task_id, "title": "继续上次的练习", "reason": "初稿和修改记录已保存在这门课程中。"}
        elif active_words:
            recommended = {"kind": "vocabulary", "id": active_words[0].entry_id, "title": "接着完成上次的词卡", "reason": "上次词卡的回忆或核对尚未完成，可以继续原来的义项。"}
        elif word_due:
            recommended = {"kind": "vocabulary", "title": "先回忆几张到期词卡", "reason": "这些词卡到了你上次安排的时间；今天只取一小组，其他记录保留。"}
        elif reading_due:
            recommended = {"kind": "reading", "id": reading_due[0].id, "title": "独立重做一段阅读", "reason": "上次订正后已经隔了一段时间，先隐藏解析再检查。"}
        elif practice_due:
            recommended = {"kind": practice_due[0].data["kind"], "id": practice_due[0].task_id, "title": "重新独立练一次", "reason": "已到复习时间，旧初稿保留，重新作答后再比较。"}
        else:
            choices = prefs["focus"] or (["vocabulary", "listening", "reading", "writing", "translation"] if prefs["mode"] == "foundation" else ["listening", "reading", "writing", "translation", "vocabulary"])
            seen = [r["kind"] for r in recent[:4]]
            kind = next((k for k in choices if k not in seen), choices[0])
            reason = "先按你选择的重点安排，并穿插近期较少练到的内容。" if prefs["focus"] else "还没有足够练习记录，先用短练了解自己的卡点。"
            independent_reading = [r for r in recent if r["kind"] == "reading" and r["independent"]]
            if not prefs["focus"] and independent_reading and independent_reading[0]["ratio"] < .6 and (not recent or recent[0]["kind"] != "reading"):
                kind, reason = "reading", "最近一次自述独立阅读有较多错题，建议换一段短文核对原因；这不是能力定级。"
            if not recent and not prefs["focus"] and prefs["listening_score"] is not None and prefs["reading_score"] is not None:
                kind = "listening" if prefs["listening_score"] < prefs["reading_score"] else "reading"
                reason = "先参考你填写的听力、阅读成绩安排；之后用实际练习修正建议。"
            recommended = {"kind": kind, "title": f"开始一小段{LABELS[kind]}学习", "reason": reason}
    return {**result, "recommendation": recommended, "server_time": current,
        "daily_new_limit": prefs["daily_new_words"], "review_minutes": min(10, max(2, prefs["daily_minutes"] // 3)),
        "stats": {"collected": sum(bool(w.data.get("collected")) for w in words), "word_due": word_due,
                  "reading_due": len(reading_due), "practice_due": len(practice_due)}, "recent": recent[:5]}

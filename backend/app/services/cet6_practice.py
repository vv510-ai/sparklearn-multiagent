"""Small authored exercises: first attempt, revision and delayed reattempt."""
import copy
import datetime as dt
import json
from functools import lru_cache
from pathlib import Path
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from ..models.db import session
from ..models.entities import Cet6Practice
from ..schemas.cet6 import PracticeAction
from . import cet6_learning as learning


@lru_cache(maxsize=1)
def tasks():
    return {t["id"]: t for t in json.loads((Path(__file__).parents[1] / "data" / "cet6_practice_v1.json").read_text(encoding="utf-8"))}


def _task(item):
    if item not in tasks():
        raise HTTPException(404, "练习不存在。")
    return tasks()[item]


def _find(db, user, notebook, item):
    return db.scalar(select(Cet6Practice).where(Cet6Practice.id == learning.stable_id("practice", user, notebook, item),
        Cet6Practice.user_id == user, Cet6Practice.notebook_id == notebook))


def public(row, task):
    data = row.data if row else {"phase": "answer", "answer": "", "history": []}
    material = {k: v for k, v in task.items() if k not in {"answer", "reference", "checklist"}}
    if task["kind"] == "listening":
        material["audio_url"] = f"/static/cet6/{task['id']}.mp3"
        if data["phase"] == "answer":
            material.pop("speech_text", None)
    if data["phase"] in {"feedback", "done"}:
        material.update({k: task[k] for k in ("reference", "checklist")})
        if task["kind"] == "listening":
            material["answer"] = task["answer"]
    result = {"task": material, "revision": row.revision if row else 0,
        **{k: v for k, v in data.items() if k not in {"operations", "kind"}}}
    if data["phase"] == "answer":
        result["history"] = [{"finished_at": h.get("finished_at")} for h in data.get("history", [])]
    return result


def catalogue(user, notebook):
    learning.check(user, notebook)
    with session() as db:
        return {"items": [{k: t[k] for k in ("id", "kind", "title", "minutes", "source")} |
            {"progress": public(r, t) if (r := _find(db, user, notebook, t["id"])) else None} for t in tasks().values()]}


def detail(user, notebook, item):
    learning.check(user, notebook)
    with session() as db:
        return public(_find(db, user, notebook, item), _task(item))


def act(user, notebook, item, req: PracticeAction):
    learning.check(user, notebook)
    task = _task(item)
    with session() as db:
        row = _find(db, user, notebook, item)
        if row is None:
            if req.revision:
                raise HTTPException(409, "练习记录已变化，请重新打开。")
            row = Cet6Practice(id=learning.stable_id("practice", user, notebook, item), user_id=user, notebook_id=notebook,
                task_id=item, revision=0, data={"phase": "answer", "answer": "", "history": [], "kind": task["kind"], "started_at": learning.now().isoformat()})
            db.add(row)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                row = _find(db, user, notebook, item)
        data = copy.deepcopy(row.data)
        if learning.receipt(data, req, row.revision):
            return public(row, task)
        current = learning.now()
        phase = data["phase"]
        if req.action == "draft":
            if phase == "done":
                raise HTTPException(409, "本次练习已完成，请先重新开始。")
            if phase == "answer":
                data["answer"] = req.answer
                data["used_help"] = data.get("used_help", False) or req.used_help
                data["timed"] = req.timed
            else:
                data.update(revision_text=req.revision_text, reflection=req.reflection)
        elif req.action == "submit":
            if phase != "answer":
                raise HTTPException(409, "首次作答已保存，不能覆盖。")
            if (task["kind"] == "listening" and req.answer not in {str(i) for i in range(len(task["options"]))}) or (task["kind"] != "listening" and len(req.answer.strip()) < 10):
                raise HTTPException(422, "请先完成自己的作答，再查看参考。")
            first = {"answer": req.answer, "submitted_at": current.isoformat(), "used_help": data.get("used_help", False) or req.used_help,
                "timed": req.timed, "elapsed_seconds": max(0, int((current - dt.datetime.fromisoformat(data["started_at"])).total_seconds()))}
            if task["kind"] == "listening":
                first["correct"] = req.answer == task["answer"]
            data.update(first=first, phase="feedback", answer=req.answer, revision_text="", reflection="")
        elif req.action == "finish":
            if phase != "feedback":
                raise HTTPException(409, "请先提交作答并完成订正。")
            if len(req.reflection.strip()) < 3 or (task["kind"] != "listening" and len(req.revision_text.strip()) < 10):
                raise HTTPException(422, "请保留修改稿，并记下一处修改或重听后的发现。")
            due = data.get("due_at")
            early = bool(due and due > current.isoformat())
            if not early:
                due = (current + dt.timedelta(days=1 if data["first"]["used_help"] else min(7, 1 + len(data["history"]) * 2))).isoformat()
            data.update(phase="done", revision_text=req.revision_text, reflection=req.reflection,
                due_at=due, last_early=early, finished_at=current.isoformat())
        elif req.action == "restart":
            if phase != "done":
                raise HTTPException(409, "当前练习尚未完成，请先继续。")
            history = (data["history"] + [{k: data.get(k) for k in ("first", "revision_text", "reflection", "finished_at")}])[-30:]
            data = {"kind": task["kind"], "phase": "answer", "answer": "", "history": history,
                "due_at": data.get("due_at"), "used_help": req.used_help, "started_at": current.isoformat(), "operations": data["operations"]}
        data["updated_at"] = current.isoformat()
        learning.commit_data(db, Cet6Practice, row, data)
        return public(row, task)

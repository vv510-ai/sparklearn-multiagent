"""Official-source viewer and private answer sheets, not a sealed scored exam."""
import copy
import datetime as dt
import json
from functools import lru_cache
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..models.db import session
from ..models.entities import Cet6PaperAttempt
from ..schemas.cet6 import PaperAction
from . import cet6_learning as learning


@lru_cache(maxsize=1)
def papers():
    return {p["id"]: p for p in json.loads((Path(__file__).parents[1] / "data" / "cet6_papers_v1.json").read_text(encoding="utf-8"))}


def _paper(item):
    if item not in papers():
        raise HTTPException(404, "这份试卷尚未收录。")
    return papers()[item]


def _find(db, user, notebook, item):
    return db.scalar(select(Cet6PaperAttempt).where(Cet6PaperAttempt.id == learning.stable_id("paper", user, notebook, item),
        Cet6PaperAttempt.user_id == user, Cet6PaperAttempt.notebook_id == notebook))


def _initial():
    return {"phase": "answer", "answers": {}, "writing": "", "translation": "", "reflection": "", "used_help": False,
        "history": [], "started_at": learning.now().isoformat()}


def _public(row, paper):
    data = copy.deepcopy(row.data) if row else _initial()
    data.pop("operations", None)
    info = {k: copy.deepcopy(v) for k, v in paper.items() if k != "questions"}
    info["questions"] = [{k: v for k, v in q.items() if data["phase"] == "feedback" or k not in {"answer", "explanation"}} for q in paper["questions"]]
    return {**data, "revision": row.revision if row else 0, "paper": info}


def catalogue(user, notebook):
    learning.check(user, notebook)
    with session() as db:
        return {"items": [{k: p[k] for k in ("id", "title", "source_type", "source_url", "coverage", "checked_on", "audio_status")} |
            {"progress": {"phase": r.data["phase"], "answered": len(r.data["answers"])} if (r := _find(db, user, notebook, p["id"])) else None} for p in papers().values()]}


def detail(user, notebook, item):
    learning.check(user, notebook)
    with session() as db:
        return _public(_find(db, user, notebook, item), _paper(item))


def act(user, notebook, item, req: PaperAction):
    learning.check(user, notebook)
    paper = _paper(item)
    questions = {str(q["number"]): q for q in paper["questions"]}
    if any(number not in questions or answer not in questions[number]["options"] for number, answer in req.answers.items()):
        raise HTTPException(422, "存在无效的题号或选项，请重新核对答题卡。")
    with session() as db:
        row = _find(db, user, notebook, item)
        if row is None:
            if req.revision:
                raise HTTPException(409, "记录已变化，请保留输入后重新打开。")
            row = Cet6PaperAttempt(id=learning.stable_id("paper", user, notebook, item), user_id=user,
                notebook_id=notebook, paper_id=item, revision=0, data=_initial())
            db.add(row)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                row = _find(db, user, notebook, item)
        data = copy.deepcopy(row.data)
        if learning.receipt(data, req, row.revision):
            return _public(row, paper)
        now = learning.now()
        if req.action == "restart":
            if data["phase"] != "feedback":
                raise HTTPException(409, "请先提交本次阅读作答。")
            previous = {k: data[k] for k in ("first", "reflection", "writing", "translation")}
            data = {**_initial(), "history": (data["history"] + [previous])[-20:], "operations": data["operations"]}
        else:
            if data["phase"] == "feedback" and req.answers != data["answers"]:
                raise HTTPException(409, "首次答案已保存，不能覆盖；可以记录订正或开始新一轮。")
            data.update(answers=dict(req.answers), writing=req.writing, translation=req.translation,
                reflection=req.reflection, used_help=data["used_help"] or req.used_help)
            if req.action == "submit":
                if data["phase"] != "answer":
                    raise HTTPException(409, "这次阅读作答已提交。")
                if not req.answers:
                    raise HTTPException(422, "请至少完成一道阅读题，再提交核对。")
                correct = sum(answer == questions[number]["answer"] for number, answer in req.answers.items())
                data.update(phase="feedback", due_at=(now + dt.timedelta(days=1)).isoformat(), first={
                    "answers": dict(req.answers), "writing": req.writing, "translation": req.translation,
                    "answered": len(req.answers), "correct": correct, "total": len(questions),
                    "submitted_at": now.isoformat(), "used_help": data["used_help"],
                    "elapsed_seconds": max(0, int((now - dt.datetime.fromisoformat(data["started_at"])).total_seconds()))})
        data["updated_at"] = now.isoformat()
        learning.commit_data(db, Cet6PaperAttempt, row, data)
        return _public(row, paper)

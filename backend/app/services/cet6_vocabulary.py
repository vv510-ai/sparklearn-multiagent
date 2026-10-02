"""Source-versioned vocabulary and independent, per-sense recall records."""
from __future__ import annotations
import copy
import json
import re
from functools import lru_cache
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from ..models.db import session
from ..models.entities import VocabularyCard, ReadingTraining
from ..schemas.cet6 import WordAction
from . import cet6_learning as learning
from . import vocabulary_scheduler


@lru_cache(maxsize=1)
def corpus():
    return json.loads((Path(__file__).parents[1] / "data" / "cet6_vocabulary_v1.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def entries():
    return {e["id"]: e for e in corpus()["entries"]}


def entry(item):
    if item not in entries():
        raise HTTPException(404, "词条不存在，请重新搜索词库。")
    return entries()[item]


def _key(user, notebook, item, sense):
    return learning.stable_id("vocab", user, notebook, f"{item}:{sense}")


def _find(db, user, notebook, item, sense):
    return db.scalar(select(VocabularyCard).where(VocabularyCard.id == _key(user, notebook, item, sense),
        VocabularyCard.user_id == user, VocabularyCard.notebook_id == notebook))


def _public(row, sense):
    data = row.data if row else {}
    result = {"revision": row.revision if row else 0, "sense_id": sense, "collected": bool(data.get("collected")),
        "contexts": data.get("contexts", []), "tracks": data.get("tracks", {}), "active": data.get("active"), "last": data.get("last")}
    active = data.get("active")
    if active and active["revealed"]:
        old = data.get("tracks", {}).get(active["mode"], {})
        result["rating_options"] = {rating: vocabulary_scheduler.schedule(old, active, rating, learning.now(), f"{row.id}:{active['mode']}")[0]["due_at"]
                                    for rating in vocabulary_scheduler.RATINGS}
    return result


def detail(user, notebook, item):
    learning.check(user, notebook)
    e = entry(item)
    with session() as db:
        cards = [_public(_find(db, user, notebook, item, s["id"]), s["id"]) for s in e["senses"]]
        due = sorted((t["due_at"], c["sense_id"], mode) for c in cards for mode, t in c["tracks"].items()
                     if t.get("due_at", "z") <= learning.now().isoformat())
        next_review = {"sense_id": due[0][1], "mode": due[0][2]} if due else {
            "sense_id": next((c["sense_id"] for c in cards if not c["tracks"]), cards[0]["sense_id"] if cards else ""), "mode": "meaning"}
        return {"entry": e, "version": corpus()["version"], "cards": cards, "next_review": next_review}


def catalogue(user, notebook, query="", group="all", view="all", offset=0, limit=30):
    learning.check(user, notebook)
    current = learning.now().isoformat()
    prefs = learning.profile(user, notebook)["preferences"]
    with session() as db:
        cards = db.scalars(select(VocabularyCard).where(VocabularyCard.user_id == user, VocabularyCard.notebook_id == notebook)).all()
        collected = {c.entry_id for c in cards if c.data.get("collected")}
        learnt = {c.entry_id for c in cards if c.data.get("tracks")}
        due = {c.entry_id for c in cards if any(t.get("due_at", "z") <= current for t in c.data.get("tracks", {}).values())}
        active = {c.entry_id for c in cards if c.data.get("active")}
    q = query.strip().casefold()
    values = [e for e in entries().values() if (group == "all" or e["level"] == group)
        and (not q or q in (e["word"] + " " + " ".join(e.get("variants", [])) + " " + " ".join(e.get("derivatives", []))).casefold())]
    if q:
        values.sort(key=lambda e: (e["word"].casefold() != q, not e["word"].casefold().startswith(q), e["word"].casefold()))
    if view == "mine":
        values = [e for e in values if e["id"] in collected]
    elif view == "today":
        values = [e for e in values if e["senses"] and (e["id"] in active or e["id"] in due or e["id"] not in learnt)]
        values.sort(key=lambda e: (e["id"] not in active, e["id"] not in due, e["level"] != ("foundation" if prefs["mode"] == "foundation" else "cet6"), e.get("frequency") or 999999, e["id"]))
        values = values[:min(20, max(3, prefs["daily_minutes"] // 2))]
    return {"version": corpus()["version"], "manifest": corpus()["manifest"], "total": len(values), "offset": offset,
        "items": [{k: e[k] for k in ("id", "word", "level", "phonetic", "variants", "derivatives")} |
            {"meaning": "" if view == "today" else e["senses"][0]["definition"] if e["senses"] else "释义待补，可查看词表原页", "collected": e["id"] in collected,
             "status": "回忆未完成" if e["id"] in active else "到期复习" if e["id"] in due else "复习中" if e["id"] in learnt else "未练习"} |
            ({"word": "", "phonetic": "", "variants": [], "derivatives": []} if view == "today" and e["id"] in due | active else {}) for e in values[offset:offset + limit]]}


def act(user: str, notebook: str, item: str, req: WordAction):
    learning.check(user, notebook)
    e = entry(item)
    sense = next((s for s in e["senses"] if s["id"] == req.sense_id), None)
    if req.version != corpus()["version"] or not sense:
        raise HTTPException(409, "词库版本或义项已变化，请重新打开词条。")
    with session() as db:
        row = _find(db, user, notebook, item, req.sense_id)
        if row is None:
            if req.revision:
                raise HTTPException(409, "词卡已变化，请重新打开。")
            row = VocabularyCard(id=_key(user, notebook, item, req.sense_id), user_id=user, notebook_id=notebook,
                entry_id=item, sense_id=req.sense_id, data={}, revision=0)
            db.add(row)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                row = _find(db, user, notebook, item, req.sense_id)
        data = copy.deepcopy(row.data)
        if learning.receipt(data, req, row.revision):
            return _public(row, req.sense_id)
        current = learning.now()
        tracks = data.setdefault("tracks", {})
        if req.action == "collect":
            if req.question_id and not req.reading_id:
                raise HTTPException(422, "题目定位需要对应的原阅读。")
            data["collected"] = True
            context = {"text": req.context.strip(), "note": req.context_note.strip(), "reading_id": req.reading_id, "source": "自己提供的语境", "saved_at": current.isoformat()}
            if req.reading_id:
                reading = db.scalar(select(ReadingTraining).where(ReadingTraining.id == req.reading_id,
                    ReadingTraining.user_id == user, ReadingTraining.notebook_id == notebook))
                if not reading:
                    raise HTTPException(404, "原阅读不属于当前课程。")
                if not req.context.strip() or req.context.strip() not in "\n\n".join(reading.data["material"]["paragraphs"]):
                    raise HTTPException(422, "请保留文章中的完整原句，不要改写成来源原文。")
                context["source"] = reading.data["material"]["title"]
                if req.question_id:
                    questions = reading.data["material"]["questions"]
                    index = next((i for i, q in enumerate(questions) if q["id"] == req.question_id), None)
                    if index is None:
                        raise HTTPException(422, "这道题不属于当前阅读。")
                    context.update(question_id=req.question_id, question_number=index + 1, question_prompt=questions[index]["prompt"])
            if context["text"] or context["note"]:
                previous = data.setdefault("contexts", [])
                if not any(all(c.get(k, "") == context.get(k, "") for k in ("text", "note", "reading_id", "question_id")) for c in previous):
                    data["contexts"] = (previous + [context])[-20:]
        elif req.action == "start":
            if not data.get("active"):
                track = tracks.get(req.mode, {})
                data["active"] = {"mode": req.mode, "started_at": current.isoformat(), "revealed": False,
                    "early": bool(track.get("due_at") and track["due_at"] > current.isoformat()), "used_help": req.used_help}
        elif req.action == "reveal":
            active = data.get("active")
            if not active or active["revealed"]:
                raise HTTPException(409, "请先开始回忆，或继续完成当前词卡。")
            active.update(revealed=True, answer=req.answer.strip(), used_help=bool(active["used_help"] or req.used_help))
            if active["mode"] == "spelling":
                normalize = lambda s: re.sub(r"\s+", " ", s.strip().casefold())
                active["correct"] = normalize(req.answer) in {normalize(v) for v in [e["word"], *e["variants"]]}
        elif req.action == "rate":
            active = data.get("active")
            if not active or not active["revealed"]:
                raise HTTPException(409, "请先回忆并核对释义，再记录结果。")
            mode = active["mode"]
            old = tracks.get(mode, {})
            passed = req.rating != "again" and (mode != "spelling" or active.get("correct", False))
            helped = active["used_help"] or req.used_help
            track, scheduling = vocabulary_scheduler.schedule(old, {**active, "used_help": helped}, req.rating, current, f"{row.id}:{mode}")
            last = {**active, "rating": req.rating, "used_help": helped, "submitted_at": current.isoformat(),
                "passed": passed, "basis": "拼写核对" if mode == "spelling" else "学习者自评", "due_at": track["due_at"],
                "scheduler": track.get("scheduler", "legacy-fixed"), **scheduling}
            tracks[mode] = track
            data["last"] = last
            data["history"] = (data.get("history", []) + [last])[-100:]
            data["active"] = None
        data["updated_at"] = current.isoformat()
        learning.commit_data(db, VocabularyCard, row, data)
        return _public(row, req.sense_id)

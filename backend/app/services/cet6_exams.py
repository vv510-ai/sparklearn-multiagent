"""Versioned section attempts with source-bound keys and recoverable model feedback."""
from __future__ import annotations

import asyncio
import copy
import datetime as dt
import logging
from urllib.parse import quote

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..config import get_settings, is_demo
from ..data.cet6_exam_pilot import pilot, VERSION, REPOSITORY, COMMIT, SYLLABUS
from ..llm.spark_client import llm_complete, parse_json
from ..models.db import session
from ..models.entities import Cet6PaperAttempt
from ..prompt_templates import invoke_learning_prompt
from . import cet6_learning as learning

KINDS = {"listening", "reading", "writing", "translation"}


def _pack(paper_id, kind):
    paper = pilot()
    if paper_id != paper["id"] or kind not in KINDS:
        raise HTTPException(404, "这套题的本板块尚未接入本站答题。")
    return paper, paper["blocks"][kind]


def _id(user, notebook, paper, kind):
    return learning.stable_id("exam-section", user, notebook, f"{paper}:{kind}")


def _find(db, user, notebook, paper, kind):
    return db.scalar(select(Cet6PaperAttempt).where(Cet6PaperAttempt.id == _id(user, notebook, paper, kind),
        Cet6PaperAttempt.user_id == user, Cet6PaperAttempt.notebook_id == notebook))


def _initial():
    return dict(version=VERSION, phase="answer", answers={}, text="", history=[], started_at=learning.now().isoformat())


def _public(row, paper, block, kind):
    data = copy.deepcopy(row.data) if row else _initial()
    data.pop("operations", None)
    history = data.pop("history", [])
    material = {k: copy.deepcopy(v) for k,v in paper.items() if k not in {"blocks", "crosscheck_url"}}
    material.update({k: copy.deepcopy(v) for k,v in block.items() if k not in {"questions", "rubric"}})
    material["kind"] = kind
    material["paper_title"] = paper["title"]
    feedback = data["phase"] == "feedback"
    material["questions"] = [copy.deepcopy(q) if feedback else {k:copy.deepcopy(q[k]) for k in ("number","choices","page","group")} for q in block["questions"]]
    if feedback:
        material["crosscheck_url"] = paper["crosscheck_url"]
    return {**data, "revision": row.revision if row else 0, "material": material, "history_count":len(history)}


def catalogue(user, notebook):
    learning.check(user, notebook)
    paper = pilot()
    with session() as db:
        progress = {}
        for kind in KINDS:
            row = _find(db, user, notebook, paper["id"], kind)
            progress[kind] = None if row is None else {"phase":row.data["phase"], "answered":len(row.data["answers"]), "updated_at":row.data.get("updated_at")}
    items = []
    for year, month in [(2026,6),(2025,12),(2025,6),(2024,12),(2024,6)]:
        for number in [1,2,3]:
            item = dict(id=f"cet6-{year}-{month:02}-{number}", year=year, month=month, set=number,
                title=f"{year} 年 {month} 月 · 第 {number} 套", ready=(year,month,number)==(2026,6,1),
                source_url=f"{REPOSITORY}/tree/{COMMIT}/{quote(f'六级真题/{year}.{month:02}')}")
            if item["ready"]:
                item.update(progress=progress, source_url=paper["source_url"], counts={k:len(v["questions"]) or 1 for k,v in paper["blocks"].items()})
            items.append(item)
    return {"items":items,"version":VERSION,"years":[2026,2025,2024],"note":"本站答题样板：2026年6月第1套。其他套次保留原站入口，未标为已接入。"}


def detail(user, notebook, paper_id, kind):
    learning.check(user, notebook)
    paper, block = _pack(paper_id, kind)
    with session() as db:
        return _public(_find(db,user,notebook,paper_id,kind),paper,block,kind)


def act(user, notebook, paper_id, kind, req):
    learning.check(user, notebook)
    paper, block = _pack(paper_id, kind)
    if req.version != VERSION:
        raise HTTPException(409, "题卷版本已变化，请保留输入并重新读取。")
    questions = {str(q["number"]):q for q in block["questions"]}
    if any(n not in questions or a not in questions[n]["choices"] for n,a in req.answers.items()):
        raise HTTPException(422, "答案包含不属于本板块的题号或选项。")
    if questions and req.text or not questions and req.answers:
        raise HTTPException(422, "作答类型与所选板块不一致。")
    with session() as db:
        row = _find(db,user,notebook,paper_id,kind)
        if row is None:
            if req.revision:
                raise HTTPException(409, "作答记录已变化，请重新读取。")
            row = Cet6PaperAttempt(id=_id(user,notebook,paper_id,kind), user_id=user, notebook_id=notebook,
                paper_id=f"exam:{paper_id}:{kind}", revision=0, data=_initial())
            db.add(row)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                row = _find(db,user,notebook,paper_id,kind)
        data = copy.deepcopy(row.data)
        if learning.receipt(data,req,row.revision):
            return _public(row,paper,block,kind)
        if data["version"] != VERSION:
            raise HTTPException(409, "旧作答对应另一题卷版本，请保留记录后联系维护者。")
        if req.action == "restart":
            if data["phase"] != "feedback":
                raise HTTPException(409,"请先完成本轮提交。")
            data = {**_initial(),"history":(data["history"]+[data["first"]])[-20:],"operations":data["operations"]}
        else:
            if data["phase"] != "answer":
                raise HTTPException(409,"本轮已提交，首次作答已保留；请使用重新作答。")
            data.update(answers=dict(req.answers),text=req.text)
            if req.action == "submit":
                if questions:
                    missing = len(questions)-len(req.answers)
                    if missing and not req.allow_incomplete:
                        raise HTTPException(422,f"还有 {missing} 题未作答，请检查漏题或明确选择仍然提交。")
                    if not req.answers:
                        raise HTTPException(422,"请至少作答一题。")
                elif len(req.text.strip()) < 10:
                    raise HTTPException(422,"请先输入自己的作答，再提交分析。")
                first = dict(answers=dict(req.answers),text=req.text,submission_id=str(req.request_id),
                    submitted_at=learning.now().isoformat(),version=VERSION)
                if questions:
                    first.update(correct=sum(req.answers.get(n)==q["answer"] for n,q in questions.items()),
                        answered=len(req.answers),total=len(questions))
                else:
                    data["review"] = {"status":"pending"}
                data.update(phase="feedback",first=first)
        data["updated_at"] = learning.now().isoformat()
        learning.commit_data(db,Cet6PaperAttempt,row,data)
        return _public(row,paper,block,kind)


class RevisionSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid",str_strip_whitespace=True)
    quote: str = Field(min_length=1,max_length=1200)
    replacement: str = Field(min_length=1,max_length=1600)
    reason: str = Field(min_length=5,max_length=800)


class Dimension(BaseModel):
    model_config = ConfigDict(extra="forbid",str_strip_whitespace=True)
    name: str = Field(min_length=1,max_length=50)
    comment: str = Field(min_length=5,max_length=600)


class Review(BaseModel):
    model_config = ConfigDict(extra="forbid",str_strip_whitespace=True)
    summary: str = Field(min_length=10,max_length=1000)
    strengths: list[str] = Field(max_length=3)
    priorities: list[str] = Field(min_length=1,max_length=3)
    dimensions: list[Dimension] = Field(min_length=4,max_length=4)
    suggestions: list[RevisionSuggestion] = Field(max_length=5)


async def review(user, notebook, paper_id, kind):
    """Claim work atomically; late results cannot attach to a newer submission."""
    learning.check(user,notebook)
    paper, block = _pack(paper_id,kind)
    if kind not in {"writing","translation"}:
        raise HTTPException(422,"听力和阅读使用已核验的题目解析。")
    with session() as db:
        row = _find(db,user,notebook,paper_id,kind)
        if row is None or row.data["phase"] != "feedback":
            raise HTTPException(409,"请先提交自己的作答。")
        data = copy.deepcopy(row.data)
        prior = data.get("review",{})
        if prior.get("status") == "ready":
            return _public(row,paper,block,kind)
        if prior.get("status") == "running" and (learning.now()-dt.datetime.fromisoformat(prior["started_at"])).total_seconds()<150:
            return _public(row,paper,block,kind)
        submission = data["first"]["submission_id"]
        learner_text = data["first"]["text"]
        if is_demo():
            data["review"] = {"status":"unavailable","message":"当前演示环境未连接真实批改模型；原稿已保存，可按原卷要求自查。"}
            learning.commit_data(db,Cet6PaperAttempt,row,data)
            return _public(row,paper,block,kind)
        data["review"] = {"status":"running","started_at":learning.now().isoformat()}
        learning.commit_data(db,Cet6PaperAttempt,row,data)
        started_at = data["review"]["started_at"]
    try:
        call = invoke_learning_prompt("english.cet6_feedback",kind=block["title"],rubric=block["rubric"],
            dimensions="、".join(block["dimensions"]),answer=learner_text)
        from .model_preferences import resolve
        route = resolve(call.prompt)
        settings = get_settings()
        model = route.get("model") if route else (settings.deepseek_model if settings.llm_provider=="deepseek" else settings.llm_provider)
        raw = await asyncio.wait_for(llm_complete(call.prompt,system=call.system,temperature=.2,json_mode=True,
            max_tokens=6000,allow_model_fallback=False,allow_mock_fallback=False),timeout=100)
        checked = Review.model_validate(parse_json(raw))
        normalize = lambda value: " ".join(value.split())
        if any(normalize(s.quote) not in normalize(learner_text) for s in checked.suggestions):
            raise ValueError("feedback quoted text absent from learner answer")
        if [d.name for d in checked.dimensions] != block["dimensions"]:
            raise ValueError("feedback rubric differs from requested dimensions")
        result = {"status":"ready","model":model,"content":checked.model_dump(),"rubric_source":SYLLABUS,
            "generated_at":learning.now().isoformat(),"note":"AI 练习反馈，非官方评分；建议逐项对照原题与原稿。"}
    except (Exception, asyncio.CancelledError) as exc:
        logging.getLogger(__name__).warning("CET6 review rejected (%s)", type(exc).__name__)
        result = {"status":"failed","message":"本次分析未通过检查或服务暂不可用。原稿已保存，可以重试分析。"}
    with session() as db:
        row = _find(db,user,notebook,paper_id,kind)
        # A new attempt, submission, or a timed-out claim supersedes this one.
        if row and row.data.get("first",{}).get("submission_id")==submission and row.data.get("review",{}).get("started_at")==started_at:
            data = copy.deepcopy(row.data)
            data["review"] = result
            learning.commit_data(db,Cet6PaperAttempt,row,data)
        return _public(row,paper,block,kind)

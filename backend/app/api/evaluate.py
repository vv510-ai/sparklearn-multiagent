"""评估闭环 API:
POST /api/eval/support —— 作答后按需获取提示或揭晓答案;
POST /api/eval/submit —— 提交答题:逐题比对 → BKT 更新掌握度 → 错因标签回写画像
                          → 路径重排 → 返回评估报告(学习闭环核心);
GET  /api/eval/report —— 学情报告(画像 + 掌握度雷达数据 + 近期事件)。"""
from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from ..agents.eval_agent import evaluate_answers
from ..models.db import session
from ..models.entities import QuizAttempt, Resource
from ..schemas.core import EvalSubmit, EvalSupportRequest
from ..services.knowledge_graph import canonical_kp_id, kp_name
from ..services.profile_service import ensure_user, get_profile, recent_events

router = APIRouter(prefix="/api/eval", tags=["eval"])

MISCONCEPTION_TAGS = {
    "概念没记牢",
    "条件看漏了",
    "步骤顺序混乱",
    "选项辨析错误",
    "计算或推导失误",
    "会做但不熟练",
    "还不确定",
}


def _normalize_answer(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = text.replace("（", "(").replace("）", ")")
    return re.sub(r"[\s`'\".,，。:：;；、()（）\[\]【】]", "", text)


def _choice_letter(value: Any, options: list[Any] | None = None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    direct = re.match(r"^([A-D])(?:[.、:：\s]|$)", raw, re.IGNORECASE)
    if direct:
        return direct.group(1).upper()
    expected = _normalize_answer(re.sub(r"^[A-D][.、:：\s]*", "", raw, flags=re.IGNORECASE))
    for index, option in enumerate(options or []):
        option_text = re.sub(r"^[A-D][.、:：\s]*", "", str(option or ""), flags=re.IGNORECASE)
        if _normalize_answer(option_text) == expected:
            return chr(65 + index)
    return ""


def _judge_value(value: Any) -> bool | None:
    text = _normalize_answer(value)
    if text in {"对", "是", "正确", "true", "t", "yes", "y", "1"}:
        return True
    if text in {"错", "否", "错误", "false", "f", "no", "n", "0"}:
        return False
    return None


def _grade_answer(question: dict, answer: str) -> bool:
    """Deterministic backend grading.

    Objective questions compare against the stored answer. Subjective/design
    questions keep the existing local fallback rule used by QuizPlayer.
    """
    if not question:
        return False
    qtype = str(question.get("type") or "").strip()
    expected = question.get("answer", "")
    if not answer:
        return False
    if qtype == "single" or (qtype == "complexity" and question.get("options")):
        options = question.get("options") if isinstance(question.get("options"), list) else []
        return _choice_letter(answer, options) == _choice_letter(expected, options)
    if qtype == "judge":
        got = _judge_value(answer)
        want = _judge_value(expected)
        return got is not None and want is not None and got == want
    if qtype in {"fill", "complexity"}:
        return _normalize_answer(answer) == _normalize_answer(expected)
    return len(str(answer).strip()) >= 8


def _quiz_question(user_id: str, resource_id: str, question_id: str) -> dict:
    with session() as s:
        resource = s.get(Resource, resource_id)
        if not resource or resource.user_id != user_id or resource.kind != "quiz":
            raise HTTPException(404, "quiz resource not found")
        payload = resource.payload if isinstance(resource.payload, dict) else {}
        for question in payload.get("questions", []):
            if isinstance(question, dict) and question.get("id") == question_id:
                return question
    raise HTTPException(404, "quiz question not found")


def _hint_for(question: dict) -> str:
    """Return deterministic scaffolding without copying the stored answer."""
    qtype = str(question.get("type") or "").strip()
    if qtype == "single" or (qtype == "complexity" and question.get("options")):
        return "先逐项判断每个选项成立所需的条件，再排除与题干条件冲突的选项。"
    if qtype == "judge":
        return "把题干拆成“对象、条件、结论”三部分，检查是否存在一个反例。"
    if qtype == "fill":
        return "先回忆这个概念的定义句，答案通常是定义中不可替换的关键词。"
    if qtype == "complexity":
        return "先确定基本操作执行次数，再只保留随输入规模增长最快的项。"
    return "先写出核心定义，再按“已知条件 → 推理步骤 → 结论”组织答案。"


@router.post("/support")
async def support(req: EvalSupportRequest):
    """Human-in-the-loop support: attempt first, then hint or reveal."""
    ensure_user(req.user_id)
    if not req.attempt.strip():
        raise HTTPException(400, "请先写下你的尝试，再请求提示或揭晓")
    question = _quiz_question(req.user_id, req.quiz_resource_id, req.question_id)
    if req.mode == "hint":
        return {"mode": "hint", "question_id": req.question_id,
                "hint": _hint_for(question)}
    return {"mode": "reveal", "question_id": req.question_id,
            "expected": question.get("answer", ""),
            "explain": question.get("explain", ""),
            "error_tags": question.get("error_tags", [])}


@router.post("/submit")
async def submit(req: EvalSubmit):
    ensure_user(req.user_id)
    # 从题组资源还原每题的 kp / error_tags / 参考答案
    qmap: dict[str, dict] = {}
    with session() as s:
        r = s.get(Resource, req.quiz_resource_id)
        if r:
            payload = r.payload if isinstance(r.payload, dict) else {}
            qmap = {q["id"]: q for q in payload.get("questions", []) if q.get("id")}

    enriched = []
    for a in req.answers:
        q = qmap.get(a.question_id, {})
        correct = _grade_answer(q, a.answer)
        mastery_correct = correct and not a.revealed
        misconception = a.misconception if a.misconception in MISCONCEPTION_TAGS else ""
        if a.revealed and not misconception:
            raise HTTPException(400, f"揭晓题 {a.question_id} 需要先完成错因复盘")
        error_tags = list(q.get("error_tags", []) or []) if not mastery_correct else []
        if misconception and misconception not in error_tags and not mastery_correct:
            error_tags.append(misconception)
        kp = canonical_kp_id(q.get("kp") or req.kp)
        enriched.append({"question_id": a.question_id,
                         "kp": kp or "",
                         "correct": correct,
                         "mastery_correct": mastery_correct,
                         "answer": a.answer,
                         "expected": q.get("answer", ""),
                         "type": q.get("type", ""),
                         "difficulty": q.get("difficulty", 0),
                         "explain": q.get("explain", ""),
                         "error_tags": error_tags,
                         "hint_used": a.hint_used,
                         "revealed": a.revealed,
                         "misconception": misconception,
                         "support_level": ("revealed" if a.revealed else
                                           "hinted" if a.hint_used else "independent"),
                         "seconds": max(0.0, a.seconds)})
    n = len(enriched) or 1
    score = sum(e["correct"] for e in enriched) / n
    attempt_kp = canonical_kp_id(req.kp) or (enriched[0]["kp"] if enriched else "")
    support_summary = {
        "hinted": sum(bool(e["hint_used"]) for e in enriched),
        "revealed": sum(bool(e["revealed"]) for e in enriched),
        "independent": sum(e["support_level"] == "independent" for e in enriched),
        "misconceptions": [e["misconception"] for e in enriched if e["misconception"]],
    }
    behavior = {**req.behavior, "support": support_summary}
    with session() as s:
        s.add(QuizAttempt(user_id=req.user_id, quiz_resource_id=req.quiz_resource_id,
                          kp=attempt_kp,
                          score=round(score, 3),
                          detail={"answers": enriched,
                                  "submitted": [a.model_dump() for a in req.answers],
                                  "behavior": behavior}))
        s.commit()

    report = evaluate_answers(req.user_id, enriched)
    report["behavior"] = behavior
    return report


@router.get("/report")
async def report(user_id: str = Query("demo_user")):
    ensure_user(user_id)
    profile = get_profile(user_id)
    mastery = profile.get("knowledge_mastery") or {}
    radar = [{"kp": k, "name": kp_name(k), "mastery": round(float(v), 3)}
             for k, v in mastery.items()]
    radar.sort(key=lambda d: d["mastery"])
    with session() as s:
        attempts = (s.query(QuizAttempt).filter(QuizAttempt.user_id == user_id)
                    .order_by(QuizAttempt.id.desc()).limit(100).all())
    n_attempt = len(attempts)
    avg_score = round(sum(a.score for a in attempts) / n_attempt, 3) if n_attempt else None
    if not radar:
        raise HTTPException(404, "profile not found")
    return {"profile": profile, "radar": radar,
            "weakest": radar[:3], "strongest": radar[-3:][::-1],
            "attempts": {"total": n_attempt, "accuracy": avg_score},
            "events": recent_events(user_id, 20)}

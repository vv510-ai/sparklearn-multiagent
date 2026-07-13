"""评估闭环 API:
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
from ..schemas.core import EvalSubmit
from ..services.knowledge_graph import canonical_kp_id, kp_name
from ..services.profile_service import ensure_user, get_profile, recent_events

router = APIRouter(prefix="/api/eval", tags=["eval"])


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
        kp = canonical_kp_id(q.get("kp") or req.kp)
        enriched.append({"question_id": a.question_id,
                         "kp": kp or "",
                         "correct": correct,
                         "answer": a.answer,
                         "expected": q.get("answer", ""),
                         "type": q.get("type", ""),
                         "difficulty": q.get("difficulty", 0),
                         "explain": q.get("explain", ""),
                         "error_tags": q.get("error_tags", []) if not correct else []})
    n = len(enriched) or 1
    score = sum(e["correct"] for e in enriched) / n
    attempt_kp = canonical_kp_id(req.kp) or (enriched[0]["kp"] if enriched else "")
    with session() as s:
        s.add(QuizAttempt(user_id=req.user_id, quiz_resource_id=req.quiz_resource_id,
                          kp=attempt_kp,
                          score=round(score, 3),
                          detail={"answers": enriched,
                                  "submitted": [a.model_dump() for a in req.answers],
                                  "behavior": req.behavior}))
        s.commit()

    report = evaluate_answers(req.user_id, enriched)
    report["behavior"] = req.behavior
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

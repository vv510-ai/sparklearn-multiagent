"""评估闭环 API:
POST /api/eval/support —— 作答后按需获取提示或揭晓答案;
POST /api/eval/submit —— 提交答题:逐题比对 → BKT 更新掌握度 → 错因标签回写画像
                          → 路径重排 → 返回评估报告(学习闭环核心);
POST /api/eval/retest —— 对未形成独立掌握证据的题进行一次无提示复测;
GET  /api/eval/review-queue —— 获取今天到期的间隔复习题（不含答案）;
POST /api/eval/review —— 提交独立回忆并推进或重置复习间隔;
GET  /api/eval/evidence —— 可解释学习证据账本;
GET  /api/eval/report —— 学情报告(画像 + 掌握度雷达数据 + 近期事件)。"""
from __future__ import annotations

import re
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from ..agents import doc_agent, eval_agent as eval_agent_module, quiz_agent
from ..agents.eval_agent import evaluate_answers
from ..models.db import session
from ..models.entities import QuizAttempt, Resource, ReviewItem
from ..rag.ingest import validate_source_scope
from ..schemas.core import (EvalRetestRequest, EvalReviewRequest, EvalSubmit,
                            EvalSupportRequest, RemediationRequest)
from ..services.knowledge_graph import canonical_kp_id, kp_name
from ..services.learning_evidence import build_learning_evidence
from ..services.profile_service import ensure_user, get_profile, log_event, recent_events
from ..services.review_service import (apply_review_results, as_utc, review_queue,
                                       schedule_initial_reviews, utc_now)

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


def _resource_dict(resource: Resource) -> dict[str, Any]:
    return {
        "id": resource.id,
        "kind": resource.kind,
        "kp": resource.kp,
        "title": resource.title,
        "payload": resource.payload if isinstance(resource.payload, dict) else {},
        "citations": resource.citations if isinstance(resource.citations, list) else [],
        "created_at": resource.created_at.isoformat() if resource.created_at else None,
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


def _quiz_questions(user_id: str, resource_id: str) -> dict[str, dict]:
    with session() as s:
        resource = s.get(Resource, resource_id)
        if not resource or resource.user_id != user_id or resource.kind != "quiz":
            raise HTTPException(404, "quiz resource not found")
        payload = resource.payload if isinstance(resource.payload, dict) else {}
        return {
            str(question["id"]): question
            for question in payload.get("questions", [])
            if isinstance(question, dict) and question.get("id")
        }


def _quiz_question(user_id: str, resource_id: str, question_id: str) -> dict:
    question = _quiz_questions(user_id, resource_id).get(question_id)
    if question:
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
    qmap = _quiz_questions(req.user_id, req.quiz_resource_id)

    enriched = []
    for a in req.answers:
        q = qmap.get(a.question_id)
        if not q:
            raise HTTPException(400, f"题组中不存在题目 {a.question_id}")
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
                         "confidence": a.confidence,
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
        attempt = QuizAttempt(user_id=req.user_id, quiz_resource_id=req.quiz_resource_id,
                              kp=attempt_kp,
                              score=round(score, 3),
                              detail={"answers": enriched,
                                      "submitted": [a.model_dump() for a in req.answers],
                                      "behavior": behavior})
        s.add(attempt)
        s.commit()
        attempt_id = attempt.id

    report = evaluate_answers(req.user_id, enriched)
    scheduled_reviews = schedule_initial_reviews(
        req.user_id, req.quiz_resource_id, attempt_id, enriched,
    )
    report["behavior"] = behavior
    report["attempt_id"] = attempt_id
    report["retest"] = {
        "status": "ready" if any(not e["mastery_correct"] for e in enriched) else "not_needed",
        "eligible_question_ids": [e["question_id"] for e in enriched if not e["mastery_correct"]],
    }
    report["review"] = {"scheduled": scheduled_reviews}
    with session() as s:
        stored_attempt = s.get(QuizAttempt, attempt_id)
        if stored_attempt:
            detail = dict(stored_attempt.detail or {})
            detail["diagnosis"] = report.get("diagnosis") or {}
            stored_attempt.detail = detail
            s.commit()
    return report


@router.post("/remediation")
async def remediation(req: RemediationRequest):
    """Generate a source-grounded micro-lesson and a fresh transfer retest."""
    ensure_user(req.user_id)
    existing_doc: dict[str, Any] | None = None
    with session() as s:
        attempt = s.get(QuizAttempt, req.attempt_id)
        if not attempt or attempt.user_id != req.user_id:
            raise HTTPException(404, "quiz attempt not found")
        detail = dict(attempt.detail or {})
        diagnosis = detail.get("diagnosis") if isinstance(detail.get("diagnosis"), dict) else {}
        quiz_resource = s.get(Resource, attempt.quiz_resource_id)
        if not quiz_resource or quiz_resource.user_id != req.user_id:
            raise HTTPException(404, "quiz resource not found")
        quiz_payload = quiz_resource.payload if isinstance(quiz_resource.payload, dict) else {}

        existing = detail.get("remediation") if isinstance(detail.get("remediation"), dict) else {}
        existing_resource_id = str(existing.get("resource_id") or "")
        existing_resource = s.get(Resource, existing_resource_id) if existing_resource_id else None
        existing_quiz_id = str(existing.get("transfer_quiz_id") or "")
        existing_quiz = s.get(Resource, existing_quiz_id) if existing_quiz_id else None
        existing_doc = (
            _resource_dict(existing_resource)
            if existing_resource and existing_resource.user_id == req.user_id else None
        )
        valid_existing_quiz = (
            _resource_dict(existing_quiz)
            if existing_quiz and existing_quiz.user_id == req.user_id and existing_quiz.kind == "quiz"
            else None
        )
        if existing_doc and (valid_existing_quiz or existing.get("next_action") == "select_source"):
            return {
                "diagnosis": diagnosis,
                "resource": existing_doc,
                "transfer_quiz": valid_existing_quiz,
                "next_action": str(existing.get("next_action") or "retest"),
                "reused": True,
            }

    if diagnosis.get("status") != "needed":
        raise HTTPException(409, "当前答题记录不需要补救学习")
    remediation_kp = canonical_kp_id(str(diagnosis.get("remediation_kp") or ""))
    blocked_kp = canonical_kp_id(str(diagnosis.get("blocked_kp") or ""))
    if not remediation_kp or not blocked_kp:
        raise HTTPException(409, "诊断结果缺少可验证的课程知识点")

    try:
        source_ids = validate_source_scope(
            req.user_id,
            quiz_payload.get("source_ids") if isinstance(quiz_payload.get("source_ids"), list) else [],
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    misconception = str(diagnosis.get("misconception") or "概念还不稳定")
    goal = (
        f"当前原知识点是「{kp_name(blocked_kp)}」，诊断到的误区是「{misconception}」。"
        f"请先补「{kp_name(remediation_kp)}」，再让学习者回到原题完成无提示复测。"
    )
    profile = get_profile(req.user_id)
    if existing_doc:
        resource = existing_doc
        resources = {str(resource["id"]): resource}
        flags: list[dict] = []
        source_blocked = False
    else:
        state = {
            "user_id": req.user_id,
            "session_id": f"rem-{req.attempt_id}-{uuid.uuid4().hex[:6]}",
            "messages": [{"role": "user", "content": goal}],
            "learning_goal": goal,
            "knowledge_points": [remediation_kp],
            "kinds": ["doc"],
            "source_ids": source_ids,
            "prompt_template": "remediation",
            "student_profile": profile,
            "skip_multimodal": True,
            "required_retrieval_terms": [kp_name(remediation_kp), remediation_kp],
        }
        generated = await doc_agent.run(state)
        resources = generated.get("generated_resources") if isinstance(generated, dict) else {}
        if not isinstance(resources, dict) or not resources:
            raise HTTPException(503, "补救微课生成失败，请稍后重试")

        resource = next(iter(resources.values()))
        payload = dict(resource.get("payload") or {})
        payload["remediation"] = {
            "origin_attempt_id": req.attempt_id,
            "blocked_kp": blocked_kp,
            "prerequisite_gap": diagnosis.get("prerequisite_gap"),
            "misconception": misconception,
            "next_action": "retest",
        }
        resource["payload"] = payload
        resource["title"] = f"{kp_name(remediation_kp)}·补救微课"

        flags = generated.get("safety_flags") if isinstance(generated.get("safety_flags"), list) else []
        source_blocked = any(
            flag.get("type") == "source_scope_empty" for flag in flags if isinstance(flag, dict)
        )

    transfer_quiz: dict[str, Any] | None = None
    if not source_blocked:
        original_stems = [
            str(question.get("stem") or "")
            for question in quiz_payload.get("questions", [])
            if isinstance(question, dict) and str(question.get("stem") or "").strip()
        ]
        transfer_goal = (
            f"学习者已完成「{kp_name(remediation_kp)}」补救微课。"
            f"请用全新题面检查其能否回到「{kp_name(blocked_kp)}」并独立迁移；"
            f"重点辨析误区「{misconception}」。"
        )
        quiz_generated = await quiz_agent.run({
            "user_id": req.user_id,
            "session_id": f"transfer-{req.attempt_id}-{uuid.uuid4().hex[:6]}",
            "messages": [{"role": "user", "content": transfer_goal}],
            "learning_goal": transfer_goal,
            "knowledge_points": [blocked_kp],
            "kinds": ["quiz"],
            "source_ids": source_ids,
            "student_profile": profile,
            "transfer_retest": True,
            "target_questions": 3,
            "avoid_stems": original_stems,
            "misconception": misconception,
            "required_retrieval_terms": [kp_name(blocked_kp), blocked_kp],
        })
        quiz_resources = (
            quiz_generated.get("generated_resources") if isinstance(quiz_generated, dict) else {}
        )
        quiz_flags = (
            quiz_generated.get("safety_flags")
            if isinstance(quiz_generated, dict) and isinstance(quiz_generated.get("safety_flags"), list)
            else []
        )
        flags.extend(quiz_flags)
        source_blocked = any(
            flag.get("type") == "source_scope_empty" for flag in quiz_flags if isinstance(flag, dict)
        )
        if not source_blocked:
            if not isinstance(quiz_resources, dict) or not quiz_resources:
                raise HTTPException(503, "迁移复测生成失败，请稍后重试")
            transfer_quiz = next(iter(quiz_resources.values()))
            transfer_payload = dict(transfer_quiz.get("payload") or {})
            transfer_payload.update({
                "transfer_retest": True,
                "origin_attempt_id": req.attempt_id,
                "origin_quiz_resource_id": str(quiz_resource.id),
                "blocked_kp": blocked_kp,
                "source_ids": source_ids,
            })
            transfer_quiz["payload"] = transfer_payload
            transfer_quiz["title"] = f"{kp_name(blocked_kp)}·迁移复测"
            resources.update(quiz_resources)

    next_action = "select_source" if source_blocked else "retest"
    await eval_agent_module.run({
        "user_id": req.user_id,
        "generated_resources": resources,
        "safety_flags": flags,
    })

    with session() as s:
        attempt = s.get(QuizAttempt, req.attempt_id)
        if not attempt:
            raise HTTPException(404, "quiz attempt not found")
        detail = dict(attempt.detail or {})
        detail["remediation"] = {
            "resource_id": resource["id"],
            "remediation_kp": remediation_kp,
            "source_ids": source_ids,
            "transfer_quiz_id": transfer_quiz.get("id") if transfer_quiz else "",
            "next_action": next_action,
            "status": "blocked" if source_blocked else "ready_for_retest",
        }
        attempt.detail = detail
        s.commit()

    log_event(req.user_id, "remediation_generated", {
        "attempt_id": req.attempt_id,
        "resource_id": resource["id"],
        "transfer_quiz_id": transfer_quiz.get("id") if transfer_quiz else "",
        "blocked_kp": blocked_kp,
        "remediation_kp": remediation_kp,
        "source_ids": source_ids,
        "next_action": next_action,
    })
    return {
        "diagnosis": diagnosis,
        "resource": resource,
        "transfer_quiz": transfer_quiz,
        "next_action": next_action,
        "reused": False,
    }


@router.post("/retest")
async def retest(req: EvalRetestRequest):
    """Grade one independent recovery attempt, including fresh transfer items."""
    ensure_user(req.user_id)
    with session() as s:
        attempt = s.get(QuizAttempt, req.attempt_id)
        if not attempt or attempt.user_id != req.user_id:
            raise HTTPException(404, "quiz attempt not found")
        detail = dict(attempt.detail or {})
        remediation_detail = (
            detail.get("remediation") if isinstance(detail.get("remediation"), dict) else {}
        )
        transfer_quiz_id = str(remediation_detail.get("transfer_quiz_id") or "")
        transfer_retest = bool(transfer_quiz_id and transfer_quiz_id == req.quiz_resource_id)
        if attempt.quiz_resource_id != req.quiz_resource_id and not transfer_retest:
            raise HTTPException(404, "quiz attempt not found")

    if detail.get("retest"):
        raise HTTPException(409, "该答题记录已经完成过复测")
    qmap = _quiz_questions(req.user_id, req.quiz_resource_id)
    if transfer_retest:
        eligible_ids = set(qmap)
    else:
        original_items = {
            str(item.get("question_id")): item
            for item in detail.get("answers", [])
            if isinstance(item, dict) and item.get("question_id")
        }
        eligible_ids = {
            question_id
            for question_id, item in original_items.items()
            if not bool(item.get("mastery_correct", item.get("correct")))
        }
    if not eligible_ids:
        raise HTTPException(400, "本次答题没有需要恢复的题目")

    submitted_ids = [answer.question_id for answer in req.answers]
    if len(submitted_ids) != len(set(submitted_ids)):
        raise HTTPException(400, "复测题目不能重复提交")
    if set(submitted_ids) != eligible_ids:
        raise HTTPException(400, "请一次完成全部待复测题目")

    enriched = []
    for answer in req.answers:
        question = qmap.get(answer.question_id)
        if not question:
            raise HTTPException(400, f"题组中不存在题目 {answer.question_id}")
        correct = _grade_answer(question, answer.answer)
        kp = canonical_kp_id(question.get("kp") or attempt.kp)
        enriched.append({
            "question_id": answer.question_id,
            "kp": kp or "",
            "correct": correct,
            "mastery_correct": correct,
            "answer": answer.answer,
            "expected": question.get("answer", ""),
            "type": question.get("type", ""),
            "difficulty": question.get("difficulty", 0),
            "explain": question.get("explain", ""),
            "error_tags": list(question.get("error_tags", []) or []) if not correct else [],
            "hint_used": False,
            "revealed": False,
            "misconception": "",
            "confidence": answer.confidence,
            "support_level": "independent",
            "evidence_phase": "retest",
            "seconds": max(0.0, answer.seconds),
        })

    report = evaluate_answers(req.user_id, enriched)
    recovered = sum(bool(item["mastery_correct"]) for item in enriched)
    if transfer_retest:
        with session() as s:
            original_reviews = s.query(ReviewItem).filter(
                ReviewItem.user_id == req.user_id,
                ReviewItem.source_attempt_id == req.attempt_id,
            ).all()
        fully_recovered = recovered == len(enriched)
        review_inputs = [{
            "review_item_id": row.id,
            "question_id": row.question_id,
            "kp": row.kp,
            "correct": fully_recovered,
            "mastery_correct": fully_recovered,
        } for row in original_reviews]
        review_schedules = apply_review_results(
            req.user_id,
            review_inputs or enriched,
            phase="retest",
            quiz_resource_id=attempt.quiz_resource_id if review_inputs else req.quiz_resource_id,
        )
    else:
        review_schedules = apply_review_results(
            req.user_id, enriched, phase="retest", quiz_resource_id=req.quiz_resource_id,
        )
    retest_summary = {
        "status": "completed",
        "eligible": len(enriched),
        "recovered": recovered,
        "remaining": len(enriched) - recovered,
    }
    detail["retest"] = {
        "submitted": [answer.model_dump() for answer in req.answers],
        "answers": enriched,
        "quiz_resource_id": req.quiz_resource_id,
        "mode": "transfer" if transfer_retest else "original",
        "summary": retest_summary,
    }
    detail["diagnosis"] = report.get("diagnosis") or {}
    with session() as s:
        attempt = s.get(QuizAttempt, req.attempt_id)
        if not attempt:
            raise HTTPException(404, "quiz attempt not found")
        attempt.detail = detail
        s.commit()

    report["attempt_id"] = req.attempt_id
    report["retest"] = retest_summary
    report["review"] = {"schedule": review_schedules}
    report["behavior"] = {"phase": "retest", "support": {
        "hinted": 0, "revealed": 0, "independent": len(enriched), "misconceptions": [],
    }}
    return report


@router.get("/review-queue")
async def get_review_queue(user_id: str = Query("demo_user"), limit: int = Query(10, ge=1, le=50)):
    ensure_user(user_id)
    return review_queue(user_id, limit=limit)


@router.post("/review")
async def submit_review(req: EvalReviewRequest):
    """Grade due spaced-review items and advance/reset their schedules."""
    ensure_user(req.user_id)
    if not req.items:
        raise HTTPException(400, "复习提交不能为空")
    item_ids = [item.review_item_id for item in req.items]
    if len(item_ids) != len(set(item_ids)):
        raise HTTPException(400, "复习题目不能重复提交")

    current = utc_now()
    with session() as s:
        rows = [s.get(ReviewItem, item_id) for item_id in item_ids]
        if any(row is None or row.user_id != req.user_id for row in rows):
            raise HTTPException(404, "复习题目不存在")
        if any(row.status != "scheduled" for row in rows if row):
            raise HTTPException(409, "复习题目已经完成")
        if any(as_utc(row.due_at) > current for row in rows if row):
            raise HTTPException(400, "复习时间尚未到达")
        review_rows = {
            row.id: {
                "id": row.id,
                "quiz_resource_id": row.quiz_resource_id,
                "question_id": row.question_id,
                "kp": row.kp,
            }
            for row in rows if row
        }

    qmaps: dict[str, dict[str, dict]] = {}
    enriched = []
    for submitted in req.items:
        row = review_rows[submitted.review_item_id]
        resource_id = row["quiz_resource_id"]
        if resource_id not in qmaps:
            qmaps[resource_id] = _quiz_questions(req.user_id, resource_id)
        question = qmaps[resource_id].get(row["question_id"])
        if not question:
            raise HTTPException(400, f"题组中不存在题目 {row['question_id']}")
        correct = _grade_answer(question, submitted.answer)
        kp = canonical_kp_id(question.get("kp") or row["kp"])
        enriched.append({
            "review_item_id": row["id"],
            "quiz_resource_id": resource_id,
            "question_id": row["question_id"],
            "kp": kp or "",
            "correct": correct,
            "mastery_correct": correct,
            "answer": submitted.answer,
            "expected": question.get("answer", ""),
            "type": question.get("type", ""),
            "difficulty": question.get("difficulty", 0),
            "explain": question.get("explain", ""),
            "error_tags": list(question.get("error_tags", []) or []) if not correct else [],
            "hint_used": False,
            "revealed": False,
            "misconception": "",
            "confidence": submitted.confidence,
            "support_level": "independent",
            "evidence_phase": "spaced_review",
            "seconds": max(0.0, submitted.seconds),
        })

    report = evaluate_answers(req.user_id, enriched)
    schedules = apply_review_results(req.user_id, enriched, phase="spaced_review", at=current)
    queue = review_queue(req.user_id, at=current)
    report["review"] = {
        "completed": len(enriched),
        "correct": sum(bool(item["mastery_correct"]) for item in enriched),
        "schedule": schedules,
        "summary": queue["summary"],
    }
    report["behavior"] = {"phase": "spaced_review", "support": {
        "hinted": 0, "revealed": 0, "independent": len(enriched), "misconceptions": [],
    }}
    return report


@router.get("/evidence")
async def evidence(user_id: str = Query("demo_user"), limit: int = Query(12, ge=1, le=50)):
    """Explain which assessment rounds changed mastery and why."""
    ensure_user(user_id)
    return build_learning_evidence(user_id, limit=limit)


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

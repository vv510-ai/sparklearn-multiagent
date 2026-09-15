"""Entry assessment based on independent answers, with bounded study planning.

These are descriptive teaching rules, not a calibrated IRT test or a clinical
instrument. Self-report and response time never add points to correctness.
"""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import uuid
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select, update

from ..auth import enforce_user_scope
from ..models.db import session
from ..models.entities import AssessmentSession, EventLog, PathPlan, PersonalizationDecision, Profile, Resource
from .knowledge_graph import kp_name, load_kg, prerequisites, topological_order
from .path_service import plan_path
from .profile_service import ensure_user, get_profile

DATA = Path(__file__).resolve().parents[1] / "data"
STATUS_LABELS = {"unmeasured": "待补充测评", "gap": "优先补基础", "developing": "需要巩固", "strength": "本次表现较好"}
LESSONS = {
    "complexity": "01_复杂度分析.md", "array": "02_数组与链表.md", "linked_list": "02_数组与链表.md",
    "stack": "03_栈与队列.md", "queue": "03_栈与队列.md", "recursion": "04_递归与分治.md",
    "sorting_basic": "05_排序算法.md", "sorting_adv": "05_排序算法.md", "binary_tree": "06_二叉树与BST.md",
    "bst": "06_二叉树与BST.md", "heap": "07_堆与优先队列.md", "hash": "08_哈希表.md",
    "graph_basic": "09_图与最短路.md", "graph_traverse": "09_图与最短路.md", "shortest_path": "09_图与最短路.md",
    "dp": "10_动态规划.md",
}


def question_bank() -> list[dict]:
    seed = json.loads((DATA / "seed_quiz.json").read_text(encoding="utf-8"))["questions"]
    extra = json.loads((DATA / "assessment_questions.json").read_text(encoding="utf-8"))
    result = []
    for q in seed + extra:
        if q["type"] not in ("single", "judge"):
            continue
        options = q["options"] if q["type"] == "single" else ["对", "错"]
        key = q["answer"] if q["type"] == "single" else ("A" if q["answer"] == "对" else "B")
        result.append({**q, "options": options, "answer": key})
    return result


def _next(data: dict) -> dict | None:
    answers = data["answers"]
    if len(answers) >= data["limit"]:
        return None
    seen = {r["question_id"] for r in answers}
    choices = []
    for order, kp in enumerate(data["targets"]):
        rows = [r for r in answers if r["kp"] == kp]
        measured = [r for r in rows if r["status"] != "skipped"]
        if len(measured) >= 3:
            continue
        target_difficulty = 1 if not measured else (3 if measured[-1]["correct"] else 1)
        # Complexity needs a breadth sample: notation, dependent loops, then space.
        facet = ("asymptotic", "nested", "space")[len(measured)] if kp == "complexity" else None
        for q in data["bank"]:
            if q["kp"] == kp and q["id"] not in seen:
                facet_miss = bool(facet and facet != q.get("facet"))
                choices.append(((len(measured), len(rows), order, facet_miss, abs(q["difficulty"] - target_difficulty), q["id"]), q))
    return min(choices, key=lambda pair: pair[0])[1] if choices else None


def evidence_report(data: dict) -> dict:
    rows = []
    for kp in data["targets"]:
        answers = [r for r in data["answers"] if r["kp"] == kp and r["status"] != "skipped"]
        count = len(answers)
        correct = sum(r["correct"] for r in answers)
        accuracy = correct / count if count else None
        status = "unmeasured" if count < 3 else "gap" if accuracy < 0.5 else "strength" if accuracy >= 0.8 else "developing"
        rows.append({"kp": kp, "name": kp_name(kp), "attempts": count, "correct": correct, "accuracy": accuracy,
                     "status": status, "label": STATUS_LABELS[status],
                     "high_confidence_errors": sum(r["status"] == "answered" and not r["correct"] and (r.get("confidence") or 0) >= 0.8 for r in answers),
                     "question_ids": [r["question_id"] for r in answers]})
    calibrated = [r for r in data["answers"] if r["status"] == "answered" and r.get("confidence") is not None]
    explanations = []
    bank = {q["id"]: q for q in data["bank"]}
    for answer in data["answers"]:
        q = bank[answer["question_id"]]
        explanations.append({"id": q["id"], "kp": q["kp"], "stem": q["stem"], "correct": answer["correct"],
                             "status": answer["status"], "answer": q["options"][ord(q["answer"]) - 65], "explain": q["explain"]})
    return {"skills": rows, "coverage": sum(r["attempts"] >= 3 for r in rows), "total_skills": len(rows),
            "calibration_samples": len(calibrated),
            "calibration_error": sum((r["confidence"] - int(r["correct"])) ** 2 for r in calibrated) / len(calibrated) if calibrated else None,
            "explanations": explanations,
            "boundary": "结果只描述本次课程题目中的作答；需要换题和延迟复测确认。未测知识点保持待测，自述与答题速度不计入正确率。重复摸底可能遇到同题，不作为新的独立掌握证据。"}


def study_plan(report: dict, survey: dict, *, today: dt.date | None = None) -> dict:
    today = today or dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date()
    horizon = 14
    if survey.get("target_date"):
        horizon = min(horizon, max(1, (dt.date.fromisoformat(survey["target_date"]) - today).days + 1))
    days = [{"date": (today + dt.timedelta(days=i)).isoformat(), "capacity": survey["daily_minutes"] if (today + dt.timedelta(days=i)).isoweekday() in survey["study_days"] else 0,
             "minutes": 0, "tasks": []} for i in range(horizon)]
    skills = {s["kp"]: s for s in report["skills"]}
    targets = set(skills)
    def include_parents(kp):
        for parent in prerequisites(kp):
            if parent not in targets:
                targets.add(parent)
                include_parents(parent)
    for kp in list(targets):
        include_parents(kp)
    order = [kp for kp in topological_order() if kp in targets]
    scheduled, deferred, last, reviews = {}, [], {}, []
    def place(task, earliest):
        for day in days:
            if day["date"] >= earliest and day["capacity"] - day["minutes"] >= task["minutes"]:
                day["tasks"].append(task)
                day["minutes"] += task["minutes"]
                scheduled[task["id"]] = day["date"]
                return day["date"]
        deferred.append({**task, "deferred_reason": "可用时间不足，调整日历后继续安排"})
        return None
    for kp in order:
        s = skills.get(kp, {"status": "unmeasured", "correct": 0, "attempts": 0})
        deps = [last[p] for p in prerequisites(kp) if p in last]
        kind = "diagnose" if s["status"] == "unmeasured" else "transfer" if s["status"] == "strength" else "study"
        minutes = min(survey["daily_minutes"], 8 if survey.get("pressure") == "high" or kind != "study" else 12)
        task = {"id": f"{kp}-{kind}", "kp": kp, "title": f"{kp_name(kp)} · " + {"diagnose": "补充独立测评", "transfer": "换情境验证", "study": "例题与独立练习"}[kind],
                "kind": kind, "minutes": minutes, "done": False, "requires": deps,
                "reason": "证据不足，先补测再确定深度" if kind == "diagnose" else f"本次独立答对 {s['correct']}/{s['attempts']} 题",
                "goal": f"我的课程是数据结构与算法，学习目标是{survey.get('goal', '掌握基础')}。请根据课程资料带我学习{kp_name(kp)}，先给学习目标、必要概念和一个带步骤例题，再给一题不同情境的无提示练习。每步不超过{minutes}分钟。",
                "criterion": "用自己的话解释关键步骤，并独立完成一道新题；未通过则回到先修知识。"}
        last[kp] = task["id"]
        if kind == "diagnose":
            task["goal"] = f"请用3道不同的无提示小题补测{kp_name(kp)}，逐题等待我回答，先不要展示答案；根据结果再确定学习深度。"
        elif kind == "transfer":
            task["goal"] = f"我在起点测评中完成了{kp_name(kp)}的基础题。请给一道不同情境的迁移题，先不要给提示或答案，等我独立完成后再反馈。"
        if survey.get("support"):
            task["goal"] += f" 讲解支持偏好：{survey['support']}。"
        if survey.get("stage") != "不方便回答":
            task["goal"] += f" 学习场景：{survey.get('stage', '大学课程')}。"
        if survey.get("prior_experience") == "第一次系统学习" or survey.get("stage") == "高中提前学习":
            task["goal"] += "先解释需要用到的符号、变量与循环含义，再进入算法。"
        if any(dep not in scheduled for dep in deps):
            deferred.append({**task, "deferred_reason": "先修任务尚未安排"})
            continue
        if kind != "diagnose" and any(skills.get(p, {}).get("status", "unmeasured") == "unmeasured" for p in prerequisites(kp)):
            deferred.append({**task, "deferred_reason": "先修知识待测评，完成后重新规划"})
            continue
        date = place(task, max([days[0]["date"], *[scheduled[dep] for dep in deps]]))
        if date and kind != "diagnose":
            for delay in (1, 3, 7):
                review = {**task, "id": f"{kp}-review-{delay}", "kind": "review", "title": f"{kp_name(kp)} · 间隔回忆", "minutes": 5, "requires": [task["id"]],
                          "reason": "闭卷回忆，再用一道新题检查保持情况", "goal": f"请围绕{kp_name(kp)}给我一道新的无提示迁移题，先不要显示答案。"}
                reviews.append(((dt.date.fromisoformat(date) + dt.timedelta(days=delay)).isoformat(), kp, review))
    last_review = {}
    for due, kp, review in sorted(reviews, key=lambda r: r[0]):
        if kp in last_review:
            due = max(due, (dt.date.fromisoformat(last_review[kp]) + dt.timedelta(days=1)).isoformat())
        assigned = place(review, due)
        if assigned:
            last_review[kp] = assigned
    habit_advice = {"reread": "把一次重读替换为合上资料写出三个关键点，再对照纠错。", "practice": "做题后补上一句原因解释；第二天换一道情境不同的题。", "mixed": "保留讲解与练习交替，每次结束记录一个还不能独立解释的问题。"}
    return {"days": days, "deferred": deferred, "goal": survey.get("goal", "掌握课程基础"),
            "reflection": habit_advice.get(survey.get("study_habit"), "每次结束记下：我已能独立完成什么？下一次先补哪一步？"),
            "rule": "按先修关系、作答证据和实际可用时间安排；1/3/7 天是初始复习间隔，后续依复测调整。任务勾选只记录进度，掌握度仍需独立作答。",
            "support": "先完成一个 8 分钟的小步骤，之后可以休息或调整计划。" if survey.get("pressure") == "high" else "每次先回忆，再看例题；看懂后用新题验证。"}


def _public(row: AssessmentSession) -> dict:
    data = row.data
    q = _next(data) if data["status"] == "active" else None
    return {"id": row.id, "revision": row.revision, "status": data["status"], "mode": data["mode"],
            "answered": len(data["answers"]), "maximum": data["limit"], "survey": data["survey"],
            "question": {"id": q["id"], "stem": q["stem"], "options": q["options"], "topic": kp_name(q["kp"])} if q else None,
            "report": data.get("report"), "plan": data.get("plan"), "materials": data.get("materials", []), "bank_version": data["bank_version"]}


def latest(user_id: str) -> dict:
    ensure_user(user_id)
    with session() as db:
        row = db.scalar(select(AssessmentSession).where(AssessmentSession.user_id == user_id).order_by(AssessmentSession.created_at.desc(), AssessmentSession.id.desc()).limit(1))
        return {"assessment": _public(row) if row else None, "course": load_kg()["course"]}


def start(user_id: str, survey: dict, mode: str) -> dict:
    get_profile(user_id)
    bank = question_bank()
    targets = topological_order()
    if mode == "foundation":
        targets = [k for k in targets if k in {"complexity", "array", "linked_list", "stack", "queue", "recursion"}]
    bank = [q for q in bank if q["kp"] in targets]
    count = sum(min(3, sum(q["kp"] == kp for q in bank)) for kp in targets)
    row = AssessmentSession(id=uuid.uuid4().hex, user_id=user_id, revision=0, data={"status": "active", "mode": mode, "survey": survey,
        "bank": bank, "bank_version": hashlib.sha256(json.dumps(bank, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16],
        "targets": targets, "limit": min(48, count + 4), "answers": []})
    with session() as db:
        db.add(row)
        db.commit()
    return _public(row)


def _owned(db, user_id: str, assessment_id: str):
    enforce_user_scope(user_id)
    row = db.scalar(select(AssessmentSession).where(AssessmentSession.id == assessment_id, AssessmentSession.user_id == user_id).with_for_update())
    if not row:
        raise HTTPException(404, "测评不存在")
    return row


def _apply_survey_context(value: dict, survey: dict) -> None:
    goals = {"准备课程考试": "应试", "考研 408 复习": "应试", "竞赛与算法练习": "竞赛", "编程项目应用": "工程实践", "兴趣理解": "兴趣"}
    if survey.get("goal") in goals:
        value["goal"] = goals[survey["goal"]]
    value["pace"] = {**(value.get("pace") if isinstance(value.get("pace"), dict) else {}),
        "daily_minutes": survey["daily_minutes"], "weekly_minutes": survey["daily_minutes"] * len(survey["study_days"]),
        "frequency": "每天" if len(survey["study_days"]) == 7 else f"每周{len(survey['study_days'])}天"}


def _finish(db, row, data):
    report = evidence_report(data)
    data.update(status="completed", report=report, plan=study_plan(report, data["survey"]))
    profile = db.scalar(select(Profile).where(Profile.user_id == row.user_id).with_for_update())
    if profile:
        value = copy.deepcopy(profile.data)
        value["baseline_assessment"] = {"id": row.id, "skills": report["skills"], "bank_version": data["bank_version"]}
        # Earlier real practice remains authoritative; this is a cold-start prior only.
        practice_events = db.scalars(select(EventLog).where(EventLog.user_id == row.user_id, EventLog.etype == "quiz_eval")).all()
        practiced = set()
        for event in practice_events:
            # Old events without objective-level provenance conservatively protect all scores.
            practiced.update((event.payload or {}).get("per_kp") or value["knowledge_mastery"])
        applied = set(value.get("baseline_assessment_applied_kps", []))
        for skill in report["skills"]:
            if skill["attempts"] >= 3 and skill["kp"] not in practiced | applied:
                value["knowledge_mastery"][skill["kp"]] = round(min(0.75, max(0.15, (1 + skill["correct"]) / (2 + skill["attempts"]))), 4)
                applied.add(skill["kp"])
        value["baseline_assessment_applied_kps"] = sorted(applied)
        value["focus_kps"] = [s["kp"] for s in report["skills"] if s["status"] in ("gap", "developing")][:8]
        _apply_survey_context(value, data["survey"])
        profile.data = value
        profile.version = (profile.version or 0) + 1
        path = plan_path(value, generated_by="entry_assessment")
        stored_path = db.get(PathPlan, row.user_id)
        if stored_path:
            stored_path.data = path
        else:
            db.add(PathPlan(user_id=row.user_id, data=path))
        db.add(PersonalizationDecision(user_id=row.user_id, kind="learning_path", profile_version=profile.version,
            inputs={"assessment_id": row.id, "coverage": report["coverage"]},
            output={"next_kp": path.get("next_kp"), "generated_by": "entry_assessment"},
            reason="独立作答用于首次先验，已有练习证据保持优先；日历依据本次作答和时间预算"))
    materials = []
    material_skills = [s for s in report["skills"] if s["status"] in ("gap", "developing")][:4]
    if not material_skills:
        material_skills = [s for s in report["skills"] if s["status"] == "strength"][:2]
    for skill in material_skills:
        filename = LESSONS.get(skill["kp"])
        if not filename:
            continue
        path = DATA / "seed_corpus" / filename
        body = path.read_text(encoding="utf-8")
        if body.startswith("---"):
            body = body.split("---", 2)[-1].strip()
        mistakes = [q for q in report["explanations"] if q["kp"] == skill["kp"] and not q["correct"] and q["status"] != "skipped"]
        recap = "\n\n".join(f"### {q['stem']}\n\n{q['explain']}" for q in mistakes)
        instruction = "基础题表现较好，请用以下内容核对边界条件，再完成迁移练习。" if skill["status"] == "strength" else "先补足下列概念与步骤，再尝试独立练习。"
        markdown = f"# {skill['name']} · 起点学习资料\n\n依据本次独立作答 {skill['correct']}/{skill['attempts']}：{instruction}\n\n## 错题回顾\n\n{recap or '本次该知识点没有错题；仍需换题和延迟复测确认。'}\n\n## 课程讲义\n\n{body}\n\n## 下一步\n\n合上资料解释核心步骤，再在学习工坊生成新题进行无提示复测。\n\n来源：课程自编种子讲义 {filename}（CC BY-SA 4.0）；本次诊断题解析。"
        resource_id = f"baseline-{row.id}-{skill['kp']}"
        resource = Resource(id=resource_id, user_id=row.user_id, kind="doc", kp=skill["kp"], title=f"起点资料 · {skill['name']}",
                            payload={"markdown": markdown}, citations=[{"source": filename, "chapter": skill["name"]}], safety={"source": "course_seed", "generated_by": "entry_assessment"})
        db.add(resource)
        materials.append({"id": resource_id, "kp": skill["kp"], "title": resource.title, "markdown": markdown})
    data["materials"] = materials
    db.add(EventLog(user_id=row.user_id, etype="entry_assessment", payload={"assessment_id": row.id, "bank_version": data["bank_version"], "report": report}))


def answer(user_id: str, assessment_id: str, payload: dict) -> dict:
    with session() as db:
        row = _owned(db, user_id, assessment_id)
        data = copy.deepcopy(row.data)
        existing = next((a for a in data["answers"] if a["question_id"] == payload["question_id"]), None)
        if existing:
            if any(existing.get(k) != payload.get(k) for k in ("choice", "status", "confidence")):
                raise HTTPException(409, "该题已提交，请继续下一题")
            return _public(row)
        if row.revision != payload["revision"] or data["status"] != "active":
            raise HTTPException(409, "测评已更新，请刷新后继续")
        q = _next(data)
        if not q or q["id"] != payload["question_id"]:
            raise HTTPException(409, "请提交当前题目")
        if payload["status"] == "answered" and payload.get("choice") not in [chr(65+i) for i in range(len(q["options"]))]:
            raise HTTPException(422, "请选择有效答案")
        if payload["status"] != "answered" and payload.get("choice") is not None:
            raise HTTPException(422, "跳过或不会的题不能同时选择答案")
        data["answers"].append({**payload, "kp": q["kp"], "correct": payload["status"] == "answered" and payload.get("choice") == q["answer"]})
        # Compare-and-swap also protects SQLite, whose FOR UPDATE is a no-op.
        changed = db.execute(update(AssessmentSession).where(AssessmentSession.id == row.id, AssessmentSession.revision == payload["revision"]).values(revision=payload["revision"]+1))
        if changed.rowcount != 1:
            raise HTTPException(409, "测评已更新，请刷新后继续")
        if _next(data) is None:
            _finish(db, row, data)
        row.data = data
        row.revision = payload["revision"] + 1
        db.commit()
        result = _public(row)
    return result


def update_task(user_id: str, assessment_id: str, task_id: str, done: bool) -> dict:
    with session() as db:
        row = _owned(db, user_id, assessment_id)
        data = copy.deepcopy(row.data)
        if data["status"] != "completed":
            raise HTTPException(409, "请先完成测评")
        tasks = [t for day in data["plan"]["days"] for t in day["tasks"]]
        task = next((t for t in tasks if t["id"] == task_id), None)
        if not task:
            raise HTTPException(404, "任务不存在")
        if done and any(not next((t["done"] for t in tasks if t["id"] == dep), False) for dep in task["requires"]):
            raise HTTPException(409, "先完成前置任务，再更新这一项")
        if not done and any(t["done"] and task_id in t["requires"] for t in tasks):
            raise HTTPException(409, "请先撤销后续任务的完成标记")
        task["done"] = done
        revision = row.revision
        changed = db.execute(update(AssessmentSession).where(AssessmentSession.id == row.id, AssessmentSession.revision == revision).values(revision=revision + 1))
        if changed.rowcount != 1:
            raise HTTPException(409, "计划已更新，请刷新后继续")
        row.data = data
        row.revision = revision + 1
        db.commit()
        return _public(row)


def replan(user_id: str, assessment_id: str, survey: dict) -> dict:
    with session() as db:
        row = _owned(db, user_id, assessment_id)
        data = copy.deepcopy(row.data)
        if data["status"] != "completed":
            raise HTTPException(409, "请先完成测评")
        completed = {task["id"] for day in data["plan"]["days"] for task in day["tasks"] if task["done"]}
        data["survey"] = survey
        data["plan"] = study_plan(data["report"], survey)
        tasks = [t for day in data["plan"]["days"] for t in day["tasks"]]
        retained = set()
        for task in tasks:
            if task["id"] in completed and all(dep in retained for dep in task["requires"]):
                task["done"] = True
                retained.add(task["id"])
        revision = row.revision
        changed = db.execute(update(AssessmentSession).where(AssessmentSession.id == row.id, AssessmentSession.revision == revision).values(revision=revision + 1))
        if changed.rowcount != 1:
            raise HTTPException(409, "计划已更新，请刷新后继续")
        row.data, row.revision = data, revision + 1
        profile = db.scalar(select(Profile).where(Profile.user_id == user_id).with_for_update())
        if profile:
            value = copy.deepcopy(profile.data)
            _apply_survey_context(value, survey)
            profile.data, profile.version = value, (profile.version or 0) + 1
        db.commit()
        return _public(row)

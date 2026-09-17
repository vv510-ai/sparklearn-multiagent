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
from .learning_intake import context_reasons, lesson_guidance, screening_targets, small_steps, task_approach
from .learning_scope import current_space, notebook_id, profile_row, event_in_scope

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
    if current_space() and current_space()["course"].get("bank"):
        return copy.deepcopy(current_space()["course"]["bank"])
    seed = json.loads((DATA / "seed_quiz.json").read_text(encoding="utf-8"))["questions"]
    extra = json.loads((DATA / "assessment_questions.json").read_text(encoding="utf-8"))
    extra += json.loads((DATA / "entry_v2_questions.json").read_text(encoding="utf-8"))
    result = []
    for q in seed + extra:
        if q["type"] not in ("single", "judge", "multiple"):
            continue
        options = q["options"] if q["type"] != "judge" else ["对", "错"]
        key = q["answer"] if q["type"] != "judge" else ("A" if q["answer"] == "对" else "B")
        result.append({**q, "options": options, "answer": key})
    return result


def _next(data: dict) -> dict | None:
    answers = data["answers"]
    if len(answers) >= data["limit"]:
        return None
    seen = {r["question_id"] for r in answers} | set(data.get("exposed_question_ids", []))
    choices = []
    for order, kp in enumerate(data["targets"]):
        rows = [r for r in answers if r["kp"] == kp]
        measured = [r for r in rows if r["status"] != "skipped"]
        if len(measured) >= 3:
            continue
        target_difficulty = 1 if not measured else (3 if measured[-1]["correct"] else 1)
        used_types = {q["type"] for q in data["bank"] if q["id"] in {r["question_id"] for r in measured}}
        # Complexity needs a breadth sample: notation, dependent loops, then space.
        facet = ("asymptotic", "nested", "space")[len(measured)] if kp == "complexity" else None
        for q in data["bank"]:
            if q["kp"] == kp and q["id"] not in seen:
                facet_miss = bool(facet and facet != q.get("facet"))
                format_repeat = bool(measured and q["type"] in used_types)
                choices.append(((len(measured), len(rows), order, facet_miss, abs(q["difficulty"] - target_difficulty), format_repeat, q["id"]), q))
    return min(choices, key=lambda pair: pair[0])[1] if choices else None


def evidence_report(data: dict) -> dict:
    rows = []
    scope = topological_order() if data["mode"] == "screening" else data["targets"]
    for kp in scope:
        answers = [r for r in data["answers"] if r["kp"] == kp and r["status"] != "skipped"]
        count = len(answers)
        correct = sum(r["correct"] for r in answers)
        accuracy = correct / count if count else None
        status = "unmeasured" if count < 3 else "gap" if accuracy < 0.5 else "strength" if accuracy >= 0.8 else "developing"
        rows.append({"kp": kp, "name": kp_name(kp), "attempts": count, "correct": correct, "accuracy": accuracy,
                     "in_scope": kp in data["targets"],
                     "after_intro": bool(kp == "stack" and data["survey"].get("intro_practiced")),
                     "status": status, "label": STATUS_LABELS[status],
                     "high_confidence_errors": sum(r["status"] == "answered" and not r["correct"] and (r.get("confidence") or 0) >= 0.8 for r in answers),
                     "question_ids": [r["question_id"] for r in answers]})
    calibrated = [r for r in data["answers"] if r["status"] == "answered" and r.get("confidence") is not None]
    explanations = []
    bank = {q["id"]: q for q in data["bank"]}
    for answer in data["answers"]:
        q = bank[answer["question_id"]]
        keys = q["answer"] if isinstance(q["answer"], list) else [q["answer"]]
        explanations.append({"id": q["id"], "kp": q["kp"], "stem": q["stem"], "correct": answer["correct"],
                             "status": answer["status"], "answer": "；".join(q["options"][ord(k) - 65] for k in keys),
                             "explain": q["explain"] + ("\n\n听力文字稿：" + q["transcript"] if q.get("transcript") else "")})
    return {"skills": rows, "coverage": sum(r["attempts"] >= 3 for r in rows), "total_skills": len(rows),
            "calibration_samples": len(calibrated),
            "calibration_error": sum((r["confidence"] - int(r["correct"])) ** 2 for r in calibrated) / len(calibrated) if calibrated else None,
            "explanations": explanations,
            "boundary": "结果只描述本次课程题目中的作答；需要换题和延迟复测确认。未测知识点保持待测，自述与答题速度不计入正确率。重复摸底可能遇到同题，不作为新的独立掌握证据。" + (data.get("course_snapshot") or {}).get("boundary", "")}


def study_plan(report: dict, survey: dict, *, today: dt.date | None = None) -> dict:
    today = today or dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date()
    horizon = 14
    if survey.get("target_date"):
        horizon = min(horizon, max(1, (dt.date.fromisoformat(survey["target_date"]) - today).days + 1))
    days = [{"date": (today + dt.timedelta(days=i)).isoformat(), "capacity": survey["daily_minutes"] if (today + dt.timedelta(days=i)).isoweekday() in survey["study_days"] else 0,
             "minutes": 0, "tasks": []} for i in range(horizon)]
    skills = {s["kp"]: s for s in report["skills"] if s.get("in_scope", True)}
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
        minutes = min(survey["daily_minutes"], 8 if small_steps(survey) or kind != "study" else 12)
        approach_title, approach = task_approach(survey)
        task = {"id": f"{kp}-{kind}", "kp": kp, "title": f"{kp_name(kp)} · " + {"diagnose": "补充独立测评", "transfer": "换情境验证", "study": approach_title}[kind],
                "kind": kind, "minutes": minutes, "done": False, "requires": deps,
                "reason": "证据不足，先补测再确定深度" if kind == "diagnose" else f"独立作答证据：{s['correct']}/{s['attempts']} 题正确" + ("（含后续新题）" if s.get("practice_updated") else ""),
                "goal": f"我的课程是{load_kg()['course']}，学习目标是{survey.get('goal', '掌握基础')}。请根据课程资料带我学习{kp_name(kp)}，先给学习目标、必要概念和一个带步骤例题，再给一题不同情境的无提示练习。每步不超过{minutes}分钟。",
                "criterion": "用自己的话解释关键步骤，并独立完成一道新题；未通过则回到先修知识。"}
        task["steps"] = ["先回忆概念与适用条件", approach, "合上资料，完成一道不同情境的题", "记录仍需帮助的一步"]
        space = current_space()
        textbook = (space or {}).get("course", {}).get("textbook")
        if textbook:
            task["readings"] = [{"title": section["title"], "url": section["url"], "version": textbook["version"]}
                                for section in textbook["sections"] if kp in section["kps"]]
            task["steps"] = ["阅读下面对应的教材章节，核对一个分步例子", approach,
                             "合上资料，在本页独立完成三道新题", "查看反馈；按页面提示的时间换题复测"]
        if (space or {}).get("course", {}).get("kind") == "cet6":
            if kp == "cet6_listening":
                task["steps"] = ["先读选项，预测需要听的信息", "完整听一遍音频后，独立完成三道新题", "提交后核对文字稿，区分辨音、词汇与推理困难", "闭稿复听，并按提示安排换题复测"]
                task["criterion"] = "凭音频独立提取信息；合成短音频的表现不代表完整六级听力水平。"
            elif kp in ("cet6_writing", "cet6_translation"):
                task["steps"] = ["阅读对应讲义的分步例子", "用三道新题检查句法与逻辑辨析", "在本页完成一段自己的英文，再请小知反馈", "自行修订，并用另一主题检查能否独立表达"]
                task["criterion"] = "基础辨析与实际输出分别练习；选择题完成不等于作文或翻译达标。"
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
            task["goal"] += "先解释需要用到的符号和先备概念，再逐步进入本课内容。"
        task["goal"] += " 学习安排：" + " ".join(context_reasons(survey))
        if kind != "diagnose":
            task["goal"] += " " + approach
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
            "adaptations": context_reasons(survey),
            "reflection": habit_advice.get(survey.get("study_habit"), "每次结束记下：我已能独立完成什么？下一次先补哪一步？"),
            "rule": "按先修关系、作答证据和实际可用时间安排；1/3/7 天是初始复习间隔，后续依复测调整。任务勾选只记录进度，掌握度仍需独立作答。",
            "support": "先完成一个 8 分钟的小步骤，之后可以休息或调整计划。" if small_steps(survey) else "每次先回忆，再看例题；看懂后用新题验证。"}


def _public(row: AssessmentSession) -> dict:
    data = row.data
    q = _next(data) if data["status"] == "active" else None
    from .course_learning_service import public_course
    from .assessment_practice import public_progress
    return {"id": row.id, "revision": row.revision, "status": data["status"], "mode": data["mode"],
            "notebook_id": data.get("notebook_id", ""), "course": public_course(data["course_snapshot"]) if data.get("course_snapshot") else None,
            "answered": len(data["answers"]), "maximum": data["limit"], "survey": data["survey"],
            "question": {"id": q["id"], "stem": q["stem"], "options": q["options"], "topic": kp_name(q["kp"]), "type": "multiple" if q["type"] == "multiple" else "single",
                         **({"audio_url": q["audio_url"]} if q.get("audio_url") else {})} if q else None,
            "report": data.get("report"), "plan": data.get("plan"), "materials": data.get("materials", []), "bank_version": data["bank_version"],
            "learning_progress": public_progress(data)}


def _sessions(user_id: str):
    query = select(AssessmentSession).where(AssessmentSession.user_id == user_id)
    key = AssessmentSession.data["notebook_id"].as_string()
    return query.where(key == notebook_id()) if notebook_id() else query.where(key.is_(None) | (key == ""))


def latest(user_id: str) -> dict:
    ensure_user(user_id)
    with session() as db:
        row = db.scalar(_sessions(user_id).order_by(AssessmentSession.created_at.desc(), AssessmentSession.id.desc()).limit(1).with_for_update())
        if row and current_space() and (row.data.get("course_snapshot") or {}).get("revision") != current_space()["course"].get("revision"):
            row = None
        if row and row.data["status"] == "completed":
            _refresh_from_practice(db, row)
            db.commit()
        return {"assessment": _public(row) if row else None, "course": load_kg()["course"]}


def start(user_id: str, survey: dict, mode: str, course_revision: str = "", target_kps: list[str] | None = None) -> dict:
    profile_data = get_profile(user_id)
    space = current_space()
    if space and (not space["course"].get("bank") or course_revision != space["course"].get("revision")):
        raise HTTPException(409, "请先核对这门课程的学习范围，再开始测评")
    survey = copy.deepcopy(survey)
    if space:
        survey.update(notebook_id=notebook_id(), course_title=space["course"]["title"],
            source_ids=space["course"].get("source_ids", []), course_revision=space["course"].get("revision"))
    survey["intro_practiced"] = bool(survey.get("intro_practiced") or profile_data.get("learning_intake", {}).get("intro_practiced"))
    bank = question_bank()
    targets = topological_order()
    if space and space["course"].get("kind") != "ds_algo":
        targets = targets[:4] if mode in ("screening", "foundation") else targets
    elif mode == "screening":
        targets = screening_targets(survey)
    if mode == "foundation" and (not space or space["course"].get("kind") == "ds_algo"):
        targets = [k for k in targets if k in {"complexity", "array", "linked_list", "stack", "queue", "recursion"}]
    if target_kps is not None:
        if not target_kps or not set(target_kps) <= set(topological_order()):
            raise HTTPException(422, "请选择课程范围内至少一个知识点")
        if mode == "foundation":
            targets = [k for k in targets if k in target_kps]
        elif mode == "screening":
            ordered = list(dict.fromkeys([*targets, *topological_order()]))
            targets = [k for k in ordered if k in target_kps][:4]
        else:
            targets = [k for k in topological_order() if k in target_kps]
        if not targets:
            raise HTTPException(422, "当前模式没有选中的知识点，请调整范围或选择全面摸底")
    count = sum(min(3, sum(q["kp"] == kp for q in bank)) for kp in targets)
    available = sum(q["kp"] in targets for q in bank)
    row = AssessmentSession(id=uuid.uuid4().hex, user_id=user_id, revision=0, data={"status": "active", "mode": mode, "survey": survey,
        "bank": bank, "bank_version": hashlib.sha256(json.dumps(bank, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16],
        "targets": targets, "limit": min(12 if mode == "screening" else 48, count + 4, available), "answers": [],
        "notebook_id": notebook_id(), "course_snapshot": copy.deepcopy(space["course"]) if space else None})
    with session() as db:
        profile = profile_row(db, user_id)
        active = db.scalar(_sessions(user_id).order_by(AssessmentSession.created_at.desc(), AssessmentSession.id.desc()).limit(1))
        if active and active.data["status"] == "active":
            return _public(active)
        past = db.scalars(select(EventLog).where(EventLog.user_id == user_id, EventLog.etype == "quiz_eval").order_by(EventLog.id)).all()
        past = [event for event in past if event_in_scope(event.payload)]
        row.data["practice_cursor"] = past[-1].id if past else 0
        row.data["practice_seen"] = sorted({item["key"] for event in past for item in (event.payload or {}).get("learning_evidence", []) if item.get("key")})
        if profile:
            value = copy.deepcopy(profile.data)
            _apply_survey_context(value, survey)
            profile.data, profile.version = value, (profile.version or 0) + 1
        db.add(row)
        _save_journey(db, user_id, row.id, "assessment")
        db.commit()
    return _public(row)


def _owned(db, user_id: str, assessment_id: str):
    enforce_user_scope(user_id)
    row = db.scalar(select(AssessmentSession).where(AssessmentSession.id == assessment_id, AssessmentSession.user_id == user_id).with_for_update())
    if not row:
        raise HTTPException(404, "测评不存在")
    if row.data.get("notebook_id"):
        from ..models.entities import LearningSpace
        course = db.get(LearningSpace, row.data["notebook_id"])
        if not course or course.course.get("revision") != (row.data.get("course_snapshot") or {}).get("revision"):
            raise HTTPException(409, "课程范围已经更新，请从当前课程重新开始测评；之前的作答仍保留")
    return row


def _apply_survey_context(value: dict, survey: dict) -> None:
    goals = {"准备课程考试": "应试", "考研 408 复习": "应试", "竞赛与算法练习": "竞赛", "编程项目应用": "工程实践", "兴趣理解": "兴趣"}
    value["goal"] = goals.get(survey.get("goal"), "未知")
    value["pace"] = {**(value.get("pace") if isinstance(value.get("pace"), dict) else {}),
        "daily_minutes": survey["daily_minutes"], "weekly_minutes": survey["daily_minutes"] * len(survey["study_days"]),
        "frequency": "每天" if len(survey["study_days"]) == 7 else f"每周{len(survey['study_days'])}天"}
    value["learning_intake"] = copy.deepcopy(survey)
    value["onboarding_completed"] = True
    value["materials_status"] = survey.get("materials_status", "暂时没有")


def _save_journey(db, user_id: str, assessment_id: str, phase: str) -> None:
    account = db.get(Profile, user_id)
    if account:
        value = copy.deepcopy(account.data)
        value.update(onboarding_completed=True, onboarding_state={"phase": phase,
            "notebook_id": notebook_id(), "assessment_id": assessment_id})
        account.data = value


def save_intake_context(user_id: str, survey: dict) -> dict:
    get_profile(user_id)
    with session() as db:
        profile = profile_row(db, user_id)
        value = copy.deepcopy(profile.data)
        _apply_survey_context(value, survey)
        profile.data, profile.version = value, (profile.version or 0) + 1
        db.commit()
    return get_profile(user_id)


def _finish(db, row, data):
    report = evidence_report(data)
    completed = {t["id"] for day in data.get("plan", {}).get("days", []) for t in day["tasks"] if t["done"]}
    previous = {s["kp"]: s for s in data.get("plan_evidence", {}).get("skills", []) if s.get("practice_updated")}
    plan_evidence = copy.deepcopy(report)
    plan_evidence["skills"] = [previous.get(s["kp"], s) for s in plan_evidence["skills"]]
    data.update(status="completed", report=report, plan=study_plan(plan_evidence, data["survey"]), plan_evidence=plan_evidence)
    retained = set()
    for day in data["plan"]["days"]:
        for task in day["tasks"]:
            if task["id"] in completed and all(dep in retained for dep in task["requires"]):
                task["done"] = True
                retained.add(task["id"])
    data.setdefault("practice_seen", [])
    if "practice_cursor" not in data:
        data["practice_cursor"] = db.scalar(select(EventLog.id).where(EventLog.user_id == row.user_id, EventLog.etype == "quiz_eval").order_by(EventLog.id.desc()).limit(1)) or 0
    profile = profile_row(db, row.user_id)
    if profile:
        value = copy.deepcopy(profile.data)
        value["baseline_assessment"] = {"id": row.id, "skills": report["skills"], "bank_version": data["bank_version"]}
        # Earlier real practice remains authoritative; this is a cold-start prior only.
        practice_events = db.scalars(select(EventLog).where(EventLog.user_id == row.user_id, EventLog.etype == "quiz_eval")).all()
        practiced = set()
        for event in practice_events:
            if not event_in_scope(event.payload):
                continue
            # Old events without objective-level provenance conservatively protect all scores.
            practiced.update((event.payload or {}).get("per_kp") or value["knowledge_mastery"])
        applied = set(value.get("baseline_assessment_applied_kps", []))
        for skill in report["skills"]:
            if skill["attempts"] >= 3 and not skill.get("after_intro") and skill["kp"] not in practiced | applied:
                value["knowledge_mastery"][skill["kp"]] = round(min(0.75, max(0.15, (1 + skill["correct"]) / (2 + skill["attempts"]))), 4)
                applied.add(skill["kp"])
        value["baseline_assessment_applied_kps"] = sorted(applied)
        value["focus_kps"] = [s["kp"] for s in report["skills"] if s["status"] in ("gap", "developing")][:8]
        _apply_survey_context(value, data["survey"])
        profile.data = value
        profile.version = (profile.version or 0) + 1
        path = plan_path(value, generated_by="entry_assessment")
        stored_path = db.get(PathPlan, row.user_id) if not current_space() else None
        if current_space():
            profile.path = path
        elif stored_path:
            stored_path.data = path
        else:
            db.add(PathPlan(user_id=row.user_id, data=path))
        db.add(PersonalizationDecision(user_id=row.user_id, kind="learning_path", profile_version=profile.version,
            inputs={"assessment_id": row.id, "coverage": report["coverage"]},
            output={"next_kp": path.get("next_kp"), "generated_by": "entry_assessment"},
            reason="独立作答用于首次先验，已有练习证据保持优先；日历依据本次作答和时间预算"))
    _build_materials(db, row, data, plan_evidence)
    _save_journey(db, row.user_id, row.id, "plan")
    db.add(EventLog(user_id=row.user_id, etype="entry_assessment", payload={"notebook_id": notebook_id(), "assessment_id": row.id, "bank_version": data["bank_version"], "report": report}))


def _build_materials(db, row, data, report):
    if data.get("course_snapshot"):
        return _course_materials(db, row, data, report)
    """Keep every measured task paired with current learner-specific material."""
    materials = []
    material_skills = [s for s in report["skills"] if s.get("in_scope", True) and s["status"] != "unmeasured"]
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
        seen = {a["question_id"] for a in data["answers"]}
        practice = [q for q in data["bank"] if q["kp"] == skill["kp"] and q["id"] not in seen][:2]
        data["exposed_question_ids"] = sorted(set(data.get("exposed_question_ids", [])) | {q["id"] for q in practice})
        exercises = "\n\n".join(f"### 练习 {i + 1}\n{q['stem']}\n" + "\n".join(f"- {chr(65+j)}. {o}" for j, o in enumerate(q["options"])) + ("\n（多选）" if q["type"] == "multiple" else "") for i, q in enumerate(practice))
        checks = "\n\n".join(f"练习 {i + 1}：{'、'.join(q['answer']) if isinstance(q['answer'], list) else q['answer']}。{q['explain']}" for i, q in enumerate(practice))
        markdown = f"# {skill['name']} · 起点学习资料\n\n依据{'近期独立作答' if skill.get('practice_updated') else '本次起点作答'} {skill['correct']}/{skill['attempts']}：{instruction}\n\n{lesson_guidance(data['survey'], skill)}\n\n## 起点错题回顾\n\n{recap or '本次该知识点没有错题；仍需换题和延迟复测确认。'}\n\n## 课程讲义\n\n{body}\n\n## 先尝试，再核对\n\n{exercises or '合上资料，用自己的话解释关键步骤，再请小知给一道新题。'}\n\n## 核对与复盘\n\n{checks or '请用课程讲义核对自己的解释。'}\n\n资料内练习用于自学，不计测评分。请在学习工坊完成新的无提示题，之后返回计划查看调整。\n\n来源：课程自编种子讲义 {filename}（CC BY-SA 4.0）；本次诊断题解析与自编练习。"
        resource_id = f"baseline-{row.id}-{skill['kp']}"
        resource = Resource(id=resource_id, user_id=row.user_id, kind="doc", kp=skill["kp"], title=f"起点资料 · {skill['name']}",
                            payload={"markdown": markdown}, citations=[{"source": filename, "chapter": skill["name"]}], safety={"source": "course_seed", "generated_by": "entry_assessment"})
        db.merge(resource)
        materials.append({"id": resource_id, "kp": skill["kp"], "title": resource.title, "markdown": markdown})
    data["materials"] = materials

def _course_materials(db, row, data, report):
    course = data["course_snapshot"]
    materials = []
    for skill in report["skills"]:
        kp = skill["kp"]
        if not skill.get("in_scope", True):
            continue
        body = course.get("lessons", {}).get(kp)
        if not body:
            continue
        evidence = course.get("evidence", {}).get(kp, [])
        source_text = "\n\n".join(
            (f"### [{item['source']} · {item.get('chapter', '')}]({item['url']})\n\n版本 {item.get('version', '')} · 对应章节原文\n\n{item['text']}"
             if item.get("url") else f"### {item['source']} · {item.get('location_kind', '片段')} {item.get('page', '')}\n\n{item['text']}")
            for item in evidence)
        wrong = [q for q in report["explanations"] if q["kp"] == kp and not q["correct"] and q["status"] != "skipped"]
        recap = "\n\n".join(f"### {q['stem']}\n\n{q['explain']}" for q in wrong)
        source_note = "围绕当前主题由模型生成；未使用上传文件，请结合教材核对。" if course["kind"] == "generated" else "本课程自编入门讲义；未使用上传文件。"
        if course["kind"] == "ds_algo":
            source_note = f"课程自编种子讲义 {LESSONS.get(kp, '')}（CC BY-SA 4.0）；未使用上传文件。"
        markdown = (f"# {skill['name']} · {course['title']}\n\n"
            f"本次作答：{skill['correct']}/{skill['attempts']}。{skill['label']}。\n\n"
            f"{lesson_guidance(data['survey'], skill)}\n\n## 本课目标\n\n解释核心概念，并在新情境中独立应用。\n\n"
            f"## 概念与分步示例\n\n{body}\n\n## 起点错题回顾\n\n{recap or '没有已记录的错题，仍需新题复核。'}\n\n"
            "## 轮到你尝试\n\n1. 合上讲义，用自己的话解释一个核心概念。\n2. 改变例题中的条件，自己完成推理。\n"
            + ("3. 点击本页的无提示新题按钮，独立作答后查看反馈与计划调整。\n\n" if course.get("practice_bank") else
               "3. 点击向小知提问，索取一道未见过的新题；先独立作答，卡住再展开提示。\n\n") +
            f"## 内容依据\n\n{source_text or source_note}\n\n{course['boundary']}\n\n"
            "看例题和重做原题属于学习过程，不计为新的独立掌握证据。")
        rid = f"baseline-{row.id}-{kp}"
        citations = [{k: v for k, v in e.items() if k != "text"} for e in evidence]
        resource = Resource(id=rid, user_id=row.user_id, kind="doc", kp=kp, title=f"{course['title']} · {skill['name']}",
            payload={"markdown": markdown, "notebook_id": data["notebook_id"], "course_revision": course["revision"],
                     "source_ids": course.get("source_ids", [])}, citations=citations,
            safety={"source": "course_assessment", "generated_by": "entry_assessment"})
        db.merge(resource)
        materials.append({"id": rid, "kp": kp, "title": resource.title, "markdown": markdown})
    data["materials"] = materials


def answer(user_id: str, assessment_id: str, payload: dict) -> dict:
    with session() as db:
        row = _owned(db, user_id, assessment_id)
        data = copy.deepcopy(row.data)
        existing = next((a for a in data["answers"] if a["question_id"] == payload["question_id"]), None)
        if existing:
            if any(existing.get(k) != payload.get(k) for k in ("choice", "status", "confidence")) or sorted(existing.get("choices") or []) != sorted(payload.get("choices") or []):
                raise HTTPException(409, "该题已提交，请继续下一题")
            return _public(row)
        if row.revision != payload["revision"] or data["status"] != "active":
            raise HTTPException(409, "测评已更新，请刷新后继续")
        q = _next(data)
        if not q or q["id"] != payload["question_id"]:
            raise HTTPException(409, "请提交当前题目")
        options = {chr(65+i) for i in range(len(q["options"]))}
        selected = payload.get("choices") or []
        if payload["status"] == "answered":
            if q["type"] == "multiple":
                if not selected or len(selected) != len(set(selected)) or not set(selected) <= options or payload.get("choice") is not None:
                    raise HTTPException(422, "请勾选有效且不重复的选项")
            elif payload.get("choice") not in options or selected:
                raise HTTPException(422, "请选择一个有效答案")
        if payload["status"] != "answered" and (payload.get("choice") is not None or selected):
            raise HTTPException(422, "跳过或不会的题不能同时选择答案")
        correct = set(selected) == set(q["answer"]) if q["type"] == "multiple" else payload.get("choice") == q["answer"]
        data["answers"].append({**payload, "kp": q["kp"], "correct": payload["status"] == "answered" and correct})
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
        survey = copy.deepcopy(survey)
        for key in ("notebook_id", "course_key", "course_title", "source_ids", "course_revision", "target_kps"):
            if key in data["survey"]:
                survey[key] = data["survey"][key]
        if data["status"] != "completed":
            raise HTTPException(409, "请先完成测评")
        completed = {task["id"] for day in data["plan"]["days"] for task in day["tasks"] if task["done"]}
        data["survey"] = survey
        data["plan"] = study_plan(data.get("plan_evidence", data["report"]), survey)
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
        _build_materials(db, row, data, data.get("plan_evidence", data["report"]))
        row.data, row.revision = data, revision + 1
        profile = profile_row(db, user_id)
        if profile:
            value = copy.deepcopy(profile.data)
            _apply_survey_context(value, survey)
            profile.data, profile.version = value, (profile.version or 0) + 1
        db.commit()
        return _public(row)


def extend(user_id: str, assessment_id: str, revision: int) -> dict:
    """Continue the same evidence record; completed questions are never reissued."""
    with session() as db:
        row = _owned(db, user_id, assessment_id)
        data = copy.deepcopy(row.data)
        if data["status"] == "active" and data["mode"] == "comprehensive":
            return _public(row)
        if row.revision != revision or data["status"] != "completed" or data["mode"] == "comprehensive":
            raise HTTPException(409, "测评已更新，请重新读取后继续")
        snapshot = {q["id"]: q for q in data["bank"]}
        for q in question_bank():
            snapshot.setdefault(q["id"], q)
        targets = topological_order()
        data.update(bank=list(snapshot.values()), mode="comprehensive", status="active", targets=targets,
                    limit=min(48, sum(q["kp"] in targets for q in snapshot.values())))
        data["bank_version"] = hashlib.sha256(json.dumps(data["bank"], ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]
        changed = db.execute(update(AssessmentSession).where(AssessmentSession.id == row.id, AssessmentSession.revision == revision).values(revision=revision + 1))
        if changed.rowcount != 1:
            raise HTTPException(409, "测评已更新，请重新读取后继续")
        row.data, row.revision = data, revision + 1
        _save_journey(db, user_id, row.id, "assessment")
        if _next(data) is None:
            _finish(db, row, data)
            row.data = data
        db.commit()
        return _public(row)


def evidence_key(kp: str, stem: str) -> str:
    return hashlib.sha256((kp + ":" + "".join(stem.split())).encode()).hexdigest()


def _refresh_from_practice(db, row) -> None:
    """Refresh the calendar on return, from new independent questions only.

    Keep the initial report intact. Repeated questions and assisted answers do
    not create additional independent samples; legacy logs are not inferred.
    """
    data = copy.deepcopy(row.data)
    if "practice_cursor" not in data:
        return
    events = db.scalars(select(EventLog).where(EventLog.user_id == row.user_id, EventLog.etype == "quiz_eval", EventLog.id > data["practice_cursor"]).order_by(EventLog.id)).all()
    events = [event for event in events if event_in_scope(event.payload)]
    if not events:
        return
    seen = set(data.get("practice_seen", []))
    answered_ids = {a["question_id"] for a in data["answers"]} | set(data.get("exposed_question_ids", []))
    seen.update(evidence_key(q["kp"], q["stem"]) for q in data["bank"] if q["id"] in answered_ids)
    history = data.setdefault("practice_history", {})
    evidence = copy.deepcopy(data.get("plan_evidence", data["report"]))
    skills = {s["kp"]: s for s in evidence["skills"]}
    changed_skills = set()
    for event in events:
        if not event_in_scope(event.payload):
            continue
        for item in (event.payload or {}).get("learning_evidence", []):
            kp, key = item.get("kp"), item.get("key")
            if not key or key in seen or kp not in topological_order():
                continue
            seen.add(key)
            if item.get("support_level") != "independent":
                continue
            if kp not in skills:
                skill = {"kp": kp, "name": kp_name(kp), "attempts": 0, "correct": 0, "accuracy": None,
                         "status": "unmeasured", "label": STATUS_LABELS["unmeasured"], "in_scope": False,
                         "high_confidence_errors": 0, "question_ids": []}
                evidence["skills"].append(skill)
                skills[kp] = skill
            trail = history.setdefault(kp, [bool(a["correct"]) for a in data["answers"] if a["kp"] == kp and a["status"] != "skipped"][-3:])
            trail.append(bool(item["correct"]))
            history[kp] = trail[-3:]
            count, correct = len(history[kp]), sum(history[kp])
            status = "unmeasured" if count < 3 else "gap" if correct / count < .5 else "strength" if correct / count >= .8 else "developing"
            skills[kp].update(attempts=count, correct=correct, accuracy=correct / count, status=status,
                              label=STATUS_LABELS[status], in_scope=True, practice_updated=True)
            changed_skills.add(kp)
    data["practice_cursor"] = events[-1].id
    data["practice_seen"] = sorted(seen)
    if changed_skills:
        completed = {t["id"] for day in data["plan"]["days"] for t in day["tasks"] if t["done"] and t["kp"] not in changed_skills}
        data["plan_evidence"] = evidence
        data["plan"] = study_plan(evidence, data["survey"])
        retained = set()
        for day in data["plan"]["days"]:
            for task in day["tasks"]:
                if task["id"] in completed and all(dep in retained for dep in task["requires"]):
                    task["done"] = True
                    retained.add(task["id"])
        _build_materials(db, row, data, evidence)
        data["plan"]["practice_update"] = "已根据新的独立作答调整：" + "、".join(kp_name(k) for k in sorted(changed_skills)) + "。起点报告保留原始记录。"
    revision = row.revision
    changed = db.execute(update(AssessmentSession).where(AssessmentSession.id == row.id, AssessmentSession.revision == revision).values(revision=revision + 1))
    if changed.rowcount != 1:
        raise HTTPException(409, "计划正在更新，请重新读取")
    row.data, row.revision = data, revision + 1

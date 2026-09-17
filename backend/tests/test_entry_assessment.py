"""Assessment evidence, tenant isolation, atomic persistence and calendar limits."""
from __future__ import annotations

import copy
import datetime as dt
import uuid
from collections import Counter
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.assessment import StudySurvey
from app.auth import bind_request_user, reset_request_user
from app.main import app
from app.models.db import session
from app.models.entities import AssessmentSession, EventLog, Resource
from app.services import assessment_service as service
from app.services.course_service import recommend, video_urls
from app.services.knowledge_graph import all_kp_ids
from app.services.profile_service import complete_onboarding, get_profile, log_event, merge_profile


@pytest.fixture
def user():
    uid = f"entry-test-{uuid.uuid4().hex}"
    get_profile(uid)
    return uid


def survey(**kwargs):
    return StudySurvey(**kwargs).model_dump(mode="json")


def respond(user, state, outcome="correct", **extra):
    q = next(q for q in service.question_bank() if q["id"] == state["question"]["id"])
    multiple = q["type"] == "multiple"
    choice = None if multiple else q["answer"] if outcome == "correct" else next(k for k in ("A", "B") if k != q["answer"])
    payload = {"revision": state["revision"], "question_id": q["id"], "choices": (q["answer"] if outcome == "correct" else ["A"]) if multiple else [],
        "status": "answered", "choice": choice, "confidence": .9, "elapsed_ms": 3000, **extra}
    if payload["status"] != "answered":
        payload["choices"] = []
    return service.answer(user, state["id"], payload)


def finish(user, mode="foundation", outcome="correct", **options):
    state = service.start(user, survey(**options), mode)
    while state["question"]:
        state = respond(user, state, outcome)
    return state


def test_bank_covers_every_course_objective_without_duplicate_ids():
    bank = service.question_bank()
    counts = Counter(q["kp"] for q in bank)
    assert len({q["id"] for q in bank}) == len(bank)
    assert set(counts) == set(all_kp_ids())
    assert min(counts.values()) >= 3
    for q in bank:
        assert 2 <= len(q["options"]) <= 5
        keys = q["answer"] if isinstance(q["answer"], list) else [q["answer"]]
        assert set(keys) <= {chr(65 + i) for i in range(len(q["options"]))}
        assert len(keys) == len(set(keys))
        assert q["explain"] and 1 <= q["difficulty"] <= 5


def test_resume_idempotency_and_keys_remain_private(user):
    state = service.start(user, survey(), "foundation")
    assert set(state["question"]) == {"id", "stem", "options", "topic", "type", "instruction"}
    assert state["report"] is None and state["materials"] == []
    first = copy.deepcopy(state)
    state = respond(user, state)
    assert state["answered"] == 1
    assert service.latest(user)["assessment"] == state
    assert respond(user, first) == state
    with pytest.raises(HTTPException) as error:
        respond(user, first, "wrong")
    assert error.value.status_code == 409
    stale = {**state, "revision": 0}
    with pytest.raises(HTTPException) as error:
        respond(user, stale)
    assert error.value.status_code == 409


def test_other_users_cannot_read_or_submit_an_assessment(user):
    state = service.start(user, survey(), "foundation")
    other = f"other-{uuid.uuid4().hex}"
    get_profile(other)
    assert service.latest(other)["assessment"] is None
    with pytest.raises(HTTPException) as error:
        respond(other, state)
    assert error.value.status_code == 404
    token = bind_request_user(other)
    try:
        with pytest.raises(HTTPException) as error:
            service.latest(user)
        assert error.value.status_code == 403
    finally:
        reset_request_user(token)


def test_skipping_never_becomes_evidence_of_failure(user):
    state = service.start(user, survey(), "foundation")
    while state["question"]:
        state = respond(user, state, status="skipped", choice=None, confidence=None)
    assert state["status"] == "completed"
    assert state["report"]["coverage"] == 0
    assert all(s["accuracy"] is None and s["status"] == "unmeasured" for s in state["report"]["skills"])
    assert all(t["kind"] == "diagnose" for day in state["plan"]["days"] for t in day["tasks"])
    assert all(v == .3 for v in get_profile(user)["knowledge_mastery"].values())


def test_dont_know_is_a_gap_and_answers_produce_materials_and_profile(user):
    state = service.start(user, survey(), "foundation")
    while state["question"]:
        state = respond(user, state, status="dont_know", choice=None, confidence=None)
    assert state["answered"] == 18
    assert state["report"]["coverage"] == 6
    assert all(s["status"] == "gap" for s in state["report"]["skills"])
    assert state["report"]["calibration_samples"] == 0
    assert len(state["materials"]) == 6
    assert "## 课程讲义" in state["materials"][0]["markdown"]
    assert get_profile(user)["knowledge_mastery"]["complexity"] == .2
    with session() as db:
        assert db.query(Resource).filter(Resource.user_id == user).count() == 6
        assert db.query(EventLog).filter(EventLog.user_id == user, EventLog.etype == "entry_assessment").count() == 1


def test_correct_answers_make_transfer_tasks_but_not_full_mastery(user):
    state = finish(user)
    assert state["answered"] == 18
    assert state["report"]["coverage"] == 6
    assert all(s["status"] == "strength" for s in state["report"]["skills"])
    assert state["materials"]
    assert get_profile(user)["knowledge_mastery"]["complexity"] == .75
    kinds = {t["kind"] for day in state["plan"]["days"] for t in day["tasks"]}
    assert kinds == {"transfer", "review"}
    answered_ids = [q["id"] for q in state["report"]["explanations"] if q["kp"] == "complexity"]
    facets = {q.get("facet") for q in service.question_bank() if q["id"] in answered_ids}
    assert facets == {"asymptotic", "nested", "space"}


def test_an_unmeasured_first_session_does_not_block_later_real_evidence(user):
    state = service.start(user, survey(), "foundation")
    while state["question"]:
        state = respond(user, state, status="skipped", choice=None, confidence=None)
    assert get_profile(user)["baseline_assessment_applied_kps"] == []
    finish(user)
    assert get_profile(user)["knowledge_mastery"]["complexity"] == .75


@pytest.mark.asyncio
async def test_tutor_words_do_not_become_learner_preferences(user):
    from app.agents.profile_agent import run
    state = {"user_id": user, "messages": [{"role": "assistant", "content": "我们看图准备期末考试，再动手写代码。"}]}
    result = await run(state)
    assert result["student_profile"]["goal"] == "未知"
    assert result["student_profile"]["cognitive_style"] == "未知"


def test_full_course_has_forty_eight_independent_answers(user):
    state = finish(user, "comprehensive", "wrong")
    assert state["answered"] == 48
    assert state["report"]["coverage"] == 16
    assert sum(s["high_confidence_errors"] for s in state["report"]["skills"]) == 48


def test_onboarding_and_reassessment_cannot_erase_prior_practice(user):
    merge_profile(user, {"knowledge_mastery": {"complexity": .91}})
    log_event(user, "quiz_eval", {"per_kp": {"complexity": {"mastery": .91}}})
    complete_onboarding(user, {"current_level": "刚开始接触", "topic": "树与图", "style": "图示和例子"})
    assert get_profile(user)["knowledge_mastery"]["complexity"] == .91
    finish(user, outcome="wrong")
    assert get_profile(user)["knowledge_mastery"]["complexity"] == .91
    assert get_profile(user)["cognitive_style"] == "未知"


@pytest.mark.parametrize("minutes", [8, 12, 30, 180])
def test_calendar_never_overbooks_or_reverses_dependencies(minutes):
    report = {"skills": [{"kp": kp, "status": "gap", "attempts": 3, "correct": 0} for kp in all_kp_ids()]}
    calendar = service.study_plan(report, survey(daily_minutes=minutes, study_days=[2, 4]), today=dt.date(2026, 9, 15))
    assigned = {}
    review_dates = {}
    for day in calendar["days"]:
        assert day["minutes"] == sum(t["minutes"] for t in day["tasks"])
        assert day["minutes"] <= day["capacity"]
        assert not day["tasks"] or dt.date.fromisoformat(day["date"]).isoweekday() in (2, 4)
        for task in day["tasks"]:
            assert all(dep in assigned and assigned[dep] <= day["date"] for dep in task["requires"])
            assigned[task["id"]] = day["date"]
            if task["kind"] == "review":
                assert assigned[task["requires"][0]] < day["date"]
                assert day["date"] not in review_dates.setdefault(task["kp"], set())
                review_dates[task["kp"]].add(day["date"])
    assert assigned  # Even an eight-minute budget can start learning.


def test_task_progress_requires_prerequisites_and_never_inflates_mastery(user):
    state = finish(user)
    tasks = [t for day in state["plan"]["days"] for t in day["tasks"]]
    later = next(t for t in tasks if t["requires"])
    before = get_profile(user)["knowledge_mastery"]
    with pytest.raises(HTTPException):
        service.update_task(user, state["id"], later["id"], True)
    first = tasks[0]
    updated = service.update_task(user, state["id"], first["id"], True)
    assert next(t for d in updated["plan"]["days"] for t in d["tasks"] if t["id"] == first["id"])["done"]
    assert get_profile(user)["knowledge_mastery"] == before
    replanned = service.replan(user, state["id"], survey(daily_minutes=8, study_days=[1, 2, 3, 4, 5, 6, 7]))
    assert any(t["id"] == first["id"] and t["done"] for d in replanned["plan"]["days"] for t in d["tasks"])


def test_finish_rolls_back_answer_report_and_materials_on_failure(user, monkeypatch):
    state = service.start(user, survey(), "foundation")
    for _ in range(17):
        state = respond(user, state, "wrong")
    real_finish = service._finish
    def fail_after_materials(*args):
        real_finish(*args)
        raise RuntimeError("simulated interrupted commit")
    monkeypatch.setattr(service, "_finish", fail_after_materials)
    with pytest.raises(RuntimeError):
        respond(user, state, "wrong")
    assert service.latest(user)["assessment"]["answered"] == 17
    assert get_profile(user)["knowledge_mastery"]["complexity"] == .3
    with session() as db:
        assert not db.query(Resource).filter(Resource.user_id == user).count()
    monkeypatch.setattr(service, "_finish", real_finish)
    assert respond(user, state, "wrong")["status"] == "completed"


def test_catalog_links_and_empty_search_are_honest(user):
    result = recommend(user, kp="complexity")
    assert result["source"] == "curated_catalog" and len(result["items"]) >= 2
    for item in result["items"]:
        preview = urlparse(item["preview_url"])
        assert preview.scheme == "https" and preview.hostname == "player.bilibili.com"
        assert parse_qs(preview.query)["autoplay"] == ["0"]
        assert urlparse(item["watch_url"]).hostname == "www.bilibili.com"
    empty = recommend(user, '海洋生物学 & "新课"')
    assert empty["items"] == []
    assert parse_qs(urlparse(empty["search_url"]).query)["keyword"] == ['海洋生物学 & "新课"']
    with pytest.raises(ValueError):
        video_urls("https://evil.example/video")


def test_api_requires_login_and_rejects_invalid_calendars(monkeypatch):
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    monkeypatch.setenv("AUTH_SECRET", "entry-test-only-abcdefghijklmnopqrstuvwxyz-0123456789")
    from app.config import get_settings
    get_settings.cache_clear()
    with TestClient(app) as client:
        assert client.get("/api/assessment").status_code == 401
        assert client.get("/api/courses").status_code == 401
    with pytest.raises(ValueError):
        StudySurvey(study_days=[1, 1])
    with pytest.raises(ValueError):
        StudySurvey(target_date="2020-01-01")


def test_screening_multiselect_context_drives_plan_and_materials(user):
    options = dict(goal="编程项目应用", goals=["编程项目应用", "准备课程考试"],
                   barriers=["application", "coding"], supports=["steps", "small_steps"],
                   daily_minutes=20, study_cue="晚饭后坐到书桌前")
    state = finish(user, "screening", "wrong", **options)
    assert state["answered"] == state["maximum"] == 12
    assert state["report"]["coverage"] == 4 and state["report"]["total_skills"] == 16
    assert sum(s["status"] == "unmeasured" for s in state["report"]["skills"]) == 12
    context = get_profile(user)["learning_intake"]
    assert context["goals"] == options["goals"] and context["barriers"] == options["barriers"]
    assert get_profile(user)["onboarding_completed"] is True
    tasks = [t for d in state["plan"]["days"] for t in d["tasks"]]
    assert tasks and all(t["minutes"] <= 8 for t in tasks)
    assert "代码追踪" in tasks[0]["title"]
    assert "伪代码" in tasks[0]["goal"] and "准备课程考试" in tasks[0]["goal"]
    markdown = state["materials"][0]["markdown"]
    assert "补全关键步骤" in markdown and "伪代码" in markdown and "晚饭后" in markdown
    other = service.study_plan(state["report"], survey(goal="准备课程考试", goals=["准备课程考试"], daily_minutes=30))
    assert "考点" in other["days"][0]["tasks"][0]["title"] or any("考点" in t["title"] for d in other["days"] for t in d["tasks"])


def test_continue_screening_preserves_answers_progress_and_never_repeats_exposed_questions(user):
    state = finish(user, "screening")
    first = next(t for d in state["plan"]["days"] for t in d["tasks"])
    state = service.update_task(user, state["id"], first["id"], True)
    with session() as db:
        exposed = set(db.get(AssessmentSession, state["id"]).data.get("exposed_question_ids", []))
    old_ids = {a["id"] for a in state["report"]["explanations"]}
    continued = service.extend(user, state["id"], state["revision"])
    assert continued["answered"] == 12 and continued["survey"] == state["survey"]
    assert service.extend(user, state["id"], state["revision"]) == continued
    while continued["question"]:
        assert continued["question"]["id"] not in old_ids | exposed
        continued = respond(user, continued)
    assert continued["answered"] == 48 and continued["report"]["coverage"] == 16
    assert any(t["id"] == first["id"] and t["done"] for d in continued["plan"]["days"] for t in d["tasks"])
    with session() as db:
        ids = [r.id for r in db.query(Resource).filter(Resource.user_id == user)]
        assert len(ids) == len(set(ids))


def test_multiple_questions_require_the_exact_set_and_reject_invalid_submissions(user):
    state = service.start(user, survey(), "screening")
    while state["question"] and state["question"]["type"] != "multiple":
        state = respond(user, state)
    assert state["question"] and state["question"]["type"] == "multiple"
    q = next(q for q in service.question_bank() if q["id"] == state["question"]["id"])
    for selected in ([], ["Z"], ["A", "A"]):
        with pytest.raises(HTTPException) as error:
            service.answer(user, state["id"], {"revision": state["revision"], "question_id": q["id"], "status": "answered", "choice": None, "choices": selected, "confidence": None})
        assert error.value.status_code == 422
    original = copy.deepcopy(state)
    state = respond(user, state)
    assert respond(user, original, choices=list(reversed(q["answer"]))) == state
    with session() as db:
        assert db.get(AssessmentSession, state["id"]).data["answers"][-1]["correct"]


def test_invalid_multiselect_context_is_rejected():
    for options in (dict(goals=["准备课程考试"], goal="编程项目应用"), dict(barriers=["coding", "coding"]),
                    dict(supports=["invented"]), dict(goals=["探索学习起点", "兴趣理解"], goal="兴趣理解")):
        with pytest.raises(ValueError):
            StudySurvey(**options)


def test_intro_does_not_inflate_baseline_and_new_independent_practice_refreshes_plan(user):
    state = finish(user, "foundation", intro_practiced=True)
    assert get_profile(user)["knowledge_mastery"]["stack"] == .3
    assert next(s for s in state["report"]["skills"] if s["kp"] == "stack")["after_intro"]
    original_report = copy.deepcopy(state["report"])
    from app.agents.eval_agent import evaluate_answers
    # Three new question stems, independently answered incorrectly, change the task.
    evaluate_answers(user, [{"question_id": f"new-{i}", "stem": f"新情境核验 {i}", "kp": "complexity", "correct": False, "support_level": "independent"} for i in range(3)])
    refreshed = service.latest(user)["assessment"]
    assert refreshed["report"] == original_report
    assert "新的独立作答" in refreshed["plan"]["practice_update"]
    assert any(t["id"] == "complexity-study" for d in refreshed["plan"]["days"] for t in d["tasks"])
    # Seeing help, or repeating those same stems, cannot create new samples.
    evaluate_answers(user, [{"question_id": f"new-{i}", "stem": f"新情境核验 {i}", "kp": "complexity", "correct": True, "support_level": "independent"} for i in range(3)] + [{"stem": "已给提示", "kp": "complexity", "correct": True, "support_level": "hinted"}])
    repeated = service.latest(user)["assessment"]
    assert repeated["plan"] == refreshed["plan"]


def test_retrying_start_resumes_active_session_instead_of_losing_answers(user):
    state = service.start(user, survey(), "screening")
    state = respond(user, state)
    assert service.start(user, survey(), "screening") == state


def test_changed_goals_update_materials_and_clear_old_legacy_goal(user):
    state = finish(user, "screening", goal="编程项目应用", goals=["编程项目应用"])
    updated = service.replan(user, state["id"], survey(goal="掌握课程基础", goals=["掌握课程基础"], supports=["examples"]))
    assert get_profile(user)["goal"] == "未知"
    assert {m["kp"] for m in updated["materials"]} == {s["kp"] for s in state["report"]["skills"] if s["attempts"] >= 3}
    for material in updated["materials"]:
        assert "当前优先：掌握课程基础" in material["markdown"]
        assert "给一个完整例题" in material["markdown"]
        assert "当前优先：编程项目应用" not in material["markdown"]
        with session() as db:
            assert db.get(Resource, material["id"]).payload["markdown"] == material["markdown"]


def test_previously_seen_and_assisted_questions_cannot_become_new_independent_evidence(user):
    from app.agents.eval_agent import evaluate_answers
    old = {"stem": "以前做过的题", "kp": "complexity", "correct": False, "support_level": "independent"}
    evaluate_answers(user, [old])
    state = finish(user, "screening")
    hinted = {"stem": "已经给过提示的题", "kp": "complexity", "correct": False, "support_level": "hinted"}
    evaluate_answers(user, [hinted])
    assert service.latest(user)["assessment"]["plan"] == state["plan"]
    evaluate_answers(user, [old, {**hinted, "support_level": "independent"}])
    assert service.latest(user)["assessment"]["plan"] == state["plan"]

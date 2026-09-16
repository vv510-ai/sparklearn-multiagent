"""Course isolation, actual source binding, resume and prompt propagation."""
import asyncio
import copy
import json
import uuid

import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.models.db import session
from app.models.entities import AssessmentSession, Resource, EventLog
from app.services.learning_scope import course_scope, current_space
from app.services.knowledge_graph import all_kp_ids
from app.prompt_templates import invoke_learning_prompt


@pytest.fixture
def learner(monkeypatch):
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    monkeypatch.setenv("AUTH_SECRET", "learning-spaces-test-only-0123456789abcdef")
    config.get_settings.cache_clear()
    with TestClient(app) as client:
        result = client.post("/api/auth/register", json={"email": f"spaces-{uuid.uuid4().hex}@example.test", "password": "Course-Test-Password!", "name": "课程验收"})
        assert result.status_code == 201, result.text
        account = result.json()
        client.headers["Authorization"] = f"Bearer {account['access_token']}"
        assert client.get("/api/onboarding").json()["required"]
        yield client, account["user"]["id"]


def prepare(client, user, key="python", title="Python 入门", goal="独立解题与纠错"):
    book = client.post("/api/notebooks", json={"user_id": user, "title": title}).json()
    survey = {"notebook_id": book["id"], "course_key": key, "course_title": title, "goal": goal, "goals": [goal],
        "daily_minutes": 20, "study_days": [1, 3, 5], "barriers": ["application"], "supports": ["steps"]}
    response = client.post(f"/api/notebooks/{book['id']}/learning/prepare", json={"title": title, "course_key": key, "survey": survey})
    assert response.status_code == 200, response.text
    course = response.json()
    assert "bank" not in course and "lessons" not in course
    survey.update(course_revision=course["revision"], target_kps=[n["id"] for n in course["outline"]])
    return book, survey, course


def finish(client, survey, correct=True):
    response = client.post("/api/assessment/start", json={"survey": survey, "mode": "comprehensive"})
    assert response.status_code == 200, response.text
    state = response.json()
    with session() as db:
        bank = {q["id"]: q for q in db.get(AssessmentSession, state["id"]).data["bank"]}
    while state["question"]:
        question = state["question"]
        assert "answer" not in question and "explain" not in question
        q = bank[question["id"]]
        response = client.post(f"/api/assessment/{state['id']}/answers", json={
            "revision": state["revision"], "question_id": question["id"], "status": "answered" if correct else "dont_know",
            "choice": q["answer"] if correct and q["type"] == "single" else None,
            "choices": q["answer"] if correct and q["type"] == "multiple" else []})
        assert response.status_code == 200, response.text
        state = response.json()
    return state


def test_two_curricula_keep_assessment_plan_profile_and_path_separate(learner):
    client, user = learner
    before = client.get(f"/api/profile/{user}").json()["knowledge_mastery"]
    py, py_survey, _ = prepare(client, user)
    maths, math_survey, _ = prepare(client, user, "calculus", "高等数学入门", "准备课程考试")
    py_result, math_result = finish(client, py_survey), finish(client, math_survey, False)
    assert py_result["report"]["coverage"] == math_result["report"]["coverage"] == 4
    assert py_result["answered"] == math_result["answered"] == 12
    for book, expected, prefix in ((py, py_result, "py_"), (maths, math_result, "calc_")):
        latest = client.get(f"/api/assessment?notebook_id={book['id']}").json()["assessment"]
        assert latest["id"] == expected["id"]
        profile = client.get(f"/api/profile/{user}?notebook_id={book['id']}").json()
        assert all(k.startswith(prefix) for k in profile["knowledge_mastery"])
        path = client.get(f"/api/path?user_id={user}&notebook_id={book['id']}").json()
        assert all(n["id"].startswith(prefix) for n in path["nodes"])
        assert all(d["minutes"] <= d["capacity"] for d in latest["plan"]["days"])
        assert latest["materials"] and "数据结构" not in latest["materials"][0]["markdown"]
    assert client.get(f"/api/profile/{user}").json()["knowledge_mastery"] == before
    assert client.get("/api/assessment").json()["assessment"] is None


def test_resume_onboarding_and_no_silent_new_attempt(learner):
    client, user = learner
    book, survey, course = prepare(client, user)
    unconfirmed = client.post("/api/assessment/start", json={"survey": {**survey, "course_revision": "stale"}})
    assert unconfirmed.status_code == 409
    first = client.post("/api/assessment/start", json={"survey": survey}).json()
    response = client.post(f"/api/assessment/{first['id']}/answers", json={"revision": first["revision"], "question_id": first["question"]["id"], "status": "dont_know"})
    assert response.status_code == 200
    resume = client.get("/api/onboarding").json()["resume"]
    assert resume == {"phase": "assessment", "notebook_id": book["id"], "assessment_id": first["id"]}
    again = client.post("/api/assessment/start", json={"survey": survey}).json()
    assert again["id"] == first["id"] and again["answered"] == 1
    changed = client.post(f"/api/notebooks/{book['id']}/learning/prepare", json={"title": "Changed", "course_key": "calculus", "survey": survey})
    assert changed.status_code == 409
    assert client.get(f"/api/assessment?notebook_id={book['id']}").json()["assessment"]["id"] == first["id"]


def test_background_prompts_use_current_course_and_no_cross_task_context(learner):
    client, user = learner
    py, _, _ = prepare(client, user)
    maths, _, _ = prepare(client, user, "calculus", "高等数学入门", "准备课程考试")
    async def read(book, marker):
        with course_scope(user, book["id"]):
            await asyncio.sleep(0)
            prompt = invoke_learning_prompt("doc.complete_notes", topic="本节", goal="学习", persona="", context="", conversation="").prompt
            assert marker in prompt and "每次只推进一个推理步骤" in prompt
            return current_space()["notebook_id"], all_kp_ids()
    async def run():
        return await asyncio.gather(read(py, "独立解题与纠错"), read(maths, "准备课程考试"))
    results = asyncio.run(run())
    assert results[0][0] == py["id"] and all(k.startswith("py_") for k in results[0][1])
    assert results[1][0] == maths["id"] and all(k.startswith("calc_") for k in results[1][1])
    assert current_space() is None


def test_upload_is_in_prompt_assessment_and_learning_materials(learner, monkeypatch):
    from app.services import course_learning_service
    client, user = learner
    book = client.post("/api/notebooks", json={"user_id": user, "title": "生态学笔记"}).json()
    body = "生产者通过光合作用将太阳能转化为化学能。消费者通过摄食获取能量。分解者把有机物分解为无机物。能量在食物链中逐级传递，并以热的形式散失。"
    upload = client.post("/api/knowledge/upload", data={"user_id": user, "notebook_id": book["id"], "title": "生态课资料"}, files={"file": ("ecology.txt", body.encode(), "text/plain")})
    assert upload.status_code == 200, upload.text
    source = upload.json()["source"]
    captured = []
    async def model(prompt, **kwargs):
        captured.append(prompt)
        assert body in prompt
        return json.dumps({"topics": [{"name": f"生态系统概念{i}", "objective": "区分生态系统中的能量来源", "lesson": "先区分生产者和消费者，再举生活中的食物链例子。", "chunk_ids": ["s1c1"], "quote": "生产者通过光合作用将太阳能转化为化学能。", "questions": [
            {"stem": f"第{i}组情境{j}：判断生产者的能量来源与转化。", "type": "multiple" if j == 2 else "single", "options": ["光合作用", "太阳能转化为化学能", "吞食动物", "不需能量"], "answer": ["A", "B"] if j == 2 else "A", "explain": "资料说明生产者通过光合作用将太阳能转化为化学能。", "difficulty": 1} for j in range(3)]} for i in range(3)]}, ensure_ascii=False)
    monkeypatch.setattr(course_learning_service, "llm_complete", model)
    survey = {"notebook_id": book["id"], "course_key": "custom", "course_title": "生态学笔记", "source_ids": [source["id"]], "goal": "看懂学习资料", "goals": ["看懂学习资料"]}
    response = client.post(f"/api/notebooks/{book['id']}/learning/prepare", json={"title": "生态学笔记", "source_ids": [source["id"]], "survey": survey})
    assert response.status_code == 200, response.text
    course = response.json()
    assert captured and course["sources"][0]["title"] == "生态课资料"
    assert course["sources"][0]["sha256"] and course["sources"][0]["location_kind"] == "片段"
    survey["course_revision"] = course["revision"]
    result = finish(client, survey, False)
    assert all("生态课资料" in m["markdown"] and "生产者通过光合作用" in m["markdown"] for m in result["materials"])
    other = client.post("/api/notebooks", json={"user_id": user, "title": "其他课程"}).json()
    wrong_scope = client.post(f"/api/notebooks/{other['id']}/learning/prepare", json={"title": "其他课程", "source_ids": [source["id"]], "survey": survey})
    assert wrong_scope.status_code == 400


def test_other_learner_cannot_read_or_prepare_space(learner):
    client, user = learner
    book, _, _ = prepare(client, user)
    assert client.get(f"/api/path?user_id={user}&notebook_id=missing").status_code == 404
    with TestClient(app) as other:
        account = other.post("/api/auth/register", json={"email": f"other-{uuid.uuid4().hex}@example.test", "password": "Course-Test-Password!", "name": "其他人"}).json()
        other.headers["Authorization"] = f"Bearer {account['access_token']}"
        assert other.get(f"/api/notebooks/{book['id']}/learning").status_code == 404
        assert other.post(f"/api/notebooks/{book['id']}/learning/prepare", json={"title": "别人的课", "course_key": "python"}).status_code == 404


def test_quiz_evidence_stays_in_its_course(learner):
    client, user = learner
    py, survey, _ = prepare(client, user)
    result = finish(client, survey, False)
    maths, _, _ = prepare(client, user, "calculus", "高等数学入门")
    rid = f"test-course-quiz-{uuid.uuid4().hex}"
    with session() as db:
        db.add(Resource(id=rid, user_id=user, kind="quiz", kp="py_values", title="变量新题", payload={"notebook_id": py["id"], "questions": [{"id": "fresh", "kp": "py_values", "type": "single", "stem": "a = 11; b = a + 5，b 是多少？", "options": ["16", "11", "5", "6"], "answer": "A", "explain": "先计算 11+5=16，再赋值给 b。", "difficulty": 1}]}))
        db.commit()
    response = client.post("/api/eval/submit", json={"user_id": user, "quiz_resource_id": rid, "kp": "py_values", "answers": [{"question_id": "fresh", "answer": "A", "correct": False}]})
    assert response.status_code == 200, response.text
    assert response.json()["accuracy"] == 1
    assert response.json()["per_kp"][0]["kp"] == "py_values"
    math_profile = client.get(f"/api/profile/{user}?notebook_id={maths['id']}").json()
    assert "py_values" not in math_profile["knowledge_mastery"]
    updated = client.get(f"/api/assessment?notebook_id={py['id']}").json()["assessment"]
    assert "变量与表达式" in updated["plan"]["practice_update"]
    assert updated["report"] == result["report"]
    ledger = client.get(f"/api/eval/evidence?user_id={user}&notebook_id={py['id']}").json()
    assert ledger["summary"]["rounds"] == 1
    assert ledger["items"][0]["knowledge_points"][0]["name"] == "变量与表达式"
    assert client.get(f"/api/eval/evidence?user_id={user}&notebook_id={maths['id']}").json()["summary"]["rounds"] == 0


def test_changed_curriculum_rejects_stale_plan_and_quiz(learner):
    client, user = learner
    book, survey, course = prepare(client, user)
    old = finish(client, survey)
    rid = uuid.uuid4().hex
    with session() as db:
        db.add(Resource(id=rid, user_id=user, kind="quiz", title="之前课程的题", payload={
            "notebook_id": book["id"], "course_revision": course["revision"],
            "questions": [{"id": "old", "kp": "py_values", "type": "single", "stem": "1+1=?", "options": ["2", "3"], "answer": "A"}]}))
        db.commit()
    response = client.post(f"/api/notebooks/{book['id']}/learning/prepare", json={"title": "高等数学入门", "course_key": "calculus", "survey": survey})
    assert response.status_code == 200, response.text
    assert client.get(f"/api/assessment?notebook_id={book['id']}").json()["assessment"] is None
    stale = client.post(f"/api/assessment/{old['id']}/replan", json={"survey": survey})
    assert stale.status_code == 409
    stale_quiz = client.post("/api/eval/submit", json={"user_id": user, "quiz_resource_id": rid, "kp": "py_values", "answers": [{"question_id": "old", "answer": "A", "correct": True}]})
    assert stale_quiz.status_code == 409
    with session() as db:
        assert db.get(AssessmentSession, old["id"]).data["report"] == old["report"]


def test_confirmed_subset_controls_assessment_coverage(learner):
    client, user = learner
    book, survey, _ = prepare(client, user)
    survey["target_kps"] = ["py_functions"]
    result = finish(client, survey)
    assert result["answered"] == 3
    assert result["report"]["coverage"] == 1
    measured = [s for s in result["report"]["skills"] if s["attempts"]]
    assert [s["kp"] for s in measured] == ["py_functions"]

"""Course isolation, actual source binding, resume and prompt propagation."""
import asyncio
import copy
import json
import uuid

import pytest
from fastapi import HTTPException
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


def prepare_custom_assessment_fixture(client, user, key="python", title="Python 入门", goal="独立解题与纠错"):
    """Exercise the generic engine with explicit test content, never the default catalogue.

    The archived pack supplies deterministic questions for scoring/isolation tests.
    Mark it as a custom test curriculum; public built-in behavior is separately
    covered in test_notebook_study. This does not change production policy.
    """
    from app.data.course_packs import build_pack
    from app.models.entities import LearningSpace
    book, survey, public = prepare(client, user, key, title, goal)
    with session() as db:
        row = db.get(LearningSpace, book["id"])
        value = {**row.course, **build_pack(key), "kind": "generated", "title": title}
        row.course = value
        db.commit()
    return book, {**survey, "course_key": "custom"}, public


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
    py, py_survey, _ = prepare_custom_assessment_fixture(client, user)
    maths, math_survey, _ = prepare_custom_assessment_fixture(client, user, "calculus", "高等数学入门", "准备课程考试")
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
    book, survey, course = prepare_custom_assessment_fixture(client, user)
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
    body = "生产者通过光合作用将太阳能转化为化学能。消费者通过摄食获取能量。分解者把有机物分解为无机物。能量流动沿食物链逐级传递，并以热的形式散失。物质循环使元素在生物与非生物环境间循环。"
    upload = client.post("/api/knowledge/upload", data={"user_id": user, "notebook_id": book["id"], "title": "生态课资料"}, files={"file": ("ecology.txt", body.encode(), "text/plain")})
    assert upload.status_code == 200, upload.text
    source = upload.json()["source"]
    captured = []
    async def model(prompt, **kwargs):
        captured.append(prompt)
        assert body in prompt
        return json.dumps({"topics": [{"name": ["生产者与消费者", "能量流动", "物质循环"][i], "objective": "区分生态系统中的能量来源", "lesson": "先区分生产者和消费者，再举生活中的食物链例子。", "chunk_ids": ["s1c1"], "quote": "生产者通过光合作用将太阳能转化为化学能。", "questions": [
            {"stem": f"第{i}组情境{j}：判断生产者的能量来源与转化。", "type": "multiple" if j == 2 else "single", "options": ["光合作用", "太阳能转化为化学能", "吞食动物", "不需能量"], "answer": ["A", "B"] if j == 2 else "A", "explain": "资料说明生产者通过光合作用将太阳能转化为化学能。", "difficulty": 1} for j in range(3)]} for i in range(3)]}, ensure_ascii=False)
    monkeypatch.setattr(course_learning_service, "llm_complete", model)
    async def reviewed(*args): pass
    monkeypatch.setattr(course_learning_service, "review_course_questions", reviewed)
    survey = {"notebook_id": book["id"], "course_key": "custom", "course_title": "生态学笔记", "source_ids": [source["id"]], "goal": "看懂学习资料", "goals": ["看懂学习资料"], "daily_minutes": 15, "supports": ["steps"]}
    response = client.post(f"/api/notebooks/{book['id']}/learning/prepare", json={"title": "生态学笔记", "source_ids": [source["id"]], "survey": survey})
    assert response.status_code == 200, response.text
    course = response.json()
    assert captured and course["sources"][0]["title"] == "生态课资料"
    assert course["sources"][0]["sha256"] and course["sources"][0]["location_kind"] == "片段"
    survey["course_revision"] = course["revision"]
    result = finish(client, survey, False)
    assert all("生态课资料" in m["markdown"] and "生产者通过光合作用" in m["markdown"] for m in result["materials"])

    # Exercise the real upload -> retriever -> topic filter -> prompt chain.
    # Mock only model inference, so a source discarded after retrieval fails.
    from app.agents import doc_agent
    from app.services.knowledge_graph import resolve_conversation_topic, resolve_topic
    from app.services.topic_scope import focus_chunks_on_topic
    goal = "根据已选资料，分步骤讲解生态系统的能量流动与物质循环，并留下一个独立思考问题。"
    followup_prompts = []
    async def followup_model(prompt, **kwargs):
        followup_prompts.append(prompt)
        return "# 能量流动与物质循环\n\n" + body + "[^1]"
    async def grounding(*args, **kwargs):
        return {"grounded": True, "unsupported": [], "verdict": "ok"}
    monkeypatch.setattr(doc_agent, "llm_complete", followup_model)
    monkeypatch.setattr(doc_agent, "grounding_check", grounding)
    monkeypatch.setattr(doc_agent, "is_demo", lambda: False)
    with course_scope(user, book["id"]):
        kp, topic, custom = resolve_conversation_topic(goal, topic_label="生态学笔记")
        assert (kp, topic, custom) == ("custom_topic", "生态系统的能量流动与物质循环", True)
        assert resolve_topic([kp], goal, topic) == (kp, topic, custom)
        assert resolve_conversation_topic("请讲解物质循环") == ("topic_3", "物质循环", True)
        resource = asyncio.run(doc_agent._gen_one("doc", kp, {}, topic_name=topic,
            custom_topic=custom, source_ids=[source["id"]], goal=goal, prompt_template="complete_notes",
            user_id=user, trace_id="upload-followup", skip_multimodal=True))["resource"]
        assert focus_chunks_on_topic([{"text": body}], "topic_1", "食物链中的能量流动特点")
        assert not focus_chunks_on_topic([{"text": "生态系统中的种群数量。"}], "topic_1", "生态系统的能量流动特点")
    assert followup_prompts
    assert body in followup_prompts[0] and "看懂学习资料" in followup_prompts[0]
    assert "15" in followup_prompts[0] and "每次只推进一个推理步骤" in followup_prompts[0]
    assert "生态课资料" in resource["citations"][0]
    assert resource["payload"]["source_evidence"][0]["source_id"] == source["id"]
    assert resource["payload"]["source_evidence"][0]["preview"].rstrip("…") in body
    assert resource["payload"]["markdown"].startswith("# 能量流动与物质循环")
    assert "资料不足" not in resource["payload"]["markdown"]
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
    py, survey, _ = prepare_custom_assessment_fixture(client, user)
    result = finish(client, survey, False)
    maths, _, _ = prepare_custom_assessment_fixture(client, user, "calculus", "高等数学入门")
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
    book, survey, course = prepare_custom_assessment_fixture(client, user)
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
    book, survey, _ = prepare_custom_assessment_fixture(client, user)
    survey["target_kps"] = ["py_functions"]
    result = finish(client, survey)
    assert result["answered"] == 3
    assert result["report"]["coverage"] == 1
    measured = [s for s in result["report"]["skills"] if s["attempts"]]
    assert [s["kp"] for s in measured] == ["py_functions"]


def test_inflight_old_scope_cannot_write_changed_profile(learner):
    from app.models.entities import LearningSpace
    from app.services.learning_scope import profile_row
    client, user = learner
    book, _, _ = prepare(client, user)
    with course_scope(user, book["id"]):
        with session() as db:
            row = db.get(LearningSpace, book["id"])
            row.course = {**row.course, "revision": "changed-by-concurrent-request"}
            db.commit()
        with session() as db, pytest.raises(HTTPException) as caught:
            profile_row(db, user)
        assert caught.value.status_code == 409


def test_generated_draft_repairs_once_without_bypassing_validation(monkeypatch):
    from app.services import course_learning_service as service
    from types import SimpleNamespace
    good = {"topics": [{"name": f"知识点{i}", "objective": "理解概念与条件", "lesson": "先比较概念再完成新情境任务。", "questions": [
        {"stem": f"模块{i}题{j}：哪些条件成立？", "type": "multiple" if j == 2 else "single", "options": ["成立条件一", "成立条件二", "不成立的条件"],
         "answer": ["A", "B"] if j == 2 else "A", "explain": "依据给定条件，可推出相应的结论。"} for j in range(3)]} for i in range(3)]}
    bad = copy.deepcopy(good)
    bad["topics"][0]["questions"][2]["answer"] = ["A"]
    calls = []
    async def repair(prompt, **kwargs):
        calls.append(prompt)
        return json.dumps(bad if len(calls) == 1 else good, ensure_ascii=False)
    monkeypatch.setattr(service, "llm_complete", repair)
    async def reviewed(*args): pass
    monkeypatch.setattr(service, "review_course_questions", reviewed)
    prompt = SimpleNamespace(prompt="按照生态学原理出题", system="教学服务")
    result = asyncio.run(service.generate_valid_course(prompt, "生态学", []))
    assert len(calls) == 2 and len(result["bank"]) == 9
    assert "知识点 1 第 3 题" in calls[1]
    async def still_bad(prompt, **kwargs):
        calls.append(prompt)
        return json.dumps(bad)
    calls.clear()
    monkeypatch.setattr(service, "llm_complete", still_bad)
    result = asyncio.run(service.generate_valid_course(prompt, "生态学", []))
    assert len(calls) == 2 and len(result["bank"]) == 6
    assert [n["name"] for n in result["graph"]["nodes"]] == ["知识点1", "知识点2"]
    assert "另有 1 个未通过检查" in result["preparation_note"]
    for topic in bad["topics"]:
        topic["questions"][2]["answer"] = ["A"]
    calls.clear()
    with pytest.raises(ValueError):
        asyncio.run(service.generate_valid_course(prompt, "生态学", []))
    assert len(calls) == 2
    async def transport_failure(prompt, **kwargs):
        calls.append(prompt)
        raise RuntimeError("transport failed")
    calls.clear()
    monkeypatch.setattr(service, "llm_complete", transport_failure)
    with pytest.raises(RuntimeError):
        asyncio.run(service.generate_valid_course(prompt, "生态学", []))
    assert len(calls) == 1


def test_short_material_does_not_have_to_invent_three_topics(monkeypatch):
    from app.services.course_learning_service import validate_draft
    topic = {"name": "光合作用", "objective": "区分生产者和消费者", "lesson": "植物制造有机物。",
        "questions": [{"stem": f"问题{i}", "type": "multiple" if i == 2 else "single",
            "options": ["符合条件甲", "符合条件乙", "不符合条件"], "answer": ["A", "B"] if i == 2 else "A",
            "explain": "依据光合作用与摄食获得有机物的区别判断。"} for i in range(3)]}
    result = validate_draft({"topics": [topic]}, "短讲义", [])
    assert len(result["bank"]) == 3
    topic["questions"][2]["answer"] = ["A", "B", "C"]
    with pytest.raises(ValueError, match="错误选项"):
        validate_draft({"topics": [topic]}, "短讲义", [])


@pytest.mark.parametrize("exception,status,code,word", [
    (TimeoutError(), 503, "timeout", "超时"),
    (ValueError("private draft must not leak"), 422, "invalid_draft", "未通过检查"),
])
def test_course_failures_keep_sources_and_classify_safely(learner, monkeypatch, exception, status, code, word):
    from app.services import course_learning_service as service
    client, user = learner
    book = client.post("/api/notebooks", json={"user_id": user, "title": "资料课程"}).json()
    async def fail(*args, **kwargs):
        raise exception
    monkeypatch.setattr(service, "generate_valid_course", fail)
    result = client.post(f"/api/notebooks/{book['id']}/learning/prepare", json={"title": "资料课程", "course_key": "custom"})
    assert result.status_code == status
    assert result.headers["x-learning-failure"] == code
    assert word in result.json()["detail"] and "private draft" not in result.text
    assert client.get(f"/api/notebooks/{book['id']}/learning").json()["course"]["kind"] == "unconfigured"


def test_known_validation_issue_is_actionable_without_exposing_draft(learner, monkeypatch):
    from app.services import course_learning_service as service
    client, user = learner
    book = client.post("/api/notebooks", json={"user_id": user, "title": "资料课程"}).json()
    async def fail(*args, **kwargs):
        raise service.DraftValidationError("citation_mismatch", "资料引用未能与原文对应")
    monkeypatch.setattr(service, "generate_valid_course", fail)
    result = client.post(f"/api/notebooks/{book['id']}/learning/prepare", json={"title": "资料课程", "course_key": "custom"})
    assert result.status_code == 422
    assert result.headers["x-learning-validation"] == "citation_mismatch"
    assert "资料引用未能与原文对应" in result.json()["detail"]
    assert client.get(f"/api/notebooks/{book['id']}/learning").json()["course"]["kind"] == "unconfigured"


def test_source_text_is_bound_by_ids_not_model_recopied_quotes():
    from app.services import course_learning_service as service
    original = "真实讲义：植物通过光合作用制造有机物。"
    chunks = [{"evidence_id": "s1c1", "source": "原件", "source_id": "owned", "text": original}]
    topic = {"name": "光合作用", "objective": "识别植物获取有机物的方式", "lesson": "植物通过光合作用制造有机物。",
        "chunk_ids": ["s1c1"], "quote": "模型随意改写的文字，不能当成原文",
        "questions": [{"stem": f"问题{i}", "type": "multiple" if i == 2 else "single",
            "options": ["甲", "乙", "丙"], "answer": ["A", "B"] if i == 2 else "A",
            "explain": "根据光合作用的定义判断选项。"} for i in range(3)]}
    value = service.validate_draft({"topics": [topic]}, "讲义", chunks)
    assert value["evidence"]["topic_1"][0]["text"] == original
    assert "模型随意改写" not in json.dumps(value, ensure_ascii=False)
    assert all(q["evidence_ids"] == ["s1c1"] for q in value["bank"])
    topic["chunk_ids"] = ["invented"]
    with pytest.raises(service.DraftValidationError, match="片段编号"):
        service.validate_draft({"topics": [topic]}, "讲义", chunks)
    with pytest.raises(service.DraftValidationError, match="片段编号"):
        service.validate_draft({"topics": [topic]}, "无资料主题", [])


@pytest.mark.parametrize("bad_index", [0, 1])
@pytest.mark.parametrize("bad_stage", ["solver", "final"])
def test_last_attempt_keeps_reviewed_whole_topics_through_assessment(learner, monkeypatch, bad_index, bad_stage):
    from app.services import course_learning_service as service
    from app.models.entities import LearningSpace
    client, user = learner
    book, survey, old = prepare(client, user)
    body = "甲与乙符合本题条件，丙不符合本题条件。本练习要求先阅读完整题干，再区分单选与多选。每项判断需要说明所用条件，不能仅凭选项位置推测答案。"
    upload = client.post("/api/knowledge/upload", data={"user_id": user, "notebook_id": book["id"], "title": "条件练习"},
        files={"file": ("conditions.txt", body.encode(), "text/plain")})
    assert upload.status_code == 200, upload.text
    source_id = upload.json()["source"]["id"]
    draft = {"topics": [{"name": f"条件{i}", "objective": "区分给定条件", "lesson": f"讲义{i}：{body}", "chunk_ids": ["s1c1"],
        "questions": [{"stem": f"条件{i}问题{j}", "type": "multiple" if j == 2 else "single",
            "options": ["甲", "乙", "丙"], "answer": ["A", "B"] if j == 2 else "A",
            "explain": "根据题目条件分别判断每个选项。"} for j in range(3)]} for i in range(3)]}
    # Full independent response, with one explicit rejected question in a whole topic.
    rows = [{"id": f"topic_{i+1}-{j+1}", "conditions_sufficient": True, "supported": bad_stage != "solver" or i != bad_index or j != 0,
        "scope_preserved": True, "unstated_assumptions": [], "redundancy": [], "evidence": ["s1c1:1"],
        "options": [{"label": label, "correct": label in (["A", "B"] if j == 2 else ["A"]),
            "reason": f"根据条件{i}判断{label}"} for label in "ABC"]} for i in range(3) for j in range(3)]
    calls = []
    async def model(prompt, **kwargs):
        calls.append(prompt)
        if "最终题目与逐项理由：" in prompt:
            finals = json.JSONDecoder().raw_decode(prompt.split("最终题目与逐项理由：", 1)[1].lstrip())[0]
            return json.dumps({"questions": [{"id": q["id"],
                "issues": ["新增资料未给的排他性限定"] if bad_stage == "final" and q["id"] == f"topic_{bad_index+1}-1" else [],
                "options": [{"label": label, "accepted": True, "issues": []} for label in "ABC"]} for q in finals]})
        if "待核对题目：" not in prompt:
            return json.dumps(draft, ensure_ascii=False)
        presented = json.JSONDecoder().raw_decode(prompt.split("待核对题目：", 1)[1].lstrip())[0]
        for row, q in zip(rows, presented):
            row["options"] = [{"label": label, "correct": option in (["甲", "乙"] if q["type"] == "multiple" else ["甲"]),
                "reason": f"根据条件判断{option}"} for label, option in zip("ABC", q["options"])]
        return json.dumps({"questions": rows}, ensure_ascii=False)
    monkeypatch.setattr(service, "llm_complete", model)
    response = client.post(f"/api/notebooks/{book['id']}/learning/prepare", json={
        "title": "条件练习", "course_key": "custom", "source_ids": [source_id], "survey": survey})
    assert response.status_code == 200, response.text
    public = response.json()
    keep = {f"topic_{i+1}" for i in range(3) if i != bad_index}
    assert len(calls) == (5 if bad_stage == "solver" else 6)
    assert {n["id"] for n in public["outline"]} == keep
    assert public["question_count"] == public["quality_review"]["reviewed_questions"] == 6
    assert "未覆盖全文" in public["coverage_note"] and "另有 1 个未通过检查" in public["coverage_note"]
    survey.update(course_revision=public["revision"], target_kps=sorted(keep), course_key="custom", source_ids=[source_id])
    finished = finish(client, survey, False)
    assert finished["answered"] == 6
    with session() as db:
        saved = db.get(LearningSpace, book["id"]).course
        snapshot = db.get(AssessmentSession, finished["id"]).data["course_snapshot"]
        for value in (saved, snapshot):
            assert {q["kp"] for q in value["bank"]} == keep
            assert set(value["lessons"]) == set(value["evidence"]) == keep
            assert {n["id"] for n in value["graph"]["nodes"]} == keep
            assert all("根据条件" in q["explain"] for q in value["bank"])
    # A subsequent complete semantic failure must leave the accepted course intact.
    for row in rows:
        row["supported"] = False
    calls.clear()
    failed = client.post(f"/api/notebooks/{book['id']}/learning/prepare", json={
        "title": "另一范围", "course_key": "custom", "source_ids": [source_id], "survey": survey})
    assert failed.status_code == 422, failed.text
    assert client.get(f"/api/notebooks/{book['id']}/learning").json()["course"]["revision"] == public["revision"]

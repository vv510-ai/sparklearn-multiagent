"""Real imported textbook, executable answer oracles and learner-state contracts."""
import copy
import asyncio
import datetime as dt
import hashlib
import subprocess
import sys
import uuid

from app.models.db import session
from app.models.entities import EventLog, LearningSpace
from app.services.learning_scope import course_scope
from app.services.textbook_service import python_book, python_chunks, course_textbook_chunks
from app.data.python_practice import EXERCISES, practice_bank
from tests.test_learning_spaces import learner, prepare, finish, prepare_custom_assessment_fixture  # noqa: F401


def test_imported_sections_are_complete_and_chunks_point_to_exact_text():
    book = python_book()
    assert len(book["sections"]) == 10
    sections = {s["id"]: s for s in book["sections"]}
    for section in sections.values():
        assert hashlib.sha256(section["text"].encode()).hexdigest() == section["sha256"]
        assert section["url"].endswith("#" + section["id"])
    for chunk in python_chunks():
        section = sections[chunk["section_id"]]
        assert chunk["text"] == section["text"][chunk["start_char"]:chunk["end_char"]]
        assert chunk["text"].count("```") % 2 == 0
    # Every non-whitespace character is present, not merely six sampled chunks.
    for section in sections.values():
        covered = "".join(c["text"] for c in python_chunks() if c["section_id"] == section["id"])
        assert "".join(covered.split()) == "".join(section["text"].split())


def test_all_new_question_answers_match_python_execution():
    bank = practice_bank()
    for kp, questions in EXERCISES.items():
        for i, (_, code, expected, _, _) in enumerate(questions):
            process = subprocess.run([sys.executable, "-I", "-X", "utf8", "-c", code], capture_output=True, text=True, encoding="utf-8", timeout=5)
            assert process.returncode == 0, process.stderr
            assert process.stdout.strip() == expected
            question = next(q for q in bank if q["id"] == f"{kp}-fresh-{i+1}")
            assert question["options"][ord(question["answer"]) - 65] == expected
            assert len(set(question["options"])) == 4


def test_textbook_retrieval_is_scoped_and_keeps_original_locator(learner):
    from app.rag.retriever import retrieve
    client, user = learner
    book, _, course = prepare(client, user)
    assert course["textbook"]["title"] == "Python 官方教程"
    assert "practice_bank" not in course
    with course_scope(user, book["id"]):
        for kp, query in [("py_functions", "函数 return 没有返回值 None"), ("py_loops", "range 停止值不包含")]:
            chunks = retrieve(query, user_id=user, kp=kp)
            assert chunks and all(c["source_type"] == "textbook" and c["url"].startswith("https://docs.python.org/") for c in chunks)
            assert all(kp in c["kp"] for c in chunks)
        assert retrieve("return None", user_id=user, source_ids=["missing-source"], kp="py_functions") == []
    maths, _, _ = prepare(client, user, "calculus", "高数入门")
    with course_scope(user, maths["id"]):
        assert retrieve("return None", user_id=user) == []


def test_existing_course_uses_pinned_text_when_platform_book_changes(monkeypatch):
    from app.data.course_packs import build_pack
    from app.services import textbook_service
    course = build_pack("python")
    original = course_textbook_chunks(course)
    changed = copy.deepcopy(python_book())
    changed["sections"][0]["text"] = "Later platform edition"
    monkeypatch.setattr(textbook_service, "python_book", lambda: changed)
    assert course_textbook_chunks(course) == original


def test_named_course_generation_retrieves_textbook_without_uploaded_files(learner, monkeypatch):
    from app.agents import doc_agent
    from app.services.knowledge_graph import resolve_conversation_topic
    from app.services.learning_scope import selected_sources
    from app.services.source_service import selected_source_summaries
    client, user = learner
    book, survey, _ = prepare(client, user)
    prompts = []
    async def model(prompt, **kwargs):
        prompts.append(prompt)
        return "# 函数与返回值\n\n没有 return 的函数返回 None；print 负责显示内容，return 把值返回给调用者。[^1]\n\n```\nNone\n```"
    async def grounding(*args, **kwargs):
        return {"grounded": True, "unsupported": [], "verdict": "test"}
    monkeypatch.setattr(doc_agent, "llm_complete", model)
    monkeypatch.setattr(doc_agent, "grounding_check", grounding)
    monkeypatch.setattr(doc_agent, "is_demo", lambda: False)
    goal = "根据 Python 官方教程，分步骤解释函数没有 return 时返回什么，并区分 print 和 return。"
    with course_scope(user, book["id"]):
        selected = selected_sources([])
        assert selected == ["__course__"]
        assert selected_sources(["uploaded-file", "__course__"]) == ["uploaded-file"]
        assert selected_source_summaries(user, selected)[0]["title"] == "Python 官方教程"
        kp, topic, custom = resolve_conversation_topic(goal, knowledge_points=["py_functions"], topic_label="函数与返回值")
        resource = asyncio.run(doc_agent._gen_one("doc", kp, {}, topic_name=topic,
            custom_topic=custom, source_ids=selected, goal=goal, prompt_template="complete_notes",
            user_id=user, trace_id="textbook-followup", skip_multimodal=True))["resource"]
    assert prompts and "None" in prompts[0] and "20" in prompts[0]
    assert resource["payload"]["generation_mode"] == "model"
    assert resource["citations"] and all("docs.python.org" in c for c in resource["citations"])
    assert resource["payload"]["source_evidence"]


def _answer_new(client, state, kp, *, correct=True, assisted=False):
    start = client.post(f"/api/assessment/{state['id']}/practice", json={"kp": kp})
    assert start.status_code == 200, start.text
    result = start.json()
    assert result["status"] == "active", result
    question = result["question"]
    assert "answer" not in question and "explain" not in question
    q = next(q for q in practice_bank() if q["id"] == question["id"])
    payload = {"question_id": q["id"], "choice": q["answer"] if correct else None, "assisted": assisted}
    response = client.post(f"/api/assessment/{state['id']}/practice/answers", json=payload)
    assert response.status_code == 200, response.text
    return response.json(), payload


def test_weak_and_strong_learners_get_different_plans_and_new_evidence_updates(learner, monkeypatch):
    from app.services import assessment_practice
    client, user = learner
    book, survey, _ = prepare_custom_assessment_fixture(client, user)
    weak = finish(client, survey, False)
    assert any(t["kind"] == "study" for d in weak["plan"]["days"] for t in d["tasks"])
    task = next(t for d in weak["plan"]["days"] for t in d["tasks"] if t["kp"] == "py_values")
    assert task["readings"] and "introduction.html#numbers" in task["readings"][0]["url"]
    original = copy.deepcopy(weak["report"])
    first, payload = _answer_new(client, weak, "py_values")
    repeated = client.post(f"/api/assessment/{weak['id']}/practice/answers", json=payload)
    assert repeated.status_code == 200
    assert repeated.json()["assessment"]["learning_progress"]["py_values"]["answered"] == 1
    for _ in range(2):
        first, _ = _answer_new(client, weak, "py_values")
    updated = first["assessment"]
    assert updated["report"] == original
    assert updated["plan"]["practice_update"]
    assert any(t["kp"] == "py_values" and t["kind"] == "transfer" for d in updated["plan"]["days"] for t in d["tasks"])
    waiting = client.post(f"/api/assessment/{weak['id']}/practice", json={"kp": "py_values"}).json()
    assert waiting["status"] == "scheduled" and waiting["question"] is None
    due = dt.datetime.fromisoformat(waiting["progress"]["next_due_at"])
    monkeypatch.setattr(assessment_practice, "now", lambda: due + dt.timedelta(seconds=1))
    later, _ = _answer_new(client, updated, "py_values")
    assert later["result"]["question_id"].endswith("fresh-4")
    strong_book, strong_survey, _ = prepare_custom_assessment_fixture(client, user)
    strong = finish(client, strong_survey)
    assert all(t["kind"] in ("transfer", "review") for d in strong["plan"]["days"] for t in d["tasks"])
    assert "Python 官方教程" in strong["materials"][0]["markdown"]


def test_assistance_resume_restart_ownership_and_stale_scope(learner):
    client, user = learner
    book, survey, _ = prepare_custom_assessment_fixture(client, user)
    state = finish(client, survey, False)
    before = client.get(f"/api/profile/{user}?notebook_id={book['id']}").json()["knowledge_mastery"]
    first = client.post(f"/api/assessment/{state['id']}/practice", json={"kp": "py_values"}).json()
    again = client.post(f"/api/assessment/{state['id']}/practice", json={"kp": "py_values"}).json()
    assert first["question"] == again["question"]
    result, payload = _answer_new(client, state, "py_values", assisted=True)
    assert not result["result"]["independent"]
    assert result["assessment"]["learning_progress"]["py_values"]["independent"] == 0
    assert client.get(f"/api/profile/{user}?notebook_id={book['id']}").json()["knowledge_mastery"] == before
    assert client.post(f"/api/assessment/{state['id']}/practice/answers", json={**payload, "assisted": False}).status_code == 409
    restarted = finish(client, survey, False)
    next_question = client.post(f"/api/assessment/{restarted['id']}/practice", json={"kp": "py_values"}).json()["question"]
    assert next_question["id"] != first["question"]["id"]
    # Two assessment windows can hold the same pending question. Once one has
    # submitted, the other must advance instead of getting stuck on a 409 loop.
    old_pending = client.post(f"/api/assessment/{state['id']}/practice", json={"kp": "py_values"}).json()["question"]
    assert old_pending == next_question
    _answer_new(client, restarted, "py_values")
    resumed = client.post(f"/api/assessment/{state['id']}/practice", json={"kp": "py_values"}).json()["question"]
    assert resumed["id"] != old_pending["id"]
    owner_header = client.headers["Authorization"]
    outsider = client.post("/api/auth/register", json={"email": f"practice-{uuid.uuid4().hex}@example.test",
        "password": "Practice-Test-Password!", "name": "其他学习者"}).json()
    client.headers["Authorization"] = f"Bearer {outsider['access_token']}"
    assert client.post(f"/api/assessment/{state['id']}/practice", json={"kp": "py_values"}).status_code == 404
    assert client.post(f"/api/assessment/{state['id']}/practice/answers", json=payload).status_code == 404
    client.headers["Authorization"] = owner_header
    with session() as db:
        row = db.get(LearningSpace, book["id"])
        row.course = {**row.course, "revision": "replaced"}
        db.commit()
    assert client.post(f"/api/assessment/{state['id']}/practice", json={"kp": "py_values"}).status_code == 409


def test_delayed_rounds_use_nine_distinct_questions_then_stop(learner, monkeypatch):
    from app.services import assessment_practice
    client, user = learner
    book, survey, _ = prepare_custom_assessment_fixture(client, user)
    state = finish(client, survey, False)
    clock = dt.datetime(2030, 1, 1, tzinfo=dt.timezone.utc)
    monkeypatch.setattr(assessment_practice, "now", lambda: clock)
    seen = set()
    for count in range(1, 10):
        result, _ = _answer_new(client, state, "py_values")
        qid = result["result"]["question_id"]
        assert qid not in seen
        seen.add(qid)
        if count in (3, 6):
            waiting = client.post(f"/api/assessment/{state['id']}/practice", json={"kp": "py_values"}).json()
            assert waiting["status"] == "scheduled"
            due = dt.datetime.fromisoformat(waiting["progress"]["next_due_at"])
            assert due - clock == dt.timedelta(days=1 if count == 3 else 3)
            clock = due + dt.timedelta(seconds=1)
    last = client.post(f"/api/assessment/{state['id']}/practice", json={"kp": "py_values"}).json()
    assert last["status"] == "exhausted" and last["question"] is None
    assert last["progress"]["answered"] == last["progress"]["independent"] == last["progress"]["correct"] == 9
    assert last["progress"]["next_due_at"] is None

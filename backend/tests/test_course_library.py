"""Course publishing, actual content, ownership, retry and withdrawal contracts."""
import asyncio
import copy
import json
from pathlib import Path
import subprocess
import sys
import uuid
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.services import course_library as library
from app.models.db import session
from app.models.entities import CoursePublication, CourseRelease, CourseStudy, Resource
from app.services.learning_scope import course_scope
from tests.test_learning_spaces import learner  # noqa: F401


def bundle():
    value = json.loads(library.BUNDLE_PATH.read_text(encoding="utf-8"))
    value["release_id"] = "test-release-" + uuid.uuid4().hex
    value["course_id"] = "test-course-" + uuid.uuid4().hex
    return value


def enrolled(client):
    listing = client.get("/api/library")
    assert listing.status_code == 200, listing.text
    course = next(x for x in listing.json()["items"] if x["course_id"] == "python_foundations")
    response = client.post("/api/library/enroll", json={"release_id": course["release_id"]})
    assert response.status_code == 200, response.text
    return response.json()


def test_all_ten_objectives_have_real_sources_and_executable_examples(tmp_path):
    b = json.loads(library.BUNDLE_PATH.read_text(encoding="utf-8"))
    library.validate_bundle(b)
    assert len(b["lessons"]) == 10
    assert len(b["textbook"]["sections"]) == 18
    assert b["review"]["human_review"] is False
    for lesson in b["lessons"]:
        fixtures = [(lesson["example"]["code"], lesson["example"]["output"])]
        fixtures.extend((q["code"], q["expected"]) for q in lesson["questions"])
        for code, expected in fixtures:
            result = subprocess.run([sys.executable, "-I", "-X", "utf8", "-c", code], cwd=tmp_path,
                                    capture_output=True, text=True, encoding="utf-8", timeout=5)
            assert result.returncode == 0, (lesson["id"], result.stderr)
            assert result.stdout.strip() == expected, (lesson["id"], code, result.stdout)
    broken = copy.deepcopy(b)
    broken["lessons"][0]["criteria"] = []
    with pytest.raises(ValueError, match="Incomplete"):
        library.validate_bundle(broken)


def test_no_upload_no_assessment_start_read_practice_resume_and_owned_state(learner):
    client, user = learner
    current = enrolled(client)
    assert client.post("/api/library/enroll", json={"release_id": current["release_id"]}).json()["id"] == current["id"]
    assert client.get("/api/onboarding").json()["required"] is False
    url = f"/api/library/studies/{current['id']}/lessons/start"
    lesson = client.get(url).json()
    assert "answer" not in lesson["question"] and "expected" not in lesson["question"]
    q = json.loads(library.BUNDLE_PATH.read_text(encoding="utf-8"))["lessons"][0]["questions"][0]
    answer = {"action": "answer", "revision": lesson["revision"], "question_id": q["id"], "choice": q["answer"], "assisted": False}
    response = client.post(url, json=answer)
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["progress"]["lessons"]["start"]["attempts"][0]["correct"]
    assert client.post(url, json=answer).json() == saved  # idempotent retry
    stale = client.post(url, json={"action": "read", "revision": 0})
    assert stale.status_code == 409
    next_question = client.get(url).json()
    assert next_question["question"] is None and next_question["practice_status"] == "scheduled"
    work = client.post(url, json={"action": "work", "revision": saved["revision"], "work": "print('my work')", "self_checked": [0]})
    assert work.status_code == 200
    assert work.json()["progress"]["lessons"]["start"]["work"]["status"] == "self_reported"
    token = client.headers["Authorization"]
    other = client.post("/api/auth/register", json={"email": f"other-{uuid.uuid4().hex}@example.test", "password": "Course-Test-Password!", "name": "另一账号"}).json()
    client.headers["Authorization"] = "Bearer " + other["access_token"]
    assert client.get(url).status_code == 404
    assert client.post(url, json=answer).status_code == 404
    client.headers["Authorization"] = token
    assert client.get(url).json()["progress"]["work"]["text"] == "print('my work')"


def test_publish_failure_keeps_old_pointer_and_old_learning_version(learner, monkeypatch):
    client, user = learner
    v1 = bundle()
    library.publish(v1)
    study = library.enroll(user, v1["release_id"])
    v2 = copy.deepcopy(v1)
    v2["release_id"] += "-v2"
    v2["lessons"][0]["markdown"] += "\n新版本的附加解释。"
    from app.rag import library_index
    original = library_index.build_index
    def failing(_):
        raise RuntimeError("injected build failure")
    monkeypatch.setattr(library_index, "build_index", failing)
    with pytest.raises(RuntimeError, match="injected"):
        library.publish(v2)
    with session() as db:
        assert db.get(CoursePublication, v1["course_id"]).release_id == v1["release_id"]
        assert db.get(CourseRelease, v2["release_id"]) is None
    monkeypatch.setattr(library_index, "build_index", original)
    library.publish(v2)
    assert library.state(user, study["id"])["release_id"] == v1["release_id"]
    assert "附加解释" not in library.lesson(user, study["id"], "start")["markdown"]
    changed = copy.deepcopy(v1)
    changed["title"] = "Illegal in-place change"
    with pytest.raises(ValueError, match="immutable"):
        library.publish(changed)


def test_source_withdrawal_blocks_old_lessons_chat_resources_retrieval_and_republication(learner):
    client, user = learner
    b = bundle()
    # Use a unique source marker to avoid withdrawing the real pilot in other tests.
    source = b["textbook"]["sections"][0]
    source["text"] += "\nWithdrawal fixture"
    import hashlib
    source["sha256"] = hashlib.sha256(source["text"].encode()).hexdigest()
    library.publish(b)
    study = library.enroll(user, b["release_id"])
    from app.services.conversation_service import append_message, get_session_messages
    from app.models.entities import Notebook
    with session() as db:
        nb = db.get(Notebook, study["notebook_id"])
        session_id = nb.session_id
    with course_scope(user, study["notebook_id"]):
        append_message(user, session_id, "assistant", "Protected derived text", source_evidence=[{"index": 3, "excerpt": source["text"]}])
    rid = uuid.uuid4().hex
    with session() as db:
        db.add(Resource(id=rid, user_id=user, kind="doc", title="Derived note",
                        payload={"markdown": "Protected derived text", "learning_context": {"course_release_id": b["release_id"]}},
                        citations=["original"]))
        db.commit()
    affected = library.withdraw_source(source["sha256"], "fixture withdrawal")
    assert b["release_id"] in affected
    state = library.state(user, study["id"])
    assert state["withdrawn"]
    assert client.get(f"/api/library/studies/{study['id']}/lessons/start").status_code == 410
    messages = get_session_messages(user, session_id)
    assert messages[0]["content"] == library.WITHDRAWN
    assert messages[0]["source_evidence"][0]["index"] == 3
    raw = client.get(f"/api/resources/{rid}").json()
    assert raw["payload"]["withdrawn"] and "Protected" not in json.dumps(raw)
    with pytest.raises(HTTPException) as exc:
        with course_scope(user, study["notebook_id"]):
            pass
    assert exc.value.status_code == 410
    with pytest.raises(ValueError, match="Withdrawn"):
        library.publish(b)
    repackaged = copy.deepcopy(b)
    repackaged["release_id"] += "-new-id"
    with pytest.raises(ValueError, match="Withdrawn source"):
        library.publish(repackaged)


def test_public_queries_embed_only_the_question_and_reject_incompatible_identity(learner, monkeypatch):
    client, user = learner
    study = enrolled(client)
    from app.rag import library_index, retriever, reranker
    actual = library_index.embed_texts
    calls = []
    def record(texts, *, domain="para"):
        calls.append((domain, len(texts)))
        return actual(texts, domain=domain)
    monkeypatch.setattr(library_index, "embed_texts", record)
    with course_scope(user, study["notebook_id"]):
        first = retriever.retrieve("return 没有返回值 None", user_id=user, kp="foundation_functions")
        second = retriever.retrieve("return 没有返回值 None", user_id=user, kp="foundation_functions")
    assert first and second
    assert calls == [("query", 1), ("query", 1)]
    assert all(c["course_release_id"] == study["release_id"] for c in first)
    assert all("foundation_functions" in c["kp"] for c in first)
    with course_scope(user, study["notebook_id"]):
        assert retriever.retrieve("return", user_id=user, source_ids=["missing-private"]) == []
    identity = library_index.index_identity()
    monkeypatch.setattr(library_index, "index_identity", lambda: {**identity, "name": "another-same-dimension-model"})
    with pytest.raises(HTTPException) as exc:
        library_index.retrieve_release(study["release_id"], "return")
    assert exc.value.status_code == 503


def test_sse_checks_withdrawal_before_next_output(learner):
    client, user = learner
    b = bundle()
    library.publish(b)
    from app.api.sse import _wrap
    async def scenario():
        async def events():
            yield {"type": "delta", "text": "first"}
            library.withdraw(b["release_id"], "stream fixture")
            yield {"type": "delta", "text": "MUST NOT LEAK"}
        return [x async for x in _wrap(events(), b["release_id"])]
    output = "".join(asyncio.run(scenario()))
    assert "first" in output and "MUST NOT LEAK" not in output and "停止提供" in output


def test_streamed_chat_without_citation_retains_release_after_scope_exit(learner, monkeypatch):
    client, user = learner
    b = bundle()
    library.publish(b)
    study = library.enroll(user, b["release_id"])
    from app.api import chat
    from app.models.entities import Notebook
    from app.services.conversation_service import get_session_messages
    async def fake_events(_):
        yield {"type": "token", "delta": "Derived uncited answer"}
        yield {"type": "done"}
    monkeypatch.setattr(chat, "run_with_events", fake_events)
    response = client.post("/api/chat", json={"user_id": user, "message": "Explain return", "notebook_id": study["notebook_id"]})
    assert response.status_code == 200 and "Derived uncited answer" in response.text
    with session() as db:
        sid = db.get(Notebook, study["notebook_id"]).session_id
    assert get_session_messages(user, sid)[-1]["content"] == "Derived uncited answer"
    library.withdraw(b["release_id"], "stream persistence regression")
    assert get_session_messages(user, sid)[-1]["content"] == library.WITHDRAWN


def test_withdrawn_resource_interaction_and_provider_poll_are_blocked(learner, monkeypatch):
    client, user = learner
    b = bundle()
    library.publish(b)
    study = library.enroll(user, b["release_id"])
    rid, task_id = uuid.uuid4().hex, uuid.uuid4().hex
    payload = {"notebook_id": study["notebook_id"], "template": "interactive_audio", "markdown": "Protected", "video": {"task_id": task_id},
               "learning_context": {"course_release_id": b["release_id"]}}
    with session() as db:
        db.add(Resource(id=rid, user_id=user, kind="doc", title="Fixture", payload=payload))
        db.commit()
    from app.services.ownership_service import sync_resource_ownership, task_belongs_to_user
    sync_resource_ownership(user, rid, payload)
    assert task_belongs_to_user(user, task_id)
    from app.api.chat import _interaction_resource
    assert _interaction_resource(user, rid, study["notebook_id"])["markdown"] == "Protected"
    missing_scope = client.post("/api/chat", json={"user_id": user, "message": "再举例", "interaction_action": "example", "resource_id": rid})
    assert missing_scope.status_code == 404
    library.withdraw(b["release_id"], "resource bypass regression")
    from app.api.chat import _interaction_resource
    with pytest.raises(HTTPException) as exc:
        _interaction_resource(user, rid, "")
    assert exc.value.status_code == 410
    assert not task_belongs_to_user(user, task_id)
    assert client.get(f"/api/resources/video/task/{task_id}").status_code == 404
    assert client.get(f"/api/resources/ppt/task/{task_id}").status_code == 404


def test_note_reuse_preserves_origins_and_stays_in_its_release(learner):
    client, user = learner
    b = bundle()
    library.publish(b)
    study = library.enroll(user, b["release_id"])
    with session() as db:
        db.add(Resource(id=uuid.uuid4().hex, user_id=user, kind="doc", kp="foundation_functions", title="函数返回值",
            payload={"reusable_note": True, "markdown": "return 返回函数计算结果", "learning_context": {"course_release_id": b["release_id"]}}))
        db.commit()
    from app.services.note_service import recent_note_chunks
    from app.rag.citation import build_context
    with course_scope(user, study["notebook_id"]):
        chunks = recent_note_chunks(user, "函数返回值", knowledge_point="foundation_functions")
        assert chunks and chunks[0]["provenance"] == [{"course_release_id": b["release_id"]}]
    assert not recent_note_chunks(user, "函数返回值", knowledge_point="foundation_functions")
    _, citations = build_context(chunks)
    library.withdraw(b["release_id"], "reuse regression")
    assert library.blocked_payload({"source_evidence": citations})

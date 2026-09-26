"""English scene failures must not discard usable learning content."""
from __future__ import annotations

import asyncio
import copy
import json

import pytest

from app.api import learning
from app.llm.failures import ModelFailure
from app.services import english_learning as english


SCENE = {
    "title": "周末计划", "provenance": "模型提供的标签不能作为来源证明",
    "lines": [{"speaker": "A", "text": "Let's figure out our weekend plans.", "translation": "我们来想想周末怎么安排。"}],
    "vocabulary": [{"word": "figure out", "meaning": "想出、弄明白", "usage": "figure out a plan"}],
    "notes": "## 用法\nfigure out 表示通过思考找到办法。",
    "question": {"stem": "figure out 在这里表示什么？", "options": ["想出办法", "跑步", "争吵", "迟到"], "answer": "A", "explanation": "这里指商量并想出安排。"},
}


@pytest.fixture
def endpoint(monkeypatch):
    saved = []
    monkeypatch.setattr(learning, "_scope", lambda _: "english-test-user")
    monkeypatch.setattr(learning, "is_demo", lambda: False)
    monkeypatch.setattr(learning, "_persist", lambda *args: saved.append(args[-1]) or "r_english_test")
    return saved


def test_invalid_question_keeps_scene_and_archive(endpoint, monkeypatch):
    data = copy.deepcopy(SCENE)
    data["question"]["options"] = ["想出办法", "跑步", "争吵"]
    async def complete(*args, **kwargs):
        return json.dumps(data, ensure_ascii=False)
    monkeypatch.setattr(english, "llm_complete", complete)
    result = asyncio.run(learning.english_scene.__wrapped__(learning.SceneRequest(words="figure out")))
    assert result["lines"] == endpoint[0]["english_scene"]["lines"]
    assert result["question"] is None
    assert result["generation"]["status"] == "partial"
    assert result["resource_id"] == "r_english_test"


def test_temporary_provider_failure_retries_once(endpoint, monkeypatch):
    calls = []
    async def complete(*args, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise ModelFailure("rate_limit")
        return json.dumps(SCENE, ensure_ascii=False)
    monkeypatch.setattr(english, "llm_complete", complete)
    result = asyncio.run(learning.english_scene.__wrapped__(learning.SceneRequest(words="figure out")))
    assert result["question"]["answer"] == "A"
    assert len(calls) == 2
    assert all(call["reasoning_mode"] == "disabled" for call in calls)


@pytest.mark.parametrize("code", ["authentication", "quota", "content_filter", "timeout"])
def test_nonrecoverable_errors_do_not_retry_or_leak_payload(endpoint, monkeypatch, caplog, code):
    calls = []
    async def complete(*args, **kwargs):
        calls.append(1)
        raise ModelFailure(code)
    monkeypatch.setattr(english, "llm_complete", complete)
    with pytest.raises(learning.HTTPException) as caught:
        asyncio.run(learning.english_scene.__wrapped__(learning.SceneRequest(words="private-vocabulary")))
    assert len(calls) == 1
    assert caught.value.headers["X-English-Error"] == code
    assert "private-vocabulary" not in caplog.text
    assert endpoint == []


def test_invalid_json_is_repaired_once_without_echoing_model_output(endpoint, monkeypatch):
    calls = []
    async def complete(prompt, **kwargs):
        calls.append(prompt)
        return "PRIVATE BROKEN JSON" if len(calls) == 1 else json.dumps(SCENE)
    monkeypatch.setattr(english, "llm_complete", complete)
    result = asyncio.run(learning.english_scene.__wrapped__(learning.SceneRequest(words="figure out")))
    assert result["generation"]["status"] == "completed"
    assert len(calls) == 2
    assert "PRIVATE BROKEN JSON" not in calls[1]


def test_repeated_invalid_core_never_saved(endpoint, monkeypatch):
    calls = []
    async def complete(*args, **kwargs):
        calls.append(1)
        return json.dumps({**SCENE, "lines": []})
    monkeypatch.setattr(english, "llm_complete", complete)
    with pytest.raises(learning.HTTPException) as caught:
        asyncio.run(learning.english_scene.__wrapped__(learning.SceneRequest(words="figure out")))
    assert caught.value.headers["X-English-Error"] == "invalid_structure"
    assert len(calls) == 2 and endpoint == []


def test_source_mismatch_never_saved_and_original_timestamp_is_derived(endpoint, monkeypatch):
    calls = []
    async def complete(*args, **kwargs):
        calls.append(1)
        return json.dumps(SCENE)
    monkeypatch.setattr(english, "llm_complete", complete)
    with pytest.raises(learning.HTTPException) as caught:
        asyncio.run(learning.english_scene.__wrapped__(learning.SceneRequest(words="figure out", subtitles="Unrelated original line.")))
    assert caught.value.headers["X-English-Error"] == "source_mismatch"
    assert len(calls) == 2 and endpoint == []
    result = asyncio.run(learning.english_scene.__wrapped__(learning.SceneRequest(
        words="figure out", subtitles="1\n00:00:02,000 --> 00:00:05,000\nLet's figure out our weekend plans.")))
    assert result["lines"][0]["timestamp"] == "00:00:02,000"
    assert result["provenance"].startswith("用户字幕整理")


def test_request_deadline_does_not_start_overlapping_retry(endpoint, monkeypatch):
    calls = []
    async def complete(*args, **kwargs):
        calls.append(1)
        await asyncio.sleep(10)
    monkeypatch.setattr(english, "llm_complete", complete)
    monkeypatch.setattr(english, "GENERATION_TIMEOUT", .01)
    with pytest.raises(learning.HTTPException) as caught:
        asyncio.run(learning.english_scene.__wrapped__(learning.SceneRequest(words="figure out")))
    assert caught.value.status_code == 504 and len(calls) == 1


@pytest.mark.parametrize("question", [None, {}, {**SCENE["question"], "options": ["a", "a", "b", "c"]},
    {**SCENE["question"], "answer": "AB"}, {**SCENE["question"], "explanation": ""}])
def test_broken_optional_question_does_not_erase_valid_core(endpoint, monkeypatch, question):
    async def complete(*args, **kwargs):
        return json.dumps({**SCENE, "question": question})
    monkeypatch.setattr(english, "llm_complete", complete)
    result = asyncio.run(learning.english_scene.__wrapped__(learning.SceneRequest(words="figure out")))
    assert result["question"] is None and len(endpoint) == 1


def test_program_sets_provenance_and_clears_invented_timestamps(endpoint, monkeypatch):
    data = copy.deepcopy(SCENE)
    data.pop("provenance")
    data["lines"][0]["timestamp"] = "00:10:00"
    data["question"]["answer"] = " a "
    async def complete(*args, **kwargs):
        return json.dumps(data)
    monkeypatch.setattr(english, "llm_complete", complete)
    result = asyncio.run(learning.english_scene.__wrapped__(learning.SceneRequest(words="figure out")))
    assert result["provenance"] == "原创教学场景，非真实影视台词"
    assert result["lines"][0]["timestamp"] == ""
    assert result["question"]["answer"] == "A"


# Exercise the actual HTTP authentication, notebook scopes and database, not just helpers.
from tests.test_learning_spaces import learner  # noqa: E402,F401


def test_saved_scene_question_retry_is_owner_scoped_and_durable(learner, monkeypatch):
    import uuid
    from app.models.db import session
    from app.models.entities import Resource
    client, user = learner
    notebook = client.post("/api/notebooks", json={"user_id": user, "title": "英语自定义场景"}).json()["id"]
    second = client.post("/api/notebooks", json={"user_id": user, "title": "另一门英语课程"}).json()["id"]
    monkeypatch.setattr(learning, "_english_available", lambda: None)
    calls = []
    async def complete(prompt, **kwargs):
        calls.append(prompt)
        if "CAPABILITY=english.question" in prompt:
            return json.dumps(SCENE["question"])
        return json.dumps({**SCENE, "question": None})
    monkeypatch.setattr(english, "llm_complete", complete)
    response = client.post("/api/learning/english/scene", json={"words": "figure out", "notebook_id": notebook})
    assert response.status_code == 200, response.text
    initial = response.json()
    resource_id = initial["resource_id"]
    latest = client.get("/api/learning/english/scene/latest", params={"notebook_id": notebook})
    assert latest.json()["resource_id"] == resource_id
    assert client.get("/api/learning/english/scene/latest", params={"notebook_id": second}).json() is None
    assert client.post("/api/learning/english/scene/question", json={"resource_id": resource_id, "notebook_id": second}).status_code == 404
    request = {"resource_id": resource_id, "notebook_id": notebook}
    update = client.post("/api/learning/english/scene/question", json=request)
    assert update.status_code == 200, update.text
    assert update.json()["question"] == SCENE["question"]
    assert client.post("/api/learning/english/scene/question", json=request).status_code == 200
    assert len(calls) == 2  # main scene + one question, no generation on duplicate retry
    restored = client.get("/api/learning/english/scene/latest", params={"notebook_id": notebook}).json()
    assert restored["question"] == SCENE["question"]
    assert restored["lines"] == initial["lines"]
    assert restored["vocabulary"] == initial["vocabulary"]
    with session() as db:
        row = db.get(Resource, resource_id)
        assert row.payload["english_scene"]["generation"]["status"] == "completed"
        assert "练习暂未生成" not in row.payload["markdown"]
    other = client.post("/api/auth/register", json={"email": uuid.uuid4().hex+"@example.test", "password": "English-Test-Password!", "name": "隔离"}).json()
    client.headers["Authorization"] = "Bearer " + other["access_token"]
    assert client.get("/api/learning/english/scene/latest", params={"notebook_id": notebook}).status_code == 404
    assert client.post("/api/learning/english/scene/question", json={"resource_id": resource_id}).status_code == 404


def test_question_failure_keeps_original_persisted_payload(learner, monkeypatch):
    client, user = learner
    notebook = client.post("/api/notebooks", json={"user_id": user, "title": "英语错误恢复"}).json()["id"]
    monkeypatch.setattr(learning, "_english_available", lambda: None)
    async def complete(prompt, **kwargs):
        if "CAPABILITY=english.question" in prompt:
            raise ModelFailure("quota")
        return json.dumps({**SCENE, "question": None})
    monkeypatch.setattr(english, "llm_complete", complete)
    initial = client.post("/api/learning/english/scene", json={"words": "figure out", "notebook_id": notebook}).json()
    response = client.post("/api/learning/english/scene/question", json={"resource_id": initial["resource_id"], "notebook_id": notebook})
    assert response.status_code == 503
    assert client.get("/api/learning/english/scene/latest", params={"notebook_id": notebook}).json() == initial

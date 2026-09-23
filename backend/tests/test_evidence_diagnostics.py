from __future__ import annotations
import asyncio
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import create_engine, text

from app.agents import doc_agent, tutor_agent
from app.api.chat import _persisted_events
from app.llm.failures import ModelFailure, failure_code, generation_details
from app.models.db import _ensure_conversation_evidence
from app.rag.citation import build_context
from app.safety.grounding import grounding_check_local
from tests.test_learning_spaces import learner  # noqa: F401
from tests.test_kimi_models import kimi_transport, completion  # noqa: F401
from app.llm import spark_client

CHUNKS = [
    {"text": "递归把问题分成更小的问题。", "citation": "同一讲义 p.1", "source_id": "notes"},
    {"text": "递归必须有终止条件。" + "这是后续解释。" * 30, "citation": "同一讲义 p.1", "source_id": "notes"},
]

@pytest.mark.parametrize("answer,expected", [("递归永远不需要终止条件。[^2]", "citation_only"), ("递归永远不需要终止条件。", "lexical_overlap")])
def test_opposite_fact_is_never_reported_verified(answer, expected):
    result = grounding_check_local(answer, [c["text"] for c in CHUNKS])
    assert not result["grounded"] and result["accepted"]
    assert result["verification"] == expected


def test_empty_chunk_does_not_shift_valid_indices():
    assert grounding_check_local("递归[^2]", ["", CHUNKS[1]["text"]])["accepted"]
    assert not grounding_check_local("递归[^1]", ["", CHUNKS[1]["text"]]).get("accepted")


def test_full_evidence_preserves_same_source_multiple_indices():
    _, evidence = build_context(CHUNKS)
    assert evidence[1]["index"] == 2 and evidence[1]["excerpt"] == CHUNKS[1]["text"]
    assert len(evidence) == 2 and evidence[0]["citation"] == evidence[1]["citation"]


@pytest.mark.parametrize("policy", ["strict", "supplement"])
@pytest.mark.parametrize("late_index", ["2", "99"])
def test_tutor_checks_whole_answer_and_emits_original_index(monkeypatch, policy, late_index):
    events = []
    monkeypatch.setattr(tutor_agent, "retrieve", lambda *a, **k: CHUNKS)
    monkeypatch.setattr(tutor_agent, "is_demo", lambda: False)
    async def model(*args, **kwargs):
        yield "递归把问题分成更小的问题，而且必须有终止条件。" * 3
        assert not any(e.get("type") == "token" for e in events)
        yield "[^" + late_index + "]"
    async def capture(event): events.append(event)
    monkeypatch.setattr(tutor_agent, "llm_stream", model)
    monkeypatch.setattr(tutor_agent, "emit", capture)
    result = asyncio.run(tutor_agent.run({"messages": [{"role": "user", "content": "解释递归"}],
        "source_ids": ["notes"], "source_policy": policy, "student_profile": {}}))
    assert "[^99]" not in result["answer"]
    if late_index == "2":
        citation = next(e for e in events if e.get("type") == "citations")
        assert [c["index"] for c in citation["evidence"]] == [2]
        assert citation["evidence"][0]["excerpt"] == CHUNKS[1]["text"]
        ground = next(e["grounding"] for e in events if e.get("stage") == "grounding")
        assert not ground["grounded"] and ground["verification"] == "citation_only"


def test_unindexed_interaction_cannot_create_second_citation(monkeypatch):
    monkeypatch.setattr(tutor_agent, "retrieve", lambda *a, **k: CHUNKS[:1])
    monkeypatch.setattr(tutor_agent, "is_demo", lambda: False)
    async def model(prompt, **kwargs):
        assert "旧讲解[^2]" not in prompt
        yield "递归必须有终止条件。[^2]"
    monkeypatch.setattr(tutor_agent, "llm_stream", model)
    result = asyncio.run(tutor_agent.run({"messages": [{"role": "user", "content": "解释递归"}],
        "interaction_resource": {"markdown": "旧讲解[^2]", "title": "递归"},
        "source_ids": ["notes"], "source_policy": "supplement", "student_profile": {}}))
    assert "[^2]" not in result["answer"]


def test_sse_evidence_is_saved_with_answer(monkeypatch):
    saved=[]
    monkeypatch.setattr("app.api.chat.append_message", lambda *a, **k: saved.append((a,k)))
    _, evidence = build_context(CHUNKS)
    async def events():
        yield {"type": "token", "delta": "递归必须有终止条件。[^2]"}
        yield {"type": "citations", "agent": "tutor", "evidence": evidence[1:]}
        yield {"type": "citations", "agent": "doc", "evidence": evidence[:1]}
        yield {"type": "done"}
    async def run():
        return [e async for e in _persisted_events(events(), user_id="a", session_id="b")]
    asyncio.run(run())
    assert saved[0][1]["source_evidence"] == evidence[1:]


def test_old_sqlite_upgrade_is_additive_and_repeatable(tmp_path):
    engine=create_engine("sqlite:///" + str(tmp_path / "legacy.db"))
    with engine.begin() as c:
        c.execute(text("CREATE TABLE conversation_messages (id INTEGER PRIMARY KEY, content TEXT)"))
        c.execute(text("INSERT INTO conversation_messages VALUES (1, 'old message')"))
    _ensure_conversation_evidence(engine)
    _ensure_conversation_evidence(engine)
    with engine.connect() as c:
        assert tuple(c.execute(text("SELECT content, source_evidence FROM conversation_messages")).one()) == ("old message", None)
    engine.dispose()


@pytest.mark.parametrize("finish,body,code", [("length", "partial", "truncated"), ("stop", "", "empty_response")])
def test_model_keeps_safe_failure_reason(kimi_transport, finish, body, code):
    calls=kimi_transport(lambda _: httpx.Response(200, json=completion(body,finish)))
    with pytest.raises(ModelFailure) as error:
        asyncio.run(spark_client.llm_complete("private prompt"))
    assert error.value.code == code and len(calls) == 1
    assert "private" not in str(error.value)


@pytest.mark.parametrize("error,code", [(TimeoutError("secret"),"timeout"), (RuntimeError("secret"),"generation_failed")])
def test_doc_failure_reason_survives_resource_payload(monkeypatch,error,code):
    monkeypatch.setattr(doc_agent,"is_demo",lambda:False)
    monkeypatch.setattr(doc_agent,"retrieve",lambda *a,**k:CHUNKS)
    async def model(*a,**k): raise error
    monkeypatch.setattr(doc_agent,"llm_complete",model)
    result=asyncio.run(doc_agent._gen_one("doc","recursion",{},source_ids=["notes"],source_policy="supplement",skip_multimodal=True,goal="解释递归",trace_id="evidence-test"))
    details=result["resource"]["payload"]["generation_details"]
    assert details["reason_codes"] == [code] and details["status"] == "degraded"
    assert "secret" not in str(details) and "secret" not in str(result["flags"])


def test_rejected_doc_does_not_invent_citation_support(monkeypatch):
    monkeypatch.setattr(doc_agent,"is_demo",lambda:False)
    monkeypatch.setattr(doc_agent,"retrieve",lambda *a,**k:CHUNKS)
    async def model(*a,**k): return "递归不需要终止条件。"
    async def judge(*a,**k): return {"grounded":False,"unsupported":["错误"],"verdict":"与原文冲突"}
    monkeypatch.setattr(doc_agent,"llm_complete",model)
    monkeypatch.setattr(doc_agent,"grounding_check",judge)
    result=asyncio.run(doc_agent._gen_one("doc","recursion",{},source_ids=["notes"],source_policy="strict",skip_multimodal=True,goal="解释递归",trace_id="evidence-test"))
    payload=result["resource"]["payload"]
    assert not payload["grounded"] and "[^" not in payload["markdown"]
    assert payload["source_evidence"] == [] and result["resource"]["citations"] == []


def test_saved_evidence_survives_notebook_reload_and_owner_boundary(learner):
    from app.services.conversation_service import append_message, get_session_messages, clear_session_messages
    from app.services.notebook_service import get_notebook
    from fastapi import HTTPException
    client,user=learner
    book=client.post("/api/notebooks",json={"user_id":user,"title":"原文测试"}).json()
    _,evidence=build_context(CHUNKS)
    append_message(user,book["session_id"],"assistant","递归[^2]",source_evidence=evidence[1:])
    saved=client.get(f"/api/notebooks/{book['id']}?user_id={user}").json()
    assert saved["messages"][0]["source_evidence"] == evidence[1:]
    assert get_session_messages(user,book["session_id"])[0]["source_evidence"] == evidence[1:]
    assert get_session_messages("outsider",book["session_id"]) == []
    with pytest.raises(HTTPException): get_notebook("outsider",book["id"],include_messages=True)
    assert clear_session_messages("outsider",book["session_id"]) == 0
    assert clear_session_messages(user,book["session_id"]) == 1


@pytest.mark.parametrize("template", ["complete_notes", "one_page"])
def test_strict_doc_rejects_invalid_index_even_if_semantics_would_pass(monkeypatch,template):
    monkeypatch.setattr(doc_agent,"is_demo",lambda:False)
    monkeypatch.setattr(doc_agent,"retrieve",lambda *a,**k:CHUNKS[:1])
    monkeypatch.setattr(doc_agent,"render_one_page",lambda *a,**k:{"image_status":"ready"})
    async def model(*a,**k): return "递归必须有终止条件。[^99]"
    async def judge(*a,**k): pytest.fail("Invalid citations must be rejected before a billed semantic check")
    monkeypatch.setattr(doc_agent,"llm_complete",model)
    monkeypatch.setattr(doc_agent,"grounding_check",judge)
    result=asyncio.run(doc_agent._gen_one("doc","recursion",{},source_ids=["notes"],source_policy="strict",
        prompt_template=template,skip_multimodal=True,goal="解释递归",trace_id="invalid-strict"))
    payload=result["resource"]["payload"]
    assert "[^99]" not in payload["markdown"]
    assert payload["generation_mode"] == "source_guide"
    assert "invalid_citation" in payload["generation_details"]["reason_codes"]

from __future__ import annotations

import asyncio
import json

import pytest

from app.agents import media_agent, mindmap_agent, quiz_agent, tutor_agent
from app.rag import ingest
from app.schemas.core import ChatRequest


def test_chat_request_accepts_selected_sources():
    request = ChatRequest(message="讲讲递归", source_ids=["source-a", "source-b"])
    assert request.source_ids == ["source-a", "source-b"]


def test_tutor_retrieval_is_limited_to_selected_sources(monkeypatch):
    captured: dict[str, object] = {}

    def fake_retrieve(query: str, **kwargs):
        captured["query"] = query
        captured["source_ids"] = kwargs.get("source_ids")
        return [
            {
                "text": "递归函数必须有终止条件。",
                "source": "用户讲义",
                "chapter": "递归",
                "page": 1,
                "citation": "用户讲义 · 递归 p.1",
            }
        ]

    async def fake_stream(*args, **kwargs):
        yield "递归需要终止条件。[^1]"

    async def fake_grounding(*args, **kwargs):
        return {"grounded": True, "unsupported": [], "verdict": "ok"}

    monkeypatch.setattr(tutor_agent, "retrieve", fake_retrieve)
    monkeypatch.setattr(tutor_agent, "llm_stream", fake_stream)
    monkeypatch.setattr(tutor_agent, "grounding_check", fake_grounding)

    result = asyncio.run(
        tutor_agent.run(
            {
                "user_id": "demo_user",
                "session_id": "source-chat",
                "messages": [{"role": "user", "content": "讲讲递归"}],
                "source_ids": ["source-a"],
                "student_profile": {},
            }
        )
    )

    assert captured["source_ids"] == ["source-a"]
    assert result["citations"] == ["用户讲义 · 递归 p.1"]


def test_selected_source_mindmap_does_not_add_course_graph_relations():
    assert mindmap_agent._outline_for_scope("binary_tree", ["source-a"]) == [
        ("资料要点", "binary_tree")
    ]
    assert len(mindmap_agent._outline_for_scope("binary_tree", [])) > 1


def test_source_bound_video_prompt_ignores_unsourced_model_prompt():
    prompt = media_agent._seedance_prompt(
        {
            "video_prompt": "Add an unrelated red-black tree proof.",
            "narration": "递归函数必须有终止条件。",
            "scenes": [{"caption": "终止条件"}],
        },
        source_bound=True,
    )
    assert "递归函数必须有终止条件" in prompt
    assert "终止条件" in prompt
    assert "red-black tree" not in prompt


def test_source_fallback_quiz_shows_the_excerpt_and_citation():
    questions = quiz_agent._source_fallback_questions(
        [{"text": "递归函数必须有终止条件，否则调用不会停止。", "citation": "用户讲义 p.1"}],
        "recursion",
        2,
    )
    assert "递归函数必须有终止条件" in questions[0]["stem"]
    assert "用户讲义 p.1" in questions[0]["explain"]


def test_validate_source_scope_enforces_owner_and_normalizes(monkeypatch, tmp_path):
    own = {"id": "source-a", "user_id": "alice", "active": True, "status": "active"}
    foreign = {"id": "source-b", "user_id": "bob", "active": True, "status": "active"}
    (tmp_path / "source-a.meta.json").write_text(json.dumps(own), encoding="utf-8")
    (tmp_path / "source-b.meta.json").write_text(json.dumps(foreign), encoding="utf-8")
    monkeypatch.setattr(ingest, "UPLOAD_SOURCES_DIR", tmp_path)
    monkeypatch.setattr(
        ingest,
        "load_all_chunks",
        lambda: [{"source_id": "source-a"}, {"source_id": "source-b"}],
    )

    assert ingest.validate_source_scope("alice", [" source-a ", "source-a"]) == ["source-a"]
    with pytest.raises(ValueError, match="selected sources are unavailable"):
        ingest.validate_source_scope("alice", ["source-b"])

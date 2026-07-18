"""API contract checks for SSE events and generated resources.

The goal is to catch frontend/backend drift early: the generation flow may still
finish, but the UI can break if a resource payload field is renamed or omitted.
"""
from __future__ import annotations

import asyncio
import os
import sys
from typing import Any

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tests._stubs import install  # noqa: E402

install()

from app.agents.graph import run_with_events  # noqa: E402
from app.api.debug import read_run_report  # noqa: E402
from app.config import UPLOAD_SOURCES_DIR  # noqa: E402
from app.main import app  # noqa: E402
from app.models.db import init_db  # noqa: E402
from app.rag.ingest import ingest_corpus  # noqa: E402
from app.rag.retriever import COURSE_SOURCE, retrieve  # noqa: E402
from app.services.profile_service import ensure_user  # noqa: E402

ALLOWED_EVENTS = {
    "agent_start",
    "agent_end",
    "agent_token",
    "token",
    "resource",
    "profile",
    "path",
    "progress",
    "citations",
    "safety",
    "summary",
    "trace",
    "error",
    "done",
}

ALLOWED_AGENTS = {
    "profile",
    "orchestrator",
    "planner",
    "path",
    "doc",
    "mindmap",
    "quiz",
    "media",
    "tutor",
    "eval",
}

TEXT_RESOURCE_KINDS = {"doc", "code", "reading"}
GENERATE_STATE = {
    "user_id": "contract_user",
    "session_id": "contract-generate",
    "messages": [{"role": "user", "content": "请生成二叉树的教程、脑图、题组和讲解视频"}],
    "knowledge_points": ["binary_tree"],
    "kinds": ["doc", "mindmap", "quiz", "video"],
    "intent": "generate",
}


async def _collect(state: dict[str, Any]) -> list[dict[str, Any]]:
    return [event async for event in run_with_events(state)]


def _assert_base_event(event: dict[str, Any]) -> None:
    assert isinstance(event.get("type"), str), f"event.type missing: {event}"
    assert event["type"] in ALLOWED_EVENTS, f"unknown event type: {event['type']}"
    if event["type"] != "done":
        assert "ts" in event, f"non-terminal event should include ts: {event}"
    if "agent" in event:
        assert event["agent"] in ALLOWED_AGENTS, f"unknown agent id: {event['agent']}"


def _assert_resource(resource: dict[str, Any]) -> None:
    for key in ("id", "kind", "kp", "title", "payload", "citations"):
        assert key in resource, f"resource missing {key}: {resource}"
    assert isinstance(resource["id"], str) and resource["id"]
    assert isinstance(resource["kind"], str) and resource["kind"]
    assert isinstance(resource["kp"], str) and resource["kp"]
    assert isinstance(resource["title"], str) and resource["title"]
    assert isinstance(resource["payload"], dict), resource
    assert isinstance(resource["citations"], list), resource
    assert all(isinstance(c, str) for c in resource["citations"]), resource

    payload = resource["payload"]
    kind = resource["kind"]
    if kind in TEXT_RESOURCE_KINDS:
        assert isinstance(payload.get("markdown"), str) and payload["markdown"].strip(), resource
        assert isinstance(payload.get("grounded"), bool), resource
    elif kind == "mindmap":
        assert isinstance(payload.get("markmap"), str) and payload["markmap"].lstrip().startswith("#"), resource
    elif kind == "quiz":
        questions = payload.get("questions")
        assert isinstance(questions, list) and questions, resource
        assert isinstance(payload.get("difficulty"), int), resource
        for q in questions:
            _assert_quiz_question(q)
    elif kind == "video":
        assert any(k in payload for k in ("script", "video", "manim_code")), resource
        if "script" in payload:
            script = payload["script"]
            assert isinstance(script, dict), resource
            assert isinstance(script.get("title"), str) and script["title"], resource
            assert isinstance(script.get("narration"), str) and script["narration"], resource
            assert isinstance(script.get("scenes"), list), resource


def _assert_quiz_question(question: dict[str, Any]) -> None:
    for key in ("id", "type", "stem", "options", "answer", "kp", "difficulty", "error_tags"):
        assert key in question, f"quiz question missing {key}: {question}"
    assert question["type"] in {"single", "fill", "judge", "design", "complexity"}, question
    assert isinstance(question["stem"], str) and question["stem"], question
    assert isinstance(question["options"], list), question
    assert isinstance(question["answer"], str) and question["answer"], question
    assert isinstance(question["kp"], str) and question["kp"], question
    assert isinstance(question["difficulty"], int), question
    assert isinstance(question["error_tags"], list), question


def test_generate_sse_contract():
    init_db()
    ingest_corpus()
    ensure_user("contract_user")

    events = asyncio.run(_collect(dict(GENERATE_STATE)))
    assert events[0]["type"] == "trace"
    assert events[-1]["type"] == "done"
    assert sum(1 for e in events if e["type"] == "done") == 1
    assert not [e for e in events if e["type"] == "error"]

    for event in events:
        _assert_base_event(event)
        if event["type"] == "agent_start":
            assert isinstance(event.get("label"), str) and event["label"], event
            assert isinstance(event.get("detail"), str), event
        elif event["type"] == "agent_end":
            assert isinstance(event.get("summary"), str), event
            assert isinstance(event.get("output"), dict), event
        elif event["type"] == "resource":
            _assert_resource(event.get("resource") or {})
        elif event["type"] == "profile":
            assert isinstance(event.get("profile"), dict), event
        elif event["type"] == "path":
            path = event.get("path")
            assert isinstance(path, dict) and isinstance(path.get("nodes"), list), event
            assert isinstance(path.get("edges"), list), event
        elif event["type"] == "progress":
            assert isinstance(event.get("stage"), str), event
            assert isinstance(event.get("percent"), int), event
        elif event["type"] == "citations":
            assert isinstance(event.get("items"), list), event
        elif event["type"] == "summary":
            assert isinstance(event.get("text"), str) and event["text"], event
        elif event["type"] == "trace":
            assert isinstance(event.get("session_id"), str) and event["session_id"], event
            assert isinstance(event.get("run_dir"), str) and event["run_dir"], event

    resources = [event["resource"] for event in events if event["type"] == "resource"]
    assert {"doc", "mindmap", "quiz", "video"} <= {r["kind"] for r in resources}


def test_interactive_audio_contract_keeps_a_playable_browser_fallback():
    init_db()
    ingest_corpus()
    ensure_user("contract_audio_user")
    events = asyncio.run(_collect({
        "user_id": "contract_audio_user",
        "session_id": "contract-interactive-audio",
        "messages": [{"role": "user", "content": "请生成二叉树互动讲解"}],
        "learning_goal": "请生成二叉树互动讲解",
        "knowledge_points": ["binary_tree"],
        "kinds": ["doc"],
        "prompt_template": "interactive_audio",
        "intent": "generate",
    }))

    resource = next(
        event["resource"] for event in events
        if event.get("type") == "resource" and event.get("resource", {}).get("kind") == "doc"
    )
    payload = resource["payload"]
    assert resource["title"] == "二叉树·互动讲解"
    assert payload["template"] == "interactive_audio"
    assert payload["audio_narration"].startswith("本节讲解二叉树")
    assert payload["audio"]["status"] in {"ready", "fallback"}
    if payload["audio"]["status"] == "fallback":
        assert payload["audio"]["provider"] == "browser_speech"
        assert payload["audio"]["error"]


def test_debug_run_report_contract():
    init_db()
    ingest_corpus()
    ensure_user("contract_user")
    events = asyncio.run(_collect(dict(GENERATE_STATE, session_id="contract-debug-report")))
    trace = events[0]
    report = read_run_report(trace["session_id"])
    assert report["session_id"] == trace["session_id"]
    assert report["run_dir"].endswith(trace["session_id"])
    assert "SparkLearn Debug Report" in report["debug_report"]
    assert report["summary"]["event_counts"]["resource"] >= 4
    assert report["resources"], report
    assert report["timeline"], report


def test_knowledge_upload_search_contract():
    init_db()
    ensure_user("contract_user")
    source_id = ""
    other_source_id = ""
    try:
        with TestClient(app) as client:
            content = (
                "Contract upload source. Binary tree inorder traversal visits "
                "left subtree, root, then right subtree. This uploaded note is "
                "used to verify that user documents are indexed and searchable. "
            ).encode("utf-8")
            res = client.post(
                "/api/knowledge/upload",
                data={
                    "user_id": "contract_user",
                    "kp": "binary_tree",
                    "title": "Contract Binary Tree Notes",
                },
                files={"file": ("contract-binary-tree.txt", content, "text/plain")},
            )
            assert res.status_code == 200, res.text
            payload = res.json()
            source_id = payload["source"]["id"]
            assert payload["source"]["status"] == "indexed"
            assert payload["source"]["selectable"] is True
            assert "索引已完成" in payload["source"]["status_detail"]
            assert payload["source"]["chunk_count"] >= 1

            search = client.get(
                "/api/knowledge/search",
                params={
                    "query": "Contract upload source binary tree inorder traversal",
                    "kp": "binary_tree",
                    "limit": 5,
                },
            )
            assert search.status_code == 200, search.text
            items = search.json()["items"]
            assert items and all(item["source"] == COURSE_SOURCE for item in items), items
            assert not any(item["source_id"] == source_id for item in items), items

            selected_hits = retrieve(
                "Contract upload source binary tree inorder traversal",
                source_ids=[source_id],
                kp="binary_tree",
                final_k=5,
                user_id="contract_user",
            )
            assert any(item["source_id"] == source_id for item in selected_hits), selected_hits

            duplicate = client.post(
                "/api/knowledge/upload",
                data={
                    "user_id": "contract_user",
                    "kp": "binary_tree",
                    "title": "Contract Binary Tree Notes Duplicate",
                },
                files={"file": ("contract-binary-tree-copy.txt", content, "text/plain")},
            )
            assert duplicate.status_code == 200, duplicate.text
            assert duplicate.json()["duplicate"] is True
            assert duplicate.json()["source"]["id"] == source_id

            # Tenant-local dedup: another learner may upload the same textbook.
            ensure_user("contract_other_user")
            other = client.post(
                "/api/knowledge/upload",
                data={
                    "user_id": "contract_other_user",
                    "kp": "binary_tree",
                    "title": "Other Learner Binary Tree Notes",
                },
                files={"file": ("same-content.txt", content, "text/plain")},
            )
            assert other.status_code == 200, other.text
            other_source_id = other.json()["source"]["id"]
            other_hits = retrieve(
                "Contract upload source binary tree inorder traversal",
                source_ids=[other_source_id],
                user_id="contract_other_user",
                final_k=5,
            )
            assert other_hits and all(
                hit.get("user_id") == "contract_other_user" for hit in other_hits
            )
            assert retrieve(
                "Contract upload source binary tree inorder traversal",
                source_ids=[other_source_id],
                user_id="contract_user",
                final_k=5,
            ) == []

        events = asyncio.run(_collect(dict(
            GENERATE_STATE,
            session_id="contract-source-generate",
            kinds=["doc"],
            source_ids=[source_id],
            messages=[{"role": "user", "content": "请基于上传资料生成二叉树图文教程"}],
            learning_goal="基于上传资料生成",
        )))
        docs = [
            event["resource"]
            for event in events
            if event["type"] == "resource" and event["resource"]["kind"] == "doc"
        ]
        assert docs, events
        assert any(
            "Contract Binary Tree Notes" in citation
            for citation in docs[0]["citations"]
        ), docs[0]["citations"]
    finally:
        if source_id:
            for path in UPLOAD_SOURCES_DIR.glob(f"{source_id}*"):
                path.unlink(missing_ok=True)
        if other_source_id:
            for path in UPLOAD_SOURCES_DIR.glob(f"{other_source_id}*"):
                path.unlink(missing_ok=True)
        if source_id or other_source_id:
            ingest_corpus(force=True)


def test_tutor_sse_contract():
    ensure_user("contract_user")
    events = asyncio.run(_collect({
        "user_id": "contract_user",
        "session_id": "contract-tutor",
        "messages": [{"role": "user", "content": "为什么 Dijkstra 不能处理负权边?"}],
        "intent": "tutor",
    }))
    assert events[0]["type"] == "trace"
    assert events[-1]["type"] == "done"
    assert not [e for e in events if e["type"] == "error"]
    for event in events:
        _assert_base_event(event)
        if event["type"] == "token":
            assert isinstance(event.get("delta"), str) and event["delta"], event
        if event["type"] == "citations":
            assert isinstance(event.get("items"), list) and event["items"], event


if __name__ == "__main__":
    test_generate_sse_contract()
    print("test_generate_sse_contract ... ok")
    test_debug_run_report_contract()
    print("test_debug_run_report_contract ... ok")
    test_knowledge_upload_search_contract()
    print("test_knowledge_upload_search_contract ... ok")
    test_tutor_sse_contract()
    print("test_tutor_sse_contract ... ok")
    print("ALL API CONTRACT TESTS PASSED")

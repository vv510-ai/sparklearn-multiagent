"""Trace evidence must explain learning-output quality decisions."""
from __future__ import annotations

import json
from types import SimpleNamespace

from app import trace as trace_module


def test_trace_records_prompt_retrieval_fallback_grounding_and_latency(monkeypatch, tmp_path):
    monkeypatch.setattr(trace_module, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(
        trace_module,
        "get_settings",
        lambda: SimpleNamespace(trace_enabled=True),
    )

    recorder = trace_module.TraceRecorder({
        "user_id": "demo_user",
        "session_id": "quality-trace",
        "messages": [{"role": "user", "content": "讲讲递归"}],
        "source_ids": ["source-a"],
    })
    recorder.record_event({"type": "agent_start", "agent": "tutor", "label": "答疑导师"})
    recorder.record_event({
        "type": "progress",
        "agent": "tutor",
        "stage": "retrieval",
        "retrieval": {
            "needed": True,
            "reason": "knowledge_question",
            "source_ids": ["source-a"],
            "count": 1,
            "chunks": [{"chunk_id": "chunk-1", "source_id": "source-a", "score": 0.92}],
        },
    })
    recorder.record_event({
        "type": "progress",
        "agent": "tutor",
        "stage": "prompt_skill",
        "prompt_skill": {
            "name": "sparklearn.learning_prompt",
            "capability": "tutor.followup",
            "version": "test-version",
        },
    })
    recorder.record_event({
        "type": "progress",
        "agent": "tutor",
        "stage": "fallback",
        "degraded": True,
        "reason": "demo_mode",
        "detail": "deterministic fallback",
    })
    recorder.record_event({
        "type": "progress",
        "agent": "tutor",
        "stage": "grounding",
        "grounding": {"grounded": True, "unsupported_count": 0, "verdict": "ok"},
    })
    recorder.record_event({
        "type": "resource",
        "resource": {
            "id": "doc-1",
            "kind": "doc",
            "title": "递归笔记",
            "payload": {
                "prompt_skill": {
                    "name": "sparklearn.learning_prompt",
                    "capability": "doc.complete_notes",
                    "version": "test-version",
                }
            },
            "citations": ["资料 p.1"],
        },
    })
    recorder.record_event({
        "type": "agent_end",
        "agent": "tutor",
        "summary": "done",
        "output": {"grounding": {"grounded": True}},
    })
    recorder.record_final_state({
        "user_id": "demo_user",
        "session_id": "quality-trace",
        "messages": [],
        "source_ids": ["source-a"],
        "generated_resources": {},
    })
    recorder.finish()

    summary = json.loads((tmp_path / "quality-trace" / "summary.json").read_text(encoding="utf-8"))
    quality = summary["quality_evidence"]
    assert quality["counts"] == {
        "prompt_calls": 2,
        "retrievals": 1,
        "degraded_events": 1,
        "grounding_checks": 1,
    }
    assert quality["prompt_calls"][0]["capability"] == "tutor.followup"
    assert quality["retrievals"][0]["chunks"][0]["chunk_id"] == "chunk-1"
    assert quality["degraded_events"][0]["reason"] == "demo_mode"
    assert quality["grounding_checks"][0]["grounded"] is True
    assert summary["agents"] == ["tutor"]

    agent_status = json.loads(
        (tmp_path / "quality-trace" / "agent_status.json").read_text(encoding="utf-8")
    )
    assert isinstance(agent_status["tutor"]["duration_ms"], int)
    assert agent_status["tutor"]["duration_ms"] >= 0
    assert (tmp_path / "quality-trace" / "quality.evidence.json").exists()

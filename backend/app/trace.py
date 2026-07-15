from __future__ import annotations

import datetime as dt
import json
import re
import shutil
from collections import Counter
from pathlib import Path
from typing import Any

from .config import RUNS_DIR, get_settings

AGENT_ORDER = [
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
]


def _safe_name(value: Any) -> str:
    text = str(value or "item").strip()
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", text)
    return text.strip("_") or "item"


def _json_default(value: Any) -> str:
    if isinstance(value, (dt.datetime, dt.date)):
        return value.isoformat()
    return str(value)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def _preview(value: Any, limit: int = 180) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False, default=_json_default)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit] + ("..." if len(text) > limit else "")


def _duration_ms(started_at: Any, ended_at: Any) -> int | None:
    try:
        started = dt.datetime.fromisoformat(str(started_at))
        ended = dt.datetime.fromisoformat(str(ended_at))
    except (TypeError, ValueError):
        return None
    return max(0, round((ended - started).total_seconds() * 1000))


def _resource_summary(resource: dict[str, Any]) -> dict[str, Any]:
    payload = resource.get("payload") or {}
    prompt_skill = payload.get("prompt_skill") if isinstance(payload, dict) else None
    return {
        "id": resource.get("id"),
        "kind": resource.get("kind"),
        "kp": resource.get("kp"),
        "title": resource.get("title"),
        "payload_keys": sorted(payload) if isinstance(payload, dict) else [],
        "citation_count": len(resource.get("citations") or []),
        "prompt_skill": prompt_skill if isinstance(prompt_skill, dict) else None,
        "degraded": bool(payload.get("degraded")) if isinstance(payload, dict) else False,
    }


class TraceRecorder:
    def __init__(self, state: dict[str, Any]) -> None:
        self.enabled = bool(get_settings().trace_enabled)
        self.session_id = _safe_name(state.get("session_id", "default"))
        self.run_dir = RUNS_DIR / self.session_id
        self.started_at = dt.datetime.now(dt.timezone.utc)
        self.events: list[dict[str, Any]] = []
        self.counts: Counter[str] = Counter()
        self.resources: list[dict[str, Any]] = []
        self.agent_outputs: dict[str, dict[str, Any]] = {}
        self.agent_status: dict[str, dict[str, Any]] = {}
        self.timeline: list[dict[str, Any]] = []
        self.final_state_summary: dict[str, Any] = {}
        self.prompt_calls: list[dict[str, Any]] = []
        self.retrievals: list[dict[str, Any]] = []
        self.degraded_events: list[dict[str, Any]] = []
        self.grounding_checks: list[dict[str, Any]] = []
        if self.enabled:
            self._prepare_run_dir()
            _write_json(self.run_dir / "request.json", state)
            (self.run_dir / "events.jsonl").write_text("", encoding="utf-8")

    def _prepare_run_dir(self) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        for child in self.run_dir.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()

    def record_event(self, event: dict[str, Any]) -> None:
        if not self.enabled:
            return
        event = dict(event)
        event_index = len(self.events) + 1
        event["_trace_index"] = event_index
        event["_captured_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
        self.events.append(event)
        etype = str(event.get("type", "unknown"))
        self.counts[etype] += 1
        self._record_timeline(event_index, event)
        self._record_quality_evidence(event_index, event)

        with (self.run_dir / "events.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False, default=_json_default) + "\n")

        if etype == "profile":
            _write_json(self.run_dir / "profile.output.json", event.get("profile", {}))
        elif etype == "path":
            _write_json(self.run_dir / "path.output.json", event.get("path", {}))
        elif etype == "resource":
            resource = event.get("resource") or {}
            self.resources.append(resource)
            kind = _safe_name(resource.get("kind", "resource"))
            rid = _safe_name(resource.get("id", len(self.resources)))
            _write_json(self.run_dir / "resources" / f"{kind}_{rid}.json", resource)
        elif etype == "agent_end":
            agent = _safe_name(event.get("agent", "agent"))
            self.agent_outputs[agent] = event
            _write_json(self.run_dir / "agent_end" / f"{agent}.json", event)
            output = event.get("output") or {}
            if output:
                _write_json(self.run_dir / "agent_outputs" / f"{agent}.output.json", output)
        elif etype == "summary":
            _write_json(self.run_dir / "eval.output.json", event)
        elif etype == "citations":
            agent = _safe_name(event.get("agent", "global"))
            idx = self.counts[etype]
            _write_json(self.run_dir / "citations" / f"{agent}_{idx}.json", event.get("items", []))
        elif etype in {"progress", "safety", "error"}:
            idx = self.counts[etype]
            _write_json(self.run_dir / "events_by_type" / f"{etype}_{idx}.json", event)

    def _record_quality_evidence(self, event_index: int, event: dict[str, Any]) -> None:
        agent = event.get("agent")
        stage = event.get("stage")
        base = {
            "event": event_index,
            "agent": agent,
            "stage": stage,
            "captured_at": event.get("_captured_at"),
        }
        prompt_skill = event.get("prompt_skill")
        if isinstance(prompt_skill, dict):
            self.prompt_calls.append({**base, **prompt_skill})

        retrieval = event.get("retrieval")
        if isinstance(retrieval, dict):
            self.retrievals.append({**base, **retrieval})

        grounding = event.get("grounding")
        if isinstance(grounding, dict):
            self.grounding_checks.append({**base, **grounding})

        if event.get("degraded"):
            self.degraded_events.append({
                **base,
                "reason": event.get("reason") or stage or "degraded",
                "detail": event.get("detail", ""),
                "error": event.get("error", ""),
            })

        if event.get("type") == "resource":
            resource = event.get("resource") or {}
            payload = resource.get("payload") or {}
            resource_prompt = payload.get("prompt_skill") if isinstance(payload, dict) else None
            if isinstance(resource_prompt, dict):
                self.prompt_calls.append({
                    **base,
                    **resource_prompt,
                    "resource_id": resource.get("id"),
                    "resource_kind": resource.get("kind"),
                })

    def _record_timeline(self, event_index: int, event: dict[str, Any]) -> None:
        etype = str(event.get("type", "unknown"))
        agent = event.get("agent")
        entry: dict[str, Any] = {
            "i": event_index,
            "type": etype,
            "agent": agent,
            "ts": event.get("ts"),
        }

        if etype == "agent_start":
            detail = event.get("detail", "")
            self.agent_status[str(agent)] = {
                "status": "running",
                "label": event.get("label"),
                "detail": detail,
                "start_event": event_index,
                "started_at": event.get("ts"),
                "started_captured_at": event.get("_captured_at"),
            }
            entry["title"] = f"{agent} started"
            entry["detail"] = detail
        elif etype == "agent_end":
            status = self.agent_status.setdefault(str(agent), {})
            duration_ms = _duration_ms(
                status.get("started_captured_at"),
                event.get("_captured_at"),
            )
            status.update({
                "status": "done",
                "summary": event.get("summary", ""),
                "end_event": event_index,
                "ended_at": event.get("ts"),
                "output_keys": sorted((event.get("output") or {}).keys()),
                "duration_ms": duration_ms,
            })
            entry["title"] = f"{agent} done"
            entry["summary"] = event.get("summary", "")
            entry["duration_ms"] = duration_ms
        elif etype == "resource":
            resource = event.get("resource") or {}
            entry["title"] = f"resource: {resource.get('kind')} {resource.get('title')}"
            entry["resource"] = _resource_summary(resource)
        elif etype == "progress":
            entry["title"] = f"{agent or 'task'} progress"
            entry["stage"] = event.get("stage")
            entry["percent"] = event.get("percent")
            entry["detail"] = event.get("detail")
        elif etype == "profile":
            entry["title"] = "profile updated"
            entry["profile_keys"] = sorted((event.get("profile") or {}).keys())
        elif etype == "path":
            path = event.get("path") or {}
            entry["title"] = "path updated"
            entry["node_count"] = len(path.get("nodes") or [])
            entry["next_kp"] = path.get("next_kp")
        elif etype == "citations":
            items = event.get("items") or []
            entry["title"] = f"citations: {len(items)}"
            entry["count"] = len(items)
        elif etype == "summary":
            entry["title"] = "summary"
            entry["text"] = _preview(event.get("text"))
        elif etype == "trace":
            entry["title"] = "trace ready"
            entry["session_id"] = event.get("session_id")
            entry["run_dir"] = event.get("run_dir")
        elif etype in {"safety", "error"}:
            entry["title"] = etype
            entry["detail"] = event.get("detail")
            if etype == "error" and agent:
                self.agent_status.setdefault(str(agent), {}).update({
                    "status": "error",
                    "error": event.get("detail"),
                    "end_event": event_index,
                })
        elif etype == "done":
            entry["title"] = "stream done"
        else:
            entry["title"] = etype

        self.timeline.append(entry)

    def record_final_state(self, state: dict[str, Any] | None) -> None:
        if not self.enabled or state is None:
            return
        _write_json(self.run_dir / "final_state.json", state)
        self.final_state_summary = self._summarize_state(state)
        _write_json(self.run_dir / "state.summary.json", self.final_state_summary)
        if state.get("plan"):
            _write_json(self.run_dir / "planner.output.json", state["plan"])
        if state.get("path_plan"):
            _write_json(self.run_dir / "path.output.json", state["path_plan"])
        resources = state.get("generated_resources") or {}
        if resources:
            _write_json(self.run_dir / "final.resources.json", resources)
            _write_json(
                self.run_dir / "resources" / "index.json",
                [_resource_summary(r) for r in resources.values()],
            )
        for key, filename in (
            ("retrieval_context", "retrieval.output.json"),
            ("citations", "citations.output.json"),
            ("safety_flags", "safety_flags.output.json"),
            ("progress_events", "progress_events.output.json"),
        ):
            if state.get(key):
                _write_json(self.run_dir / filename, state[key])
        if state.get("answer"):
            _write_text(self.run_dir / "answer.output.md", str(state["answer"]))

    def _summarize_state(self, state: dict[str, Any]) -> dict[str, Any]:
        messages = state.get("messages") or []
        resources = state.get("generated_resources") or {}
        path_plan = state.get("path_plan") or {}
        return {
            "user_id": state.get("user_id"),
            "session_id": state.get("session_id"),
            "intent": state.get("intent"),
            "learning_goal": state.get("learning_goal"),
            "knowledge_points": state.get("knowledge_points") or [],
            "kinds": state.get("kinds") or [],
            "source_ids": state.get("source_ids") or [],
            "message_count": len(messages),
            "last_user_message": _preview(
                next((m.get("content") for m in reversed(messages)
                      if isinstance(m, dict) and m.get("role") == "user"), "")
            ),
            "profile_keys": sorted((state.get("student_profile") or {}).keys()),
            "plan_keys": sorted((state.get("plan") or {}).keys()),
            "path": {
                "node_count": len(path_plan.get("nodes") or []),
                "edge_count": len(path_plan.get("edges") or []),
                "next_kp": path_plan.get("next_kp"),
            },
            "resources": [_resource_summary(r) for r in resources.values()],
            "retrieval_context_count": len(state.get("retrieval_context") or []),
            "citation_count": len(state.get("citations") or []),
            "safety_flag_count": len(state.get("safety_flags") or []),
            "progress_event_count": len(state.get("progress_events") or []),
            "has_answer": bool(state.get("answer")),
            "answer_preview": _preview(state.get("answer")),
        }

    def record_error(self, detail: str) -> None:
        if self.enabled:
            _write_json(self.run_dir / "error.json", {"detail": detail})
            self.timeline.append({
                "i": len(self.events) + 1,
                "type": "error",
                "title": "runner error",
                "detail": detail,
            })

    def finish(self) -> None:
        if not self.enabled:
            return
        _write_json(self.run_dir / "events.json", self.events)
        _write_json(self.run_dir / "timeline.json", self.timeline)
        _write_json(self.run_dir / "agent_status.json", self._ordered_agent_status())
        quality_evidence = self._quality_evidence()
        _write_json(self.run_dir / "quality.evidence.json", quality_evidence)
        _write_text(self.run_dir / "debug_report.md", self._debug_report())
        summary = {
            "session_id": self.session_id,
            "run_dir": str(self.run_dir),
            "started_at": self.started_at.isoformat(),
            "captured_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "event_counts": dict(self.counts),
            "agents": list(self._ordered_agent_status()),
            "route": [e.get("agent") for e in self.timeline
                      if e.get("type") == "agent_start" and e.get("agent")],
            "resources": [
                _resource_summary(r)
                for r in self.resources
            ],
            "quality_evidence": quality_evidence,
            "state": self.final_state_summary,
            "files": {
                "request": "request.json",
                "debug_report": "debug_report.md",
                "timeline": "timeline.json",
                "agent_status": "agent_status.json",
                "state_summary": "state.summary.json",
                "events": "events.json",
                "events_jsonl": "events.jsonl",
                "quality_evidence": "quality.evidence.json",
                "profile": "profile.output.json",
                "planner": "planner.output.json",
                "path": "path.output.json",
                "resources": "resources/",
                "retrieval": "retrieval.output.json",
                "citations": "citations.output.json",
                "safety_flags": "safety_flags.output.json",
                "progress_events": "progress_events.output.json",
                "agent_end": "agent_end/",
                "agent_outputs": "agent_outputs/",
                "final_state": "final_state.json",
            },
        }
        _write_json(self.run_dir / "summary.json", summary)

    def _quality_evidence(self) -> dict[str, Any]:
        return {
            "prompt_calls": self.prompt_calls,
            "retrievals": self.retrievals,
            "degraded_events": self.degraded_events,
            "grounding_checks": self.grounding_checks,
            "counts": {
                "prompt_calls": len(self.prompt_calls),
                "retrievals": len(self.retrievals),
                "degraded_events": len(self.degraded_events),
                "grounding_checks": len(self.grounding_checks),
            },
        }

    def _ordered_agent_status(self) -> dict[str, dict[str, Any]]:
        ordered = {}
        for agent in AGENT_ORDER:
            if agent in self.agent_status:
                ordered[agent] = self.agent_status[agent]
        for agent in sorted(set(self.agent_status) - set(ordered)):
            ordered[agent] = self.agent_status[agent]
        return ordered

    def _debug_report(self) -> str:
        route = [
            str(e.get("agent"))
            for e in self.timeline
            if e.get("type") == "agent_start" and e.get("agent")
        ]
        errors = [e for e in self.timeline if e.get("type") == "error"]
        safety = [e for e in self.events if e.get("type") == "safety"]
        lines = [
            f"# SparkLearn Debug Report",
            "",
            f"- session_id: `{self.session_id}`",
            f"- run_dir: `{self.run_dir}`",
            f"- started_at: `{self.started_at.isoformat()}`",
            f"- events: `{len(self.events)}`",
            f"- route: `{ ' -> '.join(route) if route else 'none' }`",
            f"- resources: `{len(self.resources)}`",
            f"- errors: `{len(errors)}`",
            f"- safety_warnings: `{len(safety)}`",
            f"- prompt_calls: `{len(self.prompt_calls)}`",
            f"- retrievals: `{len(self.retrievals)}`",
            f"- degraded_events: `{len(self.degraded_events)}`",
            f"- grounding_checks: `{len(self.grounding_checks)}`",
            "",
            "## Resources",
            "",
        ]
        if self.resources:
            for r in self.resources:
                item = _resource_summary(r)
                lines.append(
                    f"- `{item['kind']}` `{item['id']}`: {item['title']} "
                    f"(kp={item['kp']}, citations={item['citation_count']})"
                )
        else:
            lines.append("- none")

        lines.extend(["", "## Agent Status", ""])
        for agent, status in self._ordered_agent_status().items():
            lines.append(
                f"- `{agent}`: {status.get('status', 'unknown')} "
                f"({status.get('duration_ms', 'n/a')} ms) "
                f"{_preview(status.get('summary') or status.get('detail'), 120)}"
            )

        if errors:
            lines.extend(["", "## Errors", ""])
            for e in errors:
                lines.append(f"- event {e.get('i')}: {_preview(e.get('detail'), 200)}")

        lines.extend([
            "",
            "## Key Files",
            "",
            "- `summary.json`: machine-readable run summary",
            "- `debug_report.md`: this human-readable report",
            "- `timeline.json`: ordered event timeline",
            "- `events.jsonl`: raw SSE event stream",
            "- `quality.evidence.json`: prompt, retrieval, fallback and grounding evidence",
            "- `state.summary.json`: compact final state summary",
            "- `final_state.json`: full final LangGraph state",
            "- `resources/`: one JSON file per generated resource",
            "- `agent_end/`: raw agent_end events",
            "- `agent_outputs/`: non-empty agent output payloads",
        ])
        return "\n".join(lines) + "\n"

"""Deterministic misconception diagnosis and bounded remediation routing.

The model may later explain a diagnosis, but it never decides correctness,
the prerequisite gap, or the next learning action. Those decisions come from
stored quiz evidence, the learner profile, and the curated knowledge graph.
"""
from __future__ import annotations

from typing import Any

from .knowledge_graph import canonical_kp_id, kp_name, prerequisites

READY_MASTERY = 0.6
MAX_CYCLE_ATTEMPTS = 3

_TYPE_FALLBACKS = {
    "single": "选项辨析错误",
    "judge": "条件看漏了",
    "fill": "概念没记牢",
    "complexity": "计算或推导失误",
    "design": "步骤顺序混乱",
}


def _phase(answers: list[dict[str, Any]]) -> str:
    for answer in answers:
        value = str(answer.get("evidence_phase") or "").strip()
        if value:
            return value
    return "initial"


def _priority(answer: dict[str, Any]) -> tuple[int, int, int, int]:
    return (
        int(answer.get("calibration_signal") == "confident_wrong"),
        int(bool(answer.get("revealed"))),
        int(bool(answer.get("hint_used"))),
        int(answer.get("difficulty") or 0),
    )


def _misconception(answer: dict[str, Any]) -> str:
    explicit = str(answer.get("misconception") or "").strip()
    if explicit:
        return explicit
    tags = answer.get("error_tags") if isinstance(answer.get("error_tags"), list) else []
    for tag in tags:
        text = str(tag or "").strip()
        if text:
            return text
    return _TYPE_FALLBACKS.get(str(answer.get("type") or ""), "概念还不稳定")


def _prerequisite_gap(kp: str, mastery: dict[str, Any]) -> tuple[str | None, float | None]:
    candidates = []
    for prerequisite in prerequisites(kp):
        try:
            value = float(mastery.get(prerequisite, 0.3))
        except (TypeError, ValueError):
            value = 0.3
        if value < READY_MASTERY:
            candidates.append((value, prerequisite))
    if not candidates:
        return None, None
    value, prerequisite = min(candidates)
    return prerequisite, round(value, 3)


def _action_for(phase: str, gap: str | None) -> str:
    if phase == "spaced_review":
        return "review_again"
    if phase == "retest":
        return "schedule_review"
    return "remediate" if gap else "reteach"


def diagnose_answers(
    answers: list[dict[str, Any]],
    profile: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return one explainable, bounded next action for an assessment round."""
    phase = _phase(answers)
    failed = [
        answer for answer in answers
        if not bool(answer.get("mastery_correct", answer.get("correct")))
    ]
    if not failed:
        return {
            "status": "clear",
            "action": "advance",
            "phase": phase,
            "attempt": 2 if phase == "retest" else 1,
            "max_attempts": MAX_CYCLE_ATTEMPTS,
            "blocked_kp": None,
            "blocked_name": "",
            "prerequisite_gap": None,
            "prerequisite_name": "",
            "remediation_kp": None,
            "remediation_name": "",
            "misconception": "",
            "severity": "none",
            "evidence": ["本轮所有题目均形成了独立掌握证据"],
            "reason": "当前概念已经形成独立掌握证据，可以沿学习路径继续。",
        }

    focus = max(failed, key=_priority)
    blocked_kp = canonical_kp_id(str(focus.get("kp") or ""))
    if not blocked_kp:
        return {
            "status": "needed",
            "action": "schedule_review",
            "phase": phase,
            "attempt": 2 if phase == "retest" else 1,
            "max_attempts": MAX_CYCLE_ATTEMPTS,
            "blocked_kp": None,
            "blocked_name": "",
            "prerequisite_gap": None,
            "prerequisite_name": "",
            "remediation_kp": None,
            "remediation_name": "",
            "misconception": _misconception(focus),
            "severity": "medium",
            "evidence": ["题目没有可验证的课程知识点标识"],
            "reason": "暂时无法安全生成补救课，已安排后续复习。",
        }

    mastery = (profile or {}).get("knowledge_mastery") or {}
    gap, gap_mastery = _prerequisite_gap(blocked_kp, mastery)
    action = _action_for(phase, gap)
    remediation_kp = gap or blocked_kp
    signal = str(focus.get("calibration_signal") or "")
    severity = "high" if signal == "confident_wrong" or gap else "medium"
    evidence = [f"「{kp_name(blocked_kp)}」本轮没有形成独立掌握证据"]
    if focus.get("revealed"):
        evidence.append("本题使用了答案揭晓，不能计入独立掌握")
    elif focus.get("hint_used"):
        evidence.append("本题使用了提示，需要无提示复测")
    if signal == "confident_wrong":
        evidence.append("作答时很有把握但结果错误，优先排查稳定误区")
    elif signal == "uncertain_correct":
        evidence.append("答案正确但把握不足，需要低成本巩固")
    if gap:
        evidence.append(f"前置知识「{kp_name(gap)}」掌握度仅 {gap_mastery:.0%}")

    if action == "remediate":
        reason = f"先补「{kp_name(gap or blocked_kp)}」，再回到「{kp_name(blocked_kp)}」完成无提示复测。"
    elif action == "reteach":
        reason = f"没有发现更早的先修缺口，换一种方式重讲「{kp_name(blocked_kp)}」后复测。"
    elif action == "schedule_review":
        reason = "补救后的无提示复测仍未通过，停止继续循环并进入间隔复习。"
    else:
        reason = "本次间隔复习仍未通过，复习计划已回到短间隔。"

    return {
        "status": "needed",
        "action": action,
        "phase": phase,
        "attempt": 2 if phase == "retest" else 3 if phase == "spaced_review" else 1,
        "max_attempts": MAX_CYCLE_ATTEMPTS,
        "blocked_kp": blocked_kp,
        "blocked_name": kp_name(blocked_kp),
        "prerequisite_gap": gap,
        "prerequisite_name": kp_name(gap) if gap else "",
        "prerequisite_mastery": gap_mastery,
        "remediation_kp": remediation_kp,
        "remediation_name": kp_name(remediation_kp),
        "misconception": _misconception(focus),
        "severity": severity,
        "evidence": evidence,
        "reason": reason,
    }


def apply_diagnosis_to_path(path: dict[str, Any], diagnosis: dict[str, Any]) -> dict[str, Any]:
    """Attach the current learning-cycle decision to a freshly computed path."""
    output = dict(path or {})
    output["remediation"] = diagnosis
    if diagnosis.get("action") in {"remediate", "reteach"} and diagnosis.get("remediation_kp"):
        output["next_kp"] = diagnosis["remediation_kp"]
        output["generated_by"] = "diagnostic-remediation"
    return output

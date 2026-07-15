"""Deterministic confidence calibration for learning evidence."""
from __future__ import annotations

from typing import Any

from .profile_service import get_profile, merge_profile

CONFIDENCE_PROBABILITY = {
    "guess": 0.20,
    "unsure": 0.50,
    "confident": 0.90,
}


def normalize_confidence(value: Any) -> str:
    confidence = str(value or "").strip().lower()
    return confidence if confidence in CONFIDENCE_PROBABILITY else ""


def calibration_signal(confidence: Any, correct: bool) -> str:
    level = normalize_confidence(confidence)
    if not level:
        return "unrecorded"
    if level == "confident":
        return "confident_correct" if correct else "confident_wrong"
    if correct:
        return "uncertain_correct"
    return "uncertainty_matched" if level == "guess" else "unsure_wrong"


def summarize_calibration(answers: list[dict[str, Any]]) -> dict[str, Any]:
    """Compare pre-feedback confidence with raw grading results."""
    scores: list[float] = []
    signals: dict[str, int] = {}
    for answer in answers:
        confidence = normalize_confidence(answer.get("confidence"))
        if (not confidence or not str(answer.get("answer") or "").strip()
                or str(answer.get("support_level") or "independent") != "independent"):
            continue
        correct = bool(answer.get("correct"))
        probability = CONFIDENCE_PROBABILITY[confidence]
        scores.append(1.0 - abs(probability - float(correct)))
        signal = calibration_signal(confidence, correct)
        signals[signal] = signals.get(signal, 0) + 1

    recorded = len(scores)
    return {
        "recorded": recorded,
        "score": round(sum(scores) / recorded, 3) if recorded else None,
        "confident_wrong": signals.get("confident_wrong", 0),
        "uncertain_correct": signals.get("uncertain_correct", 0),
        "confident_correct": signals.get("confident_correct", 0),
        "uncertainty_matched": signals.get("uncertainty_matched", 0),
    }


def apply_metacognition_calibration(
    user_id: str,
    answers: list[dict[str, Any]],
    profile: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Smooth one evidence round into the profile metacognition dimension."""
    current = profile or get_profile(user_id)
    summary = summarize_calibration(answers)
    before = min(1.0, max(0.0, float(current.get("metacognition", 0.5))))
    summary["metacognition_before"] = round(before, 4)
    if not summary["recorded"] or summary["score"] is None:
        summary["metacognition_after"] = round(before, 4)
        return summary, current

    after = round(before * 0.75 + float(summary["score"]) * 0.25, 4)
    updated = merge_profile(user_id, {"metacognition": after})
    summary["metacognition_after"] = after
    return summary, updated

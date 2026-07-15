from app.services.diagnosis_service import apply_diagnosis_to_path, diagnose_answers


def _answer(**overrides):
    value = {
        "question_id": "q1",
        "kp": "heap",
        "correct": False,
        "mastery_correct": False,
        "type": "single",
        "difficulty": 3,
        "error_tags": ["父子关系判断错误"],
        "support_level": "independent",
        "evidence_phase": "initial",
        "calibration_signal": "confident_wrong",
    }
    value.update(overrides)
    return value


def test_diagnosis_inserts_low_mastery_prerequisite():
    diagnosis = diagnose_answers(
        [_answer()],
        {"knowledge_mastery": {"binary_tree": 0.42, "heap": 0.3}},
    )

    assert diagnosis["action"] == "remediate"
    assert diagnosis["blocked_kp"] == "heap"
    assert diagnosis["prerequisite_gap"] == "binary_tree"
    assert diagnosis["remediation_kp"] == "binary_tree"
    assert diagnosis["severity"] == "high"
    assert any("很有把握" in item for item in diagnosis["evidence"])


def test_diagnosis_reteaches_when_prerequisites_are_ready():
    diagnosis = diagnose_answers(
        [_answer(calibration_signal="uncertain_wrong")],
        {"knowledge_mastery": {"binary_tree": 0.75, "heap": 0.35}},
    )

    assert diagnosis["action"] == "reteach"
    assert diagnosis["prerequisite_gap"] is None
    assert diagnosis["remediation_kp"] == "heap"


def test_retest_failure_stops_the_immediate_loop():
    diagnosis = diagnose_answers(
        [_answer(evidence_phase="retest", calibration_signal="uncertain_wrong")],
        {"knowledge_mastery": {"binary_tree": 0.4, "heap": 0.3}},
    )

    assert diagnosis["action"] == "schedule_review"
    assert diagnosis["attempt"] == 2
    assert "停止继续循环" in diagnosis["reason"]


def test_success_advances_and_does_not_override_path():
    diagnosis = diagnose_answers(
        [_answer(correct=True, mastery_correct=True, calibration_signal="confident_correct")],
        {"knowledge_mastery": {"heap": 0.8}},
    )
    path = apply_diagnosis_to_path({"next_kp": "sorting_adv", "generated_by": "rule"}, diagnosis)

    assert diagnosis["action"] == "advance"
    assert path["next_kp"] == "sorting_adv"
    assert path["generated_by"] == "rule"
    assert path["remediation"]["status"] == "clear"

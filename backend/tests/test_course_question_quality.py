import asyncio
import copy
import json

import pytest

from app.services import course_learning_service as service


def course():
    return {"title": "生态学", "bank": [{"id": "topic_1-1", "type": "multiple",
        "stem": "哪些过程释放二氧化碳？", "options": ["呼吸", "分解", "光合作用", "燃烧"],
        "answer": ["A", "B"], "explain": "燃烧非资料内容，不选。"}]}


def result(truth, *, supported=True):
    return {"questions": [{"id": "topic_1-1", "conditions_sufficient": True, "supported": supported, "scope_preserved": True,
        "unstated_assumptions": [], "redundancy": [], "evidence": [],
        "options": [{"label": label, "correct": correct, "reason": "独立判断题干目标与条件"}
            for label, correct in zip("ABCD", truth)]}]}


def install(monkeypatch, output):
    calls = []
    async def complete(prompt, **kwargs):
        calls.append(prompt)
        assert kwargs["allow_mock_fallback"] is False
        if "最终题目与逐项理由：" in prompt:
            return json.dumps({"questions": [{"id": row["id"], "issues": [], "options": [
                {"label": o["label"], "accepted": True, "issues": []} for o in row["options"]]} for row in output["questions"]]})
        return json.dumps(output, ensure_ascii=False)
    monkeypatch.setattr(service, "llm_complete", complete)
    return calls


def test_true_but_unmentioned_option_cannot_be_graded_wrong(monkeypatch):
    calls = install(monkeypatch, result([True, True, False, True], supported=False))
    with pytest.raises(service.DraftValidationError) as caught:
        asyncio.run(service.review_course_questions(course(), []))
    assert caught.value.code == "answer_review"
    assert '"correct": true' in caught.value.repair_issue
    assert "燃烧非资料内容，不选" not in calls[0]  # reviewer never sees generated key/explanation
    assert '"answer"' not in calls[0]


def test_key_mismatch_is_rejected_even_if_supported(monkeypatch):
    install(monkeypatch, result([True, True, False, True]))
    with pytest.raises(service.DraftValidationError, match="独立复核"):
        asyncio.run(service.review_course_questions(course(), []))


@pytest.mark.parametrize("output", [
    {"questions": []},
    result([True, True, False, None]),
    result([True, True]),
])
def test_incomplete_or_uncertain_review_cannot_pass(monkeypatch, output):
    install(monkeypatch, output)
    with pytest.raises(service.DraftValidationError):
        asyncio.run(service.review_course_questions(course(), []))


def test_agreed_key_gets_model_review_label_only(monkeypatch):
    install(monkeypatch, result([True, True, False, False]))
    value = course()
    asyncio.run(service.review_course_questions(value, []))
    assert value["quality_review"] == {"verification": "model_review", "reviewed_questions": 1}
    assert "燃烧非资料内容" not in value["bank"][0]["explain"]
    assert value["bank"][0]["explain"].startswith("A（应选）：独立判断")
    assert "D（不选）：独立判断" in value["bank"][0]["explain"]


def test_semantic_rejection_reaches_bounded_repair(monkeypatch):
    from types import SimpleNamespace
    draft = {"topics": [{"name": "物质循环", "objective": "比较碳的流动", "lesson": "元素在环境和生物之间流动。",
        "questions": [{"stem": f"条件{i}是否成立？", "options": ["甲", "乙", "丙"],
            "type": "multiple" if i == 2 else "single", "answer": ["A", "B"] if i == 2 else "A",
            "explain": "依据题面所给条件逐项判断。"} for i in range(3)]}]}
    prompts, reviews = [], []
    async def complete(prompt, **kwargs):
        prompts.append(prompt)
        return json.dumps(draft, ensure_ascii=False)
    async def check(*args):
        reviews.append(args)
        if len(reviews) == 1:
            raise service.DraftValidationError("answer_review", "未通过", repair_issue="第 2 题 D 选项不能因为资料未提及就判错")
    monkeypatch.setattr(service, "llm_complete", complete)
    monkeypatch.setattr(service, "review_course_questions", check)
    asyncio.run(service.generate_valid_course(SimpleNamespace(prompt="原要求", system="教学"), "生态学", []))
    assert len(prompts) == len(reviews) == 2
    assert "D 选项不能因为资料未提及就判错" in prompts[1]


def test_support_flag_cannot_override_an_explicit_source_gap(monkeypatch):
    output = result([True, True, False, False])
    output["questions"][0]["options"][-1]["reason"] = "资料未提，且不直接释放二氧化碳。"
    install(monkeypatch, output)
    with pytest.raises(service.DraftValidationError) as caught:
        asyncio.run(service.review_course_questions(course(), [{"evidence_id": "s1c1", "text": "呼吸和分解释放二氧化碳。"}]))
    assert caught.value.code == "answer_review"
    assert "必须更换无法据资料判定的选项" in caught.value.repair_issue


@pytest.mark.parametrize("damage", ["missing", "wrong_id", "unknown"])
def test_partial_mode_does_not_salvage_incomplete_reviews(monkeypatch, damage):
    output = result([True, True, False, False])
    if damage == "missing":
        output["questions"] = []
    elif damage == "wrong_id":
        output["questions"][0]["id"] = "other"
    else:
        output["questions"][0]["options"][0]["correct"] = None
    install(monkeypatch, output)
    with pytest.raises(service.DraftValidationError) as caught:
        asyncio.run(service.review_course_questions(course(), [], True))
    assert caught.value.code == "review_incomplete"


def test_last_attempt_still_rejects_cross_topic_duplicate_questions():
    from copy import deepcopy
    topic = {"name": "甲", "objective": "条件判断", "lesson": "根据题目条件判断。", "questions": [
        {"stem": f"条件{i}", "type": "multiple" if i == 2 else "single", "options": ["甲", "乙", "丙"],
         "answer": ["A", "B"] if i == 2 else "A", "explain": "根据给定条件分别判断每个选项。"} for i in range(3)]}
    duplicate = {**deepcopy(topic), "name": "乙"}
    saved = service.validate_final_topics({"topics": [topic, duplicate]}, "条件", [])
    assert len(saved["bank"]) == 3 and saved["omitted_topic_count"] == 1
    assert len({q["stem"] for q in saved["bank"]}) == 3


@pytest.mark.parametrize("field,value", [("scope_preserved", False), ("unstated_assumptions", ["摄食必须是活物"]),
    ("redundancy", ["B与D同义"]), ("evidence", [{"id": "unowned", "quote": "伪造原句"}])])
def test_review_flags_and_invalid_evidence_cannot_pass(monkeypatch, field, value):
    output = result([True, True, False, False])
    output["questions"][0][field] = value
    install(monkeypatch, output)
    with pytest.raises(service.DraftValidationError):
        asyncio.run(service.review_course_questions(course(), []))


def test_evidence_statement_is_bound_to_question_scope(monkeypatch):
    chunks = [{"evidence_id": "s1c1", "text": "呼吸与分解释放二氧化碳。"},
        {"evidence_id": "s2c1", "text": "燃烧也释放二氧化碳。"}]
    value = course()
    value["bank"][0]["evidence_ids"] = ["s1c1"]
    output = result([True, True, False, False])
    output["questions"][0]["evidence"] = ["s2c1:1"]
    install(monkeypatch, output)
    with pytest.raises(service.DraftValidationError):
        asyncio.run(service.review_course_questions(value, chunks))


@pytest.mark.parametrize("damage", ["scope", "missing", "label", "unknown", "contradiction"])
def test_final_explanation_audit_is_required_after_solver_approval(monkeypatch, damage):
    value = course()
    value["bank"][0]["evidence_ids"] = ["s1c1"]
    chunks = [{"evidence_id": "s1c1", "text": "绿色植物通过光合作用获得能量。某些生产者有其他能量来源。"}]
    solved = result([True, True, False, False])
    solved["questions"][0]["evidence"] = ["s1c1:1"]
    solved["questions"][0]["options"][0]["reason"] = "生产者只能通过光合作用获得能量"
    checked = {"questions": [{"id": "topic_1-1", "issues": [], "options": [
        {"label": label, "accepted": True, "issues": []} for label in "ABCD"]}]}
    option = checked["questions"][0]["options"][0]
    if damage == "scope":
        option.update(accepted=False, issues=["把绿色植物的方式扩大为全部生产者且增加只能"])
    elif damage == "missing":
        checked["questions"] = []
    elif damage == "label":
        option["label"] = "X"
    elif damage == "unknown":
        option["accepted"] = None
    else:
        option["issues"] = ["有未解决的反例"]
    calls = []
    async def complete(prompt, **kwargs):
        calls.append(prompt)
        assert kwargs["allow_mock_fallback"] is False
        return json.dumps(solved if len(calls) == 1 else checked, ensure_ascii=False)
    monkeypatch.setattr(service, "llm_complete", complete)
    with pytest.raises(service.DraftValidationError) as caught:
        asyncio.run(service.review_course_questions(value, chunks))
    assert len(calls) == 2
    assert "生产者只能通过光合作用获得能量" in calls[1]
    assert "某些生产者有其他能量来源" in calls[1]  # full allowed source, not solver-selected sentences
    assert '"scope_preserved"' not in calls[1]
    if damage == "scope":
        assert "生产者只能通过光合作用获得能量" in caught.value.repair_issue


def test_all_multiple_draft_rejected_without_changing_answers():
    topic = {"name": "角色", "objective": "区分角色", "lesson": "按获取有机物方式区分。", "questions": [
        {"stem": f"角色{i}", "type": "multiple", "options": ["甲", "乙", "丙"], "answer": ["A", "B"],
        "explain": "按题目提供的条件分别作出判断。"} for i in range(3)]}
    original = copy.deepcopy(topic)
    with pytest.raises(service.DraftValidationError) as caught:
        service.validate_draft({"topics": [topic]}, "角色", [])
    assert caught.value.code == "question_mix"
    assert topic == original


def test_preparation_timing_does_not_store_prompts_or_answers(monkeypatch):
    install(monkeypatch, result([True, True, False, False]))
    progress = {"stage": "", "attempt": 1, "stages": []}
    asyncio.run(service.review_course_questions(course(), [], False, progress))
    assert [stage["stage"] for stage in progress["stages"]] == ["solve", "final_review"]
    assert all(set(stage) == {"stage", "attempt", "elapsed_ms"} for stage in progress["stages"])
    assert all(stage["elapsed_ms"] >= 0 for stage in progress["stages"])


@pytest.mark.parametrize("reason", ["燃烧不是生物群落摄取碳的途径，也不在资料中。", "寄生者不是资料中的分类，且腐生不是寄生。"])
def test_real_source_gap_wordings_cannot_be_approved(monkeypatch, reason):
    output = result([True, True, False, False])
    output["questions"][0]["options"][-1]["reason"] = reason
    install(monkeypatch, output)
    with pytest.raises(service.DraftValidationError) as caught:
        asyncio.run(service.review_course_questions(course(), [{"evidence_id": "s1c1", "text": "呼吸释放二氧化碳。"}]))
    assert "必须更换无法据资料判定的选项" in caught.value.repair_issue

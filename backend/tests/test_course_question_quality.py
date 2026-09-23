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
    return {"questions": [{"id": "topic_1-1", "conditions_sufficient": True, "supported": supported,
        "options": [{"label": label, "correct": correct, "reason": "独立判断题干目标与条件"}
            for label, correct in zip("ABCD", truth)]}]}


def install(monkeypatch, output):
    calls = []
    async def complete(prompt, **kwargs):
        calls.append(prompt)
        assert kwargs["allow_mock_fallback"] is False
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

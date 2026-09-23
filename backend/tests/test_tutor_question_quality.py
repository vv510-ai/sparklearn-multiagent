import asyncio
import json

from app.services import tutor_question_quality as quality

AMBIGUOUS = "递归必须逐步接近终止条件。\n\n检查（单选）：下面哪种写法最可能无限递归？\nA. n 从 3 递减，到 0 停止\nB. n 一直保持 3\nC. 没有终止条件\nD. n 从 3 递减，到 1 停止"


def review(monkeypatch, truth, conditions=True):
    async def complete(*args, **kwargs):
        return json.dumps({"conditions_sufficient": conditions, "options": [
            {"label": chr(65+i), "correct": correct, "reason": "逐项代入给定初值和终止条件"} for i, correct in enumerate(truth)]})
    monkeypatch.setattr(quality, "llm_complete", complete)


def test_single_choice_with_two_correct_options_becomes_open_question(monkeypatch):
    review(monkeypatch, [False, True, True, False])
    answer, status = asyncio.run(quality.check_question(AMBIGUOUS, "递归资料"))
    assert answer.startswith("递归必须逐步接近终止条件。")
    assert "A." not in answer and "简答检查" in answer and not status["accepted"]


def test_explicit_multiple_choice_survives_but_missing_conditions_do_not(monkeypatch):
    question = AMBIGUOUS.replace("单选", "多选")
    review(monkeypatch, [False, True, True, False])
    assert asyncio.run(quality.check_question(question, ""))[0] == question
    review(monkeypatch, [False, True, False, False], conditions=False)
    assert not asyncio.run(quality.check_question(AMBIGUOUS, ""))[1]["accepted"]


def test_no_review_for_normal_explanation_or_code(monkeypatch):
    async def forbidden(*args, **kwargs):
        raise AssertionError("should not call")
    monkeypatch.setattr(quality, "llm_complete", forbidden)
    for answer in ["递归每次把问题变小。", "示例？\n```text\nA. 左边\nB. 右边\n```"]:
        assert asyncio.run(quality.check_question(answer, "")) == (answer, None)


def test_review_failure_preserves_lesson_without_guessing(monkeypatch):
    async def unavailable(*args, **kwargs):
        raise TimeoutError()
    monkeypatch.setattr(quality, "llm_complete", unavailable)
    answer, status = asyncio.run(quality.check_question(AMBIGUOUS, ""))
    assert "递归必须" in answer and "A." not in answer
    assert status["reason"] == "review_unavailable"


def test_question_heading_keeps_separate_premises_and_multiple_type(monkeypatch):
    question = "递归要接近停止条件。\n\n## 多选理解检查\n\n假设初始 n=3，n 为整数。\n\n哪些方案不能终止？\nA. n 不变，n=0 停止\nB. n 增加，n=0 停止\nC. n 递减，n=0 停止"
    prompts = []
    async def complete(prompt, **kwargs):
        prompts.append(prompt)
        return json.dumps({"conditions_sufficient": True, "options": [
            {"label": label, "correct": correct, "reason": "代入 n=3 检查参数能否到达零"}
            for label, correct in zip("ABC", [True, True, False])]})
    monkeypatch.setattr(quality, "llm_complete", complete)
    answer, status = asyncio.run(quality.check_question(question, ""))
    assert answer == question and status["accepted"] and status["question_type"] == "multiple"
    assert "假设初始 n=3" in prompts[0]
    review(monkeypatch, [True, False, False])
    rejected, status = asyncio.run(quality.check_question(question, ""))
    assert "## 多选理解检查" not in rejected and "简答检查" in rejected

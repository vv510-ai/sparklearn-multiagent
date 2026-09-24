import asyncio
import json

import pytest

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


@pytest.mark.parametrize("heading", ["## 多选理解检查", "**多选理解检查**"])
def test_question_heading_keeps_separate_premises_and_multiple_type(monkeypatch, heading):
    question = "递归要接近停止条件。\n\n## 多选理解检查\n\n假设初始 n=3，n 为整数。\n\n哪些方案不能终止？\nA. n 不变，n=0 停止\nB. n 增加，n=0 停止\nC. n 递减，n=0 停止"
    question = question.replace("## 多选理解检查", heading)
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
    assert heading not in rejected and "简答检查" in rejected


def test_review_sees_initial_conditions_even_without_a_formatted_heading(monkeypatch):
    answer = "先约定初始 n=3，且 n 是整数。\n\n请判断哪种不能终止？\nA. n 每次减一，到0停止\nB. n 每次加一，到0停止"
    prompts = []
    async def complete(prompt, **kwargs):
        prompts.append(prompt)
        return json.dumps({"conditions_sufficient": True, "options": [
            {"label": "A", "correct": False, "reason": "3到0能停止"},
            {"label": "B", "correct": True, "reason": "3不断增加不能到0"}]})
    monkeypatch.setattr(quality, "llm_complete", complete)
    checked, status = asyncio.run(quality.check_question(answer, ""))
    assert "初始 n=3" in prompts[0]
    assert status["accepted"] and checked == answer


REAL_BAD = """递归要到达终止条件。

**单选题**：假设初始参数 $n = 3$，且 $n$ 始终为整数。下列哪种方案不能保证递归终止？
A. 停止条件：$n = 0$；参数变化：每次调用变为 $n - 1$
B. 停止条件：$n = 0$；参数变化：每次调用变为 $n - 2$
C. 停止条件：$n = 0$；参数变化：每次调用变为 $n + 1$
D. 停止条件：$n <= 0$；参数变化：每次调用变为 $n - 3$
"""


def test_actual_odd_step_bad_question_cannot_pass_a_mistaken_model(monkeypatch):
    review(monkeypatch, [False, False, True, False])  # the observed bad single-key approval
    answer, status = asyncio.run(quality.check_question(REAL_BAD, "递归讲义"))
    assert quality.linear_recursion_choices(quality.terminal_question(REAL_BAD)[1]) == [False, True, True, False]
    assert not status["accepted"] and status["verification"] == "deterministic_check"
    assert "简答检查" in answer and "A." not in answer


def test_linear_positive_control_and_already_stopped(monkeypatch):
    good = REAL_BAD.replace("每次调用变为 $n - 2$", "每次调用变为 $n - 1$")
    review(monkeypatch, [False, False, True, False])
    assert asyncio.run(quality.check_question(good, ""))[1]["accepted"]
    assert quality._linear_terminates(3, "=", 3, -1)
    assert quality.linear_recursion_choices(good.replace("每次调用变为 $n - 1$", "每次调用变为 $n / 2$")) is None


def test_linear_proof_matches_small_integer_execution():
    import operator
    checks = {"=": operator.eq, "<": operator.lt, "<=": operator.le, ">": operator.gt, ">=": operator.ge}
    for initial in range(-5, 6):
        for stop in range(-5, 6):
            for delta in range(-3, 4):
                for op, check in checks.items():
                    observed = any(check(initial + k*delta, stop) for k in range(40))
                    assert quality._linear_terminates(initial, op, stop, delta) == observed


@pytest.mark.parametrize("initial", ["3.5", "3 * 2", "3或4"])
def test_linear_checker_does_not_guess_an_unparsed_initial_value(initial):
    assert quality.linear_recursion_choices(REAL_BAD.replace("$n = 3$", "$n = " + initial + "$")) is None


@pytest.mark.parametrize("division", ["n/2", "n / 2", "n÷2", "n/10"])
def test_live_integer_division_ambiguity_cannot_pass_model_approval(monkeypatch, division):
    question = REAL_BAD.replace("$n - 2$", division)
    review(monkeypatch, [False, False, True, False])
    answer, status = asyncio.run(quality.check_question(question, ""))
    assert not status["accepted"] and status["reason"] == "division_rule_missing"
    assert "简答检查" in answer and "A." not in answer


@pytest.mark.parametrize("division", ["n//2", "floor(n/2)", "ceil(n/2)", "n/2（向下取整）"])
def test_explicit_division_semantics_still_go_through_model_review(monkeypatch, division):
    question = REAL_BAD.replace("$n - 2$", division)
    assert not quality.ambiguous_integer_division(question)
    review(monkeypatch, [False, False, True, False], conditions=False)
    _, status = asyncio.run(quality.check_question(question, ""))
    assert not status["accepted"] and status["verification"] == "model_review"


def test_division_guard_does_not_infer_integer_domain_from_initial_value():
    question = REAL_BAD.replace("$n - 2$", "n/2").replace("且 $n$ 始终为整数。", "")
    assert not quality.ambiguous_integer_division(question)

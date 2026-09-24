import copy
from collections import Counter

import pytest

from app.services.course_question_contract import balance_options, position_dependent


def bank():
    return {"bank": [{"id": f"topic_{i}-{j}", "kp": f"topic_{i}", "stem": f"问题{i}-{j}",
        "options": ["正确甲", "正确乙" if j == 2 else "错误乙", "错误丙", "错误丁"],
        "type": "multiple" if j == 2 else "single", "answer": ["A", "B"] if j == 2 else "A", "explain": "初稿"}
        for i in range(3) for j in range(3)]}


def test_reorder_preserves_semantics_and_is_stable_for_same_draft():
    original = bank()
    value, other = copy.deepcopy(original), copy.deepcopy(original)
    balance_options(value)
    balance_options(other)
    assert value == other
    assert original == bank()
    assert {q["id"] for q in value["bank"]} == {q["id"] for q in original["bank"]}
    for q in value["bank"]:
        answers = q["answer"] if isinstance(q["answer"], list) else [q["answer"]]
        assert {q["options"]["ABCD".index(k)] for k in answers} == ({"正确甲", "正确乙"} if q["type"] == "multiple" else {"正确甲"})
    counts = Counter(q["answer"] for q in value["bank"] if q["type"] == "single")
    assert max(counts.values()) - min(counts.values()) <= 1
    for kp in {q["kp"] for q in value["bank"]}:
        retained = [q for q in value["bank"] if q["kp"] == kp and q["type"] == "single"]
        assert len({q["answer"] for q in retained}) == 2


@pytest.mark.parametrize("text", ["以上都正确", "A 和 B", "选项C成立", "前两项"])
def test_position_references_are_not_reordered(text):
    assert position_dependent(text)


def test_math_variables_are_not_option_references():
    for text in ("矩阵 A 的秩为 2", "已知矩阵 A 和 B，求 AB", "集合 A 与 B 的交集"):
        assert not position_dependent(text)

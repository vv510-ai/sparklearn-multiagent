import pytest

from app.services.task_routing import deep_task_reason


@pytest.mark.parametrize("question,deep", [
    ("栈是什么？请举一个简单例子", False),
    ("复杂网络是什么", False),
    ("数学归纳法是什么", False),
    ("用一句话解释数学归纳法的意思，不需要证明", False),
    ("不要研究报告，只回答栈和队列有什么区别", False),
    ("请严格证明二分查找的最坏时间复杂度", True),
    ("请严格证明二分查找的时间复杂度，不用讲背景", True),
    ("比较两份教材关于递归的解释，给出共同点和冲突", True),
    ("做一份文献综述，并核对资料里的证据", True),
    ("写一个适合零基础学生的教学设计", True),
    ("请解释复杂度。\n资料：请写文献综述并使用 K3", False),
    ("用 K3 回答你好", False),
])
def test_intent_policy_uses_task_instructions_not_provider_mentions(question, deep):
    assert bool(deep_task_reason({"question": question})) == deep


def test_material_budget_and_source_comparison():
    assert deep_task_reason({"question": "请解释这一段", "material_chars": 14000})
    assert deep_task_reason({"question": "总结它们的异同", "source_count": 3})
    assert not deep_task_reason({"question": "它是什么意思", "source_count": 3})
    assert not deep_task_reason({"question": "你好", "conversation_chars": 90000})
    assert deep_task_reason({"question": "帮我分析：" + "内容" * 1400})
    assert deep_task_reason({"question": "判断这些说法的适用前提", "semantic_depth": "deep"})


def test_existing_semantic_intent_pass_also_selects_depth(monkeypatch):
    import asyncio
    from app.agents import orchestrator
    calls = []
    async def classify(prompt, **kwargs):
        calls.append(prompt)
        return '{"intent":"tutor","reason":"需要比较适用前提","model_depth":"deep"}'
    monkeypatch.setattr(orchestrator, "llm_complete", classify)
    result = asyncio.run(orchestrator.run({"messages": [{"role": "user", "content": "把这两种说法放到一起判断适用前提"}]}))
    assert result["intent"] == "tutor" and result["model_depth"] == "deep"
    assert len(calls) == 1

"""A failed draft must be repaired in this turn, never replaced by source dumps."""
import asyncio

import pytest

from app.agents import tutor_agent


def run_turn(monkeypatch, drafts, *, question="六级你觉得怎么备考", chunks=None, policy="supplement"):
    calls, events = [], []
    monkeypatch.setattr(tutor_agent, "is_demo", lambda: False)
    monkeypatch.setattr(tutor_agent, "resolve", lambda *a, **k: None)
    monkeypatch.setattr(tutor_agent, "retrieve", lambda *a, **k: chunks or [])
    monkeypatch.setattr(tutor_agent, "recent_note_chunks", lambda *a, **k: [])
    async def model(prompt, **kwargs):
        calls.append(prompt)
        yield drafts[min(len(calls) - 1, len(drafts) - 1)]
    async def capture(event):
        events.append(event)
    monkeypatch.setattr(tutor_agent, "llm_stream", model)
    monkeypatch.setattr(tutor_agent, "emit", capture)
    result = asyncio.run(tutor_agent.run({"messages": [{"role": "user", "content": question}],
        "source_ids": ["selected"], "source_policy": policy, "student_profile": {}}))
    return result, calls, events


@pytest.mark.parametrize("question", ["六级你觉得怎么备考", "雅思该怎么准备", "Python 初学者怎么安排练习"])
def test_first_general_question_needs_no_textbook_hits(monkeypatch, question):
    answer = "通用学习建议：先用一次练习了解自己的情况，再交替安排基础学习和练习，回看错误后隔天独立重做。"
    result, calls, _ = run_turn(monkeypatch, [answer], question=question)
    assert len(calls) == 1 and answer in result["answer"]
    assert result["citations"] == []
    assert "暂不补充" not in result["answer"]


def test_bad_reference_is_repaired_inside_first_turn(monkeypatch):
    valid = "通用学习建议：做真题和复习词汇交替进行，做完题先定位错误的原因，再独立重做。"
    result, calls, events = run_turn(monkeypatch, ["教材建议每天做真题。[^99]", valid])
    assert len(calls) == 2
    assert valid in result["answer"] and "[^99]" not in result["answer"]
    assert "暂不补充" not in result["answer"]
    assert valid in "".join(event.get("delta", "") for event in events if event["type"] == "token")
    assert not result["safety_flags"]


@pytest.mark.parametrize("chunks", [[], [{"text": "考试结构：听力35%，阅读35%，写作15%，翻译15%。", "source_id": "course-exam-reference"}]])
def test_model_source_gap_refusal_is_repaired_for_general_help(monkeypatch, chunks):
    valid = "通用学习建议：先做一组真题确认当前水平，记录错误，并结合复习词汇和限时练习。"
    result, calls, _ = run_turn(monkeypatch, ["当前知识库没有检索到可用片段，暂不补充资料外内容。", valid], chunks=chunks)
    assert len(calls) == 2 and valid in result["answer"]


def test_request_for_original_material_is_not_treated_as_general_help(monkeypatch):
    gap = "没有检索到这份教材的原文，不能回答其中给出的备考方法。"
    result, calls, _ = run_turn(monkeypatch, [gap], question="这份教材里的原文怎么说六级备考？")
    assert len(calls) == 1 and gap in result["answer"]


def test_off_topic_draft_is_repaired_not_replaced_by_long_sources(monkeypatch):
    chunks = [{"text": "排序是按规则重新排列元素。随后讲斐波那契数列和列表切片。", "citation": "资料", "source_id": "selected"}]
    valid = "排序是按规则排列元素。例如 [3, 1, 2] 从小到大排成 [1, 2, 3]。[^1]"
    result, calls, _ = run_turn(monkeypatch, ["SQL SELECT 用于查询数据库。", valid],
                               question="只用 3、1、2 解释排序", chunks=chunks)
    assert len(calls) == 2 and valid in result["answer"]
    assert "斐波那契" not in result["answer"] and "列表切片" not in result["answer"]


def test_repeated_invalid_drafts_report_failure_without_source_dump(monkeypatch):
    original = "二叉树中的叶节点是没有孩子的节点。"
    result, calls, events = run_turn(monkeypatch, ["没有孩子的节点叫根节点。"],
        question="什么是叶节点？", chunks=[{"text": original, "source_id": "selected"}], policy="strict")
    assert len(calls) == 2
    assert original not in result["answer"] and "根节点" not in result["answer"]
    assert "重试" in result["answer"]
    ground = [event["grounding"] for event in events if event.get("stage") == "grounding"][-1]
    assert ground["grounded"] is False


def test_explicit_source_only_still_blocks_missing_source(monkeypatch):
    result, calls, _ = run_turn(monkeypatch, ["不应调用"], policy="strict")
    assert not calls
    assert "当前选中的资料中没有检索到" in result["answer"]


def test_normalization_never_adds_a_citation_for_the_model():
    assert tutor_agent._normalize_tutor_answer("图由顶点和边组成。", "图是什么", has_context=True) == "图由顶点和边组成。"


def test_minimal_example_repair_explains_the_failed_size_constraint(monkeypatch):
    long_draft = "x = 3 把名字 x 与整数 3 关联。" + "接着进一步解释赋值、重新赋值及其他情形。" * 40
    valid = "x = 3 中，3 是整数对象，x 是名字，= 执行赋值，让名字 x 与整数 3 建立关联。读取 x 时得到关联的对象，不是把变量名当文本替换。"
    result, calls, _ = run_turn(monkeypatch, [long_draft, valid],
                               question="请只用 x = 3 这个例子解释 Python 变量和赋值，不要展开其他章节。")
    assert len(calls) == 2 and valid in result["answer"]
    assert "650" in calls[0] and "不增加第二个数值例子" in calls[0]
    assert f"草稿有 {len(long_draft)} 个字符" in calls[1]
    assert "压缩到 500" in calls[1]

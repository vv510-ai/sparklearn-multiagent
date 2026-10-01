"""Feedback 02: natural questions retain evidence, failures are not knowledge maps."""
import asyncio

from app.agents import doc_agent
from app.agents.eval_agent import _learner_summary
from app.prompt_templates import render_learning_prompt_call
from app.services.knowledge_graph import resolve_conversation_topic
from app.services.learning_scope import course_scope, selected_sources
from app.services.topic_scope import focus_chunks_on_topic, topic_terms
from tests.test_learning_spaces import learner, prepare  # noqa: F401


def test_natural_question_keeps_subject_evidence_without_unrelated_chunks():
    assert topic_terms("选词有没有记忆点") == ["选词"]
    chunks = [{"text": "选词先判断词性，再检查搭配与上下文。"},
              {"text": "写作先明确论点，再给出支持理由。"}]
    assert focus_chunks_on_topic(chunks, "custom_topic", "选词有没有记忆点") == chunks[:1]
    assert focus_chunks_on_topic(chunks, "custom_topic", "量子纠缠有没有例子") == []


def test_one_page_prompt_receives_current_dialog_but_keeps_source_boundary():
    dialog = "学习者：选词有没有记忆点\n小知：记成词性、搭配、语境三步。"
    call = render_learning_prompt_call("one_page", topic="选词", goal="整理刚才讨论的内容",
        persona="初学者", context="[1] 选词先判断词性，再检查搭配与上下文。", conversation=dialog)
    assert dialog in call.prompt
    assert "只能来自“参考资料”" in call.prompt


def test_cet6_one_page_requires_actual_material_instead_of_old_original_guide(learner, monkeypatch):
    client, user = learner
    book, _, _ = prepare(client, user, "cet6", "大学英语六级")
    calls = []

    async def model(prompt, **kwargs):
        calls.append(prompt)
        return "# 选词的记忆点\n\n选词先判断词性，再检查搭配与上下文。[^1]"

    async def grounded(*args, **kwargs):
        return {"grounded": True, "unsupported": [], "verdict": "test"}

    monkeypatch.setattr(doc_agent, "llm_complete", model)
    monkeypatch.setattr(doc_agent, "grounding_check", grounded)
    monkeypatch.setattr(doc_agent, "is_demo", lambda: False)
    with course_scope(user, book["id"]):
        kp, name, custom = resolve_conversation_topic("选词有没有记忆点")
        out = asyncio.run(doc_agent._gen_one("doc", kp, {}, topic_name=name, custom_topic=custom,
            source_ids=selected_sources([]), goal="整理刚才的讨论", prompt_template="one_page",
            conversation="学习者：选词有没有记忆点\n小知：先读整句，再判断词性。",
            user_id=user, trace_id="feedback-02", skip_multimodal=True))
    payload = out["resource"]["payload"]
    assert payload["generation_mode"] == "unavailable"
    assert all("不要只凭一个熟悉的中文释义选词" not in p and "cet6-guide-v1" not in p for p in calls)
    assert not payload.get("source_evidence")
    assert not out["resource"]["citations"]


def test_missing_selected_source_never_turns_dialog_or_error_into_a_map(monkeypatch):
    monkeypatch.setattr(doc_agent, "retrieve", lambda *a, **k: [])

    async def unexpected(*args, **kwargs):
        raise AssertionError("No model or image request without selected-source evidence")

    monkeypatch.setattr(doc_agent, "llm_complete", unexpected)
    monkeypatch.setattr(doc_agent.multimodal_gateway, "text_to_image", unexpected)
    out = asyncio.run(doc_agent._gen_one("doc", "custom_topic", {}, topic_name="量子纠缠",
        custom_topic=True, source_ids=["selected-upload"], goal="整理刚才的讨论",
        prompt_template="one_page", trace_id="feedback-02-empty", conversation="小知：量子纠缠是量子系统间的关联。"))
    payload = out["resource"]["payload"]
    assert payload["generation_mode"] == "unavailable"
    assert "one_page_visual" not in payload
    assert not out["resource"]["citations"]
    summary = _learner_summary({"test": out["resource"]}, out["flags"], "one_page")
    assert "未生成" in summary and "已经整理好了" not in summary


def test_image_failure_summary_does_not_claim_a_finished_map():
    resource = {"kind": "doc", "payload": {"generation_mode": "model", "one_page_visual": {
        "image_status": "fallback", "image_error": "provider unavailable"}}}
    summary = _learner_summary({"test": resource}, [], "one_page")
    assert "图片未生成" in summary and "文字" in summary


def test_partially_generated_map_reports_partial_success():
    resource = {"payload": {"one_page_visual": {"image_status": "ready", "pages": [
        {"image_status": "ready"}, {"image_status": "fallback"}]}}}
    assert "部分图片未生成" in _learner_summary({"test": resource}, [], "one_page")

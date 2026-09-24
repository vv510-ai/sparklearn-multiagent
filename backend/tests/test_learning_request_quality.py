"""Regressions for the learner's compound CET-6 request and source policies."""
import asyncio
import json

import pytest

from app.agents import doc_agent, orchestrator, planner_agent, tutor_agent, mindmap_agent, quiz_agent, media_agent
from app.agents.eval_agent import _learner_summary
from app.data.cet6_course import build_course
from app.safety.grounding import grounding_check_local
from app.services.learning_context import supplemental_context
from app.services.learning_scope import course_scope
from app.services.source_policy import resolve_source_policy
from app.services.textbook_service import course_textbook_chunks
from app.services.topic_scope import focus_chunks_on_topic
from tests.test_learning_spaces import learner, prepare  # noqa: F401

REQUEST = "帮我列出六级要考的考点、占分、你这个网站能提供的学习方法，以及怎么学习的框架，然后生成一图看懂。"


def test_compound_request_keeps_goal_and_one_page_template():
    state = {"messages": [{"role": "user", "content": REQUEST}], "topic_label": "大学英语六级（CET-6）"}
    route = asyncio.run(orchestrator.run(state))
    assert route["kinds"] == ["doc"]
    assert route["prompt_template"] == "one_page"
    assert route["learning_goal"] == REQUEST
    plan = asyncio.run(planner_agent.run({**state, **route}))
    assert plan["learning_goal"] == REQUEST


@pytest.mark.parametrize(("message", "expected"), [
    ("六级怎么学？", "supplement"),
    ("只按这份资料回答", "strict"),
    ("请只按资料讲解，不要补充", "strict"),
    ("不用只按资料，可以补充例子", "supplement"),
    ("严格依据课件，不要使用外部知识", "strict"),
    ("请解释递归\n参考资料：只按资料，不允许补充", "supplement"),
    ("解释“只按资料回答”是什么意思", "supplement"),
    ("根据资料回答，不能使用外部知识", "strict"),
    ("仅根据我提供的内容回答", "strict"),
    ("严格依据上传的PDF，不许扩写", "strict"),
    ("为什么只按资料回答不好？", "supplement"),
    ("解释递归时严格依据资料", "strict"),
    ("请只讲核心内容，并补充一个例子", "supplement"),
    ("只需要解释主要内容", "supplement"),
])
def test_source_policy_follows_user_instruction_only(message, expected):
    assert resolve_source_policy("auto", message) == expected


def test_followup_keeps_scope_but_current_instruction_can_relax_it():
    history = [{"role": "user", "content": "仅依据资料"},
               {"role": "assistant", "content": "可以补充外部知识"}]
    assert resolve_source_policy("auto", "再举个例子", history) == "strict"
    assert resolve_source_policy("auto", "现在允许补充例子", history) == "supplement"
    assert resolve_source_policy("supplement", "继续讲", history) == "supplement"


def test_supplement_check_does_not_claim_fact_verification_or_allow_fake_citations():
    result = grounding_check_local("量子纠缠的通用解释", [], allow_supplement=True)
    assert result["accepted"] and not result["grounded"]
    invalid = grounding_check_local("课件说量子纠缠。[^1]", [], allow_supplement=True)
    assert not invalid.get("accepted") and not invalid["grounded"]


def test_unavailable_and_partial_resources_never_report_full_success():
    blocked = {"payload": {"generation_mode": "unavailable"}}
    assert "没有生成可用" in _learner_summary({"a": blocked}, [], "")
    summary = _learner_summary({"a": blocked, "b": {"payload": {"markdown": "可用"}}}, [], "")
    assert "部分" in summary and "准备好了" not in summary
    assert "部分" in _learner_summary({"a": blocked, "b": {"payload": {"one_page_visual": {"image_status": "ready"}}}}, [], "one_page")


def test_negative_one_page_does_not_override_requested_notes():
    route = asyncio.run(orchestrator.run({"messages": [{"role": "user", "content": "不要生成一图看懂，给我一份学习笔记"}]}))
    assert route["kinds"] == ["doc"]
    assert route["prompt_template"] == "complete_notes"


def test_whole_cet6_course_keeps_sections_and_adds_attributable_exam_context(learner):
    client, user = learner
    book, _, _ = prepare(client, user, "cet6", "大学英语六级")
    course = build_course()
    with course_scope(user, book["id"], snapshot=course):
        chunks = list(course_textbook_chunks(course))
        assert focus_chunks_on_topic(chunks, "custom_topic", course["title"]) == chunks
        extra = supplemental_context(REQUEST)
        assert any("35%" in c["text"] and c.get("url") for c in extra)
        assert any(c["source_type"] == "product" for c in extra)
        assert not supplemental_context("解释叶节点")


def test_chat_api_keeps_compound_goal_course_evidence_and_supplement_policy(learner, monkeypatch):
    client, user = learner
    book, _, _ = prepare(client, user, "cet6", "大学英语六级", "准备课程考试")
    prompts = []
    monkeypatch.setattr(doc_agent, "is_demo", lambda: False)
    monkeypatch.setattr(doc_agent, "generate_one_page", _fake_image_pipeline)

    async def model(prompt, **kwargs):
        prompts.append(prompt)
        return "# 大学英语六级（CET-6）\n\n## 考试框架\n听力35%、阅读35%、写作15%、翻译15%。\n\n## 学习方法\n先做小测，再练习薄弱项。\n\n## 网站功能\n可以整理笔记与复习图。"

    monkeypatch.setattr(doc_agent, "llm_complete", model)
    response = client.post("/api/chat", json={"user_id": user, "notebook_id": book["id"],
        "message": REQUEST, "source_policy": "auto", "topic_label": "大学英语六级（CET-6）"})
    assert response.status_code == 200
    events = [json.loads(line[5:]) for line in response.text.splitlines() if line.startswith("data:")]
    assert not [event for event in events if event.get("type") == "error"]
    resource = next(event["resource"] for event in events if event.get("type") == "resource")
    assert resource["payload"]["template"] == "one_page"
    assert resource["payload"]["source_policy"] == "supplement"
    assert resource["payload"]["generation_mode"] == "model"
    assert prompts and REQUEST in prompts[0]
    assert "35%" in prompts[0] and "准备课程考试" in prompts[0]
    assert any(event.get("type") == "done" for event in events)


def test_health_reports_only_the_injected_release(learner, monkeypatch):
    client, _ = learner
    monkeypatch.setenv("APP_RELEASE", "test-release-123")
    assert client.get("/api/health").json()["release"] == "test-release-123"


def test_supplement_tutor_calls_model_even_without_selected_source_hits(monkeypatch):
    calls = []
    monkeypatch.setattr(tutor_agent, "retrieve", lambda *a, **k: [])
    monkeypatch.setattr(tutor_agent, "is_demo", lambda: False)

    async def model(prompt, **kwargs):
        calls.append(prompt)
        yield "递归是在解决问题时调用自身处理更小的问题，需要终止条件。这是通用知识解释。"

    monkeypatch.setattr(tutor_agent, "llm_stream", model)
    result = asyncio.run(tutor_agent.run({
        "messages": [{"role": "user", "content": "解释递归"}],
        "source_ids": ["selected"], "source_policy": "supplement", "student_profile": {},
    }))
    assert calls and "允许补充" in calls[0]
    assert "递归是在解决问题时" in result["answer"]
    assert "未经课程资料核验" in result["answer"]
    assert result["citations"] == []


def test_supplement_doc_preserves_request_and_never_invents_source_citation(monkeypatch):
    calls = []
    monkeypatch.setattr(doc_agent, "retrieve", lambda *a, **k: [])
    monkeypatch.setattr(doc_agent, "is_demo", lambda: False)
    monkeypatch.setattr(doc_agent, "generate_one_page", _fake_image_pipeline)

    async def model(prompt, **kwargs):
        calls.append(prompt)
        return "# 量子纠缠\n\n## 通用解释\n量子纠缠描述联合量子状态的关联。"

    monkeypatch.setattr(doc_agent, "llm_complete", model)
    result = asyncio.run(doc_agent._gen_one("doc", "custom_topic", {}, topic_name="量子纠缠",
        custom_topic=True, source_ids=["selected"], source_policy="supplement", goal="请解释量子纠缠并生成一图看懂",
        prompt_template="one_page", trace_id="request-test", skip_multimodal=True))
    resource = result["resource"]
    assert calls and "请解释量子纠缠并生成一图看懂" in calls[0]
    assert resource["payload"]["generation_mode"] == "model"
    assert not resource["payload"]["grounded"]
    assert resource["payload"]["one_page_visual"]["content_status"] == "general_knowledge"
    assert resource["citations"] == []
    assert "[^" not in resource["payload"]["markdown"]


def test_strict_empty_course_blocks_tutor_and_doc_before_model(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Strict empty source scope must not reach the model")

    monkeypatch.setattr(doc_agent, "retrieve", lambda *a, **k: [])
    monkeypatch.setattr(tutor_agent, "retrieve", lambda *a, **k: [])
    monkeypatch.setattr(doc_agent, "llm_complete", forbidden)
    monkeypatch.setattr(tutor_agent, "llm_stream", forbidden)
    answer = asyncio.run(tutor_agent.run({"messages": [{"role": "user", "content": "解释量子纠缠"}],
        "source_ids": [], "source_policy": "strict", "student_profile": {}}))
    assert "没有检索到" in answer["answer"]
    result = asyncio.run(doc_agent._gen_one("doc", "custom_topic", {}, topic_name="量子纠缠",
        custom_topic=True, source_ids=[], source_policy="strict", goal="解释量子纠缠",
        prompt_template="one_page", trace_id="strict-empty", skip_multimodal=True))
    assert result["resource"]["payload"]["generation_mode"] == "unavailable"
    assert "one_page_visual" not in result["resource"]["payload"]


@pytest.mark.parametrize("kind", ["flashcards", "infographic", "data_table", "ppt"])
def test_strict_empty_course_blocks_special_documents(monkeypatch, kind):
    def forbidden(*args, **kwargs):
        pytest.fail("Strict empty sources reached a model/provider")
    monkeypatch.setattr(doc_agent, "llm_complete", forbidden)
    monkeypatch.setattr(doc_agent.multimodal_gateway, "ppt_create", forbidden)
    result = asyncio.run(doc_agent._gen_one(kind, "custom_topic", {}, topic_name="量子纠缠",
        custom_topic=True, source_ids=[], source_policy="strict", goal="解释量子纠缠", trace_id="strict-special"))
    assert result["resource"]["payload"]["generation_mode"] == "unavailable"


@pytest.mark.parametrize("kind,module", [("mindmap", mindmap_agent), ("quiz", quiz_agent), ("video", media_agent)])
def test_strict_empty_course_blocks_other_agents(monkeypatch, kind, module):
    def forbidden(*args, **kwargs):
        pytest.fail("Strict empty sources reached model")
    monkeypatch.setattr(module, "llm_complete", forbidden)
    result = asyncio.run(module.run({"kinds": [kind], "knowledge_points": ["custom_topic"], "topic_label": "量子纠缠",
        "source_ids": [], "source_policy": "strict", "learning_goal": "解释量子纠缠", "student_profile": {}}))
    assert all(resource["payload"]["generation_mode"] == "unavailable" for resource in result.get("generated_resources", {}).values())


@pytest.mark.parametrize("failure", ["fake_citation", "model_error"])
@pytest.mark.parametrize("template", ["one_page", "complete_notes"])
def test_empty_supplement_failure_never_delivers_fake_content_or_image(monkeypatch, failure, template):
    monkeypatch.setattr(doc_agent, "retrieve", lambda *a, **k: [])
    monkeypatch.setattr(doc_agent, "is_demo", lambda: False)

    async def model(*args, **kwargs):
        if failure == "model_error":
            raise RuntimeError("test provider unavailable")
        return "# 量子纠缠\n\n量子纠缠是联合量子状态的关联。[^99]"

    monkeypatch.setattr(doc_agent, "llm_complete", model)
    monkeypatch.setattr(doc_agent, "generate_one_page", lambda *a, **k: pytest.fail("No valid body to generate"))
    result = asyncio.run(doc_agent._gen_one("doc", "custom_topic", {}, topic_name="量子纠缠",
        custom_topic=True, source_ids=["selected"], source_policy="supplement", goal="解释量子纠缠",
        prompt_template=template, trace_id="failed-supplement", skip_multimodal=True))
    resource = result["resource"]
    assert resource["payload"]["generation_mode"] == "unavailable"
    assert "[^99]" not in resource["payload"]["markdown"]
    assert "one_page_visual" not in resource["payload"]
    summary = _learner_summary({"a": resource}, result["flags"], template)
    assert "生成失败" in summary and "好了" not in summary


def test_supplement_tutor_does_not_stream_late_fake_citation(monkeypatch):
    emitted = []
    monkeypatch.setattr(tutor_agent, "retrieve", lambda *a, **k: [])
    monkeypatch.setattr(tutor_agent, "is_demo", lambda: False)

    async def model(*args, **kwargs):
        yield "递归是在解决问题时调用自身处理更小的问题，需要终止条件，也需要每次向终止条件靠近。"
        yield "资料里写了这个结论。[^99]"

    async def capture(event):
        if event.get("type") == "token":
            emitted.append(event.get("delta", ""))

    monkeypatch.setattr(tutor_agent, "llm_stream", model)
    monkeypatch.setattr(tutor_agent, "emit", capture)
    result = asyncio.run(tutor_agent.run({"messages": [{"role": "user", "content": "解释递归"}],
        "source_ids": ["selected"], "source_policy": "supplement", "student_profile": {}}))
    assert "[^99]" not in result["answer"] and "[^99]" not in "".join(emitted)


async def _fake_image_pipeline(*args, **kwargs):
    return {"image_status": "ready", "content_status": kwargs["content_status"], "pages": []}

"""One-page is a general course feature, including free-form requests and aliases."""
import asyncio
import json
import pytest
from app.agents import doc_agent, planner_agent

CASES = [
    ("高等数学", "嗯你可以用一图看懂的功能，帮我把高数大学高数的整体框架构画出来吗？", "# 高数整体框架\n\n## 极限\n研究无限接近。\n\n## 微分\n导数描述变化率。\n\n## 积分\n定积分描述累积。"),
    ("大学物理", "物理整体框架一图看懂", "# 物理学\n\n## 力学\n研究运动与相互作用。\n\n## 热学\n研究温度与能量传递。\n\n## 电磁学\n研究电荷、电流与场。"),
    ("英语语法", "帮我生成英语语法整体框架的一图看懂", "# English Grammar\n\n## 词类\n名词指称事物，动词表达动作或状态。\n\n## 句法\n主语和谓语构成主干。\n\n## 时态\n结合语境表达时间关系。"),
    ("计算机科学", "一图看懂计算机科学的整体框架", "# CS 学习地图\n\n## 算法与数据\n组织数据与解决问题。\n\n## 系统\n处理器、内存与操作系统。\n\n## 网络\n协议支持通信。"),
]

@pytest.mark.parametrize("topic,goal,draft", CASES)
def test_valid_alias_draft_reaches_image_generation(monkeypatch, topic, goal, draft):
    calls=[]
    monkeypatch.setattr(doc_agent, "retrieve", lambda *a, **k: [])
    monkeypatch.setattr(doc_agent, "is_demo", lambda: False)
    async def model(prompt, **kw):
        if "CAPABILITY=doc.one_page_topic_check" in prompt:
            return json.dumps({"status":"matched", "topic":topic, "reason":"The outline answers the requested subject using an equivalent name."})
        return draft
    async def image(name, parts, **kw):
        calls.append((name,parts))
        page={"title":name,"renderer":"xiaoyunque-infographic-v1","image_status":"ready","provider":"xiaoyunque","image_url":"/static/gen/test.png","verification":{"status":"unverified","issues":["fixture"]}}
        return {**page,"pages":[page]}
    monkeypatch.setattr(doc_agent, "llm_complete", model)
    monkeypatch.setattr(doc_agent, "generate_one_page", image)
    result=asyncio.run(doc_agent._gen_one("doc","custom_topic",{},topic_name=topic,custom_topic=True,
        source_ids=[],source_policy="supplement",goal=goal,prompt_template="one_page",trace_id="general-topic"))
    assert result["resource"]["payload"]["generation_mode"] == "model"
    assert len(calls)==1
    assert draft in calls[0][1]
    assert not any(f["type"]=="topic_drift" for f in result["flags"])


def test_current_request_overrides_old_course_and_old_kp(monkeypatch):
    monkeypatch.setattr(planner_agent,"is_demo",lambda:False,raising=False)
    async def model(prompt, **kw):
        assert "有机化学" in prompt
        return json.dumps({"topic":"有机化学","overview":True})
    monkeypatch.setattr(planner_agent,"llm_complete",model,raising=False)
    result=asyncio.run(planner_agent.run({"learning_goal":"请用一图看懂把有机化学的整体框架画出来",
        "topic_label":"高等数学","knowledge_points":["binary_tree"],"prompt_template":"one_page","kinds":["doc"]}))
    assert result["topic_label"]=="有机化学"
    assert result["knowledge_points"]==["custom_topic"]


@pytest.mark.parametrize("goal,history,previous,expected,missing", [
    ("一图看懂有机化学的整体框架", [], "高等数学", "有机化学", False),
    ("刚才的内容生成一图看懂", [{"role":"user","content":"英语语法"}], "高等数学", "英语语法", False),
    ("生成一图看懂", [], "大学物理", "大学物理", False),
    ("生成一图看懂", [], "", "当前主题", True),
    ("图论", [], "英语语法", "图论", False),
    ("知识表示与推理", [], "高等数学", "知识表示与推理", False),
])
def test_scope_outage_never_restores_stale_topic(goal, history, previous, expected, missing):
    from app.services.one_page_topic import resolve_scope
    async def broken(*a, **kw): raise TimeoutError()
    scope = asyncio.run(resolve_scope(goal, history, previous, complete=broken, demo=False))
    assert expected in scope["topic"]
    assert bool(scope.get("missing")) == missing


@pytest.mark.parametrize("outcome", ["repaired", "rejected", "uncertain", "source_fallback_mismatch", "provider_failed", "no_content"])
def test_one_page_failure_boundaries(monkeypatch, outcome):
    from app.llm.failures import ModelFailure
    good = CASES[0][2]
    wrong = CASES[3][2]
    calls = {"image": 0, "repair": 0, "check": 0}
    chunks = [{"text": "TCP 用于可靠传输。", "citation": "网络笔记 p.1", "source_id": "fixture"}] if outcome == "source_fallback_mismatch" else []
    monkeypatch.setattr(doc_agent, "retrieve", lambda *a, **k: chunks)
    monkeypatch.setattr(doc_agent, "is_demo", lambda: False)
    async def grounding(*a, **kw): return {"grounded": False, "accepted": False, "verdict": "不受资料支持"}
    monkeypatch.setattr(doc_agent, "grounding_check", grounding)
    async def model(prompt, **kw):
        if "CAPABILITY=doc.one_page_topic_check" in prompt:
            calls["check"] += 1
            if outcome == "uncertain": return "malformed result"
            status = "mismatch" if (outcome == "rejected" or outcome == "repaired" and calls["check"] == 1 or outcome == "source_fallback_mismatch" and calls["check"] > 1) else "matched"
            return json.dumps({"status": status, "reason": "固定样本主题检查"})
        if "CAPABILITY=doc.one_page_topic_repair" in prompt:
            calls["repair"] += 1
            return good if outcome == "repaired" else wrong
        if outcome == "no_content": raise ModelFailure("empty_response")
        return wrong if outcome in {"rejected", "repaired"} else good
    async def image(*a, **kw):
        calls["image"] += 1
        page={"renderer":"xiaoyunque-infographic-v1", "image_status":"fallback" if outcome == "provider_failed" else "ready", "attempts":[{"attempt":1}], "verification":{"status":"unverified","issues":["fixture"]}}
        return {**page,"pages":[page]}
    monkeypatch.setattr(doc_agent, "llm_complete", model)
    monkeypatch.setattr(doc_agent, "generate_one_page", image)
    result = asyncio.run(doc_agent._gen_one("doc", "custom_topic", {}, topic_name="高等数学", custom_topic=True,
        source_ids=["fixture"] if chunks else [], source_policy="strict" if chunks else "supplement",
        goal="高等数学整体框架一图看懂", prompt_template="one_page",trace_id="matrix"))
    payload=result["resource"]["payload"]
    if outcome in {"rejected", "source_fallback_mismatch", "no_content"}:
        assert calls["image"] == 0
        assert payload["generation_mode"] == "unavailable"
        assert payload["image_attempted"] is False
        assert "尚未调用小云雀" in payload["markdown"]
        assert payload["failure_stage"] == ("content_generation" if outcome == "no_content" else "content_topic")
    else:
        assert calls["image"] == 1
        assert payload["image_attempted"] is True
    if outcome == "repaired":
        assert calls["repair"] == 1
        assert payload["topic_verification"]["status"] == "matched"
        assert payload["markdown"] == good
    if outcome == "rejected": assert calls["repair"] == 1
    if outcome == "uncertain": assert "topic_check_unavailable" in payload["generation_details"]["reason_codes"]
    if outcome == "provider_failed":
        assert payload["failure_stage"] == "image_generation"
        assert "image_degraded" in payload["generation_details"]["reason_codes"]


@pytest.mark.parametrize("plain_markers", [False, True])
def test_selected_chapters_not_discarded_for_missing_course_name(monkeypatch, plain_markers):
    chunks = [{"text":"极限描述无限接近。", "citation":"讲义 p.1", "source_id":"fixture"},
              {"text":"导数描述瞬时变化率。", "citation":"讲义 p.2", "source_id":"fixture"}]
    monkeypatch.setattr(doc_agent,"retrieve",lambda *a, **kw:chunks)
    monkeypatch.setattr(doc_agent,"is_demo",lambda:False)
    async def model(prompt, **kw):
        if "CAPABILITY=doc.one_page_topic_check" in prompt:
            return json.dumps({"status":"matched","reason":"极限与导数属于高等数学"})
        assert all(c["text"] in prompt for c in chunks)
        draft = "# 高数\n\n## 极限\n极限描述无限接近。[^1]\n\n## 导数\n导数描述瞬时变化率。[^2]"
        return draft.replace("[^", "[") if plain_markers else draft
    async def grounding(*a, **kw): return {"grounded":True,"accepted":True}
    monkeypatch.setattr(doc_agent,"llm_complete",model)
    monkeypatch.setattr(doc_agent,"grounding_check",grounding)
    result=asyncio.run(doc_agent._gen_one("doc","custom_topic",{},topic_name="高等数学",custom_topic=True,
        source_ids=["fixture"],source_policy="strict",goal="高数整体框架一图看懂",prompt_template="one_page",skip_multimodal=True,trace_id="matrix",
        one_page_scope={"topic":"高等数学","overview":True,"kp":"custom_topic"}))
    payload=result["resource"]["payload"]
    assert payload["generation_mode"]=="model"
    assert len(payload["source_evidence"])==2
    assert payload["image_attempted"] is False


def test_strict_empty_sources_never_calls_models_or_image(monkeypatch):
    monkeypatch.setattr(doc_agent,"retrieve",lambda *a, **kw:[])
    monkeypatch.setattr(doc_agent,"is_demo",lambda:False)
    async def forbidden(*a, **kw): raise AssertionError("strict empty source must stop first")
    monkeypatch.setattr(doc_agent,"llm_complete",forbidden)
    monkeypatch.setattr(doc_agent,"generate_one_page",forbidden)
    out=asyncio.run(doc_agent._gen_one("doc","custom_topic",{},topic_name="历史学",custom_topic=True,
        source_ids=[],source_policy="strict",goal="一图看懂历史学",prompt_template="one_page",trace_id="matrix"))
    assert out["resource"]["payload"]["blocked_reason"]=="source_scope_empty"
    assert out["resource"]["payload"]["image_attempted"] is False


@pytest.mark.parametrize("topic,allowed", [("高等数学",False),("大学英语六级",True)])
def test_course_exam_reference_is_not_injected_into_other_subjects(monkeypatch, topic, allowed):
    from app.services import one_page_topic
    monkeypatch.setattr(one_page_topic,"current_space", lambda:{"course":{"title":"大学英语六级（CET-6）"}})
    scope=one_page_topic._scope(topic,True)
    assert scope["use_course_reference"] is allowed
    monkeypatch.setattr(doc_agent,"supplemental_context",lambda q:[{"text":"六级听力35%", "source_type":"exam_reference","citation":"考试结构"}])
    monkeypatch.setattr(doc_agent,"is_demo",lambda:False)
    async def model(prompt, **kw):
        if "CAPABILITY=doc.one_page_topic_check" in prompt:
            return json.dumps({"status":"matched","reason":"主题匹配"})
        assert ("六级听力35%" in prompt) is allowed
        return CASES[0][2]
    monkeypatch.setattr(doc_agent,"llm_complete",model)
    out=asyncio.run(doc_agent._gen_one("doc","custom_topic",{},topic_name=topic,custom_topic=True,
        source_ids=[],source_policy="supplement",goal=topic+"考试框架一图看懂",prompt_template="one_page",trace_id="scope",
        skip_multimodal=True,one_page_scope=scope))
    assert out["resource"]["payload"]["generation_mode"]=="model"


def test_semantic_missing_topic_is_not_reinterpreted_as_a_subject():
    from app.services.one_page_topic import resolve_scope
    async def model(*a, **kw): return '{"topic":"","overview":false}'
    result=asyncio.run(resolve_scope("能不能给我一个一图看懂",[],"",complete=model,demo=False))
    assert result["missing"] is True


def test_scope_fallback_uses_tool_button_focus_without_truncating_it():
    from app.services.one_page_topic import resolve_scope
    async def broken(*a, **kw): raise TimeoutError()
    goal="请根据最近的学习对话和所选资料自动识别内容焦点，生成一图看懂：" + "布局说明"*30 + "\n\n请以最近学习对话中的实际问题为准：选词有没有记忆点"
    scope=asyncio.run(resolve_scope(goal,[],"高等数学",complete=broken,demo=False))
    assert scope["topic"]=="选词有没有记忆点"


def test_plain_citations_keep_invalid_numbers_for_rejection_and_leave_links_unchanged():
    from app.rag.citation import normalize_reference_markers
    from app.safety.grounding import grounding_check_local
    text=normalize_reference_markers("定理。[1] 补充见资料[99]。 [2](https://example.test) a[1]")
    assert "[^1]" in text and "[^99]" in text
    assert "[2](https://example.test) a[1]" in text
    check = grounding_check_local(text,["定理"],allow_supplement=True)
    assert not check.get("accepted")
    assert "99" in str(check["unsupported"])
    no_sources=grounding_check_local(normalize_reference_markers("依据资料[99]"),[],allow_supplement=True)
    assert not no_sources.get("accepted") and "99" in str(no_sources["unsupported"])


@pytest.mark.parametrize("text", ["数组 `[1]` 是单元素列表", "a[1][2]", "[章节][1]", "[1][reference]", "[1][]", "列表是[1]。", "```python\na=[99]\n```", "[1]: https://example.test [99]"])
def test_reference_normalization_preserves_non_citation_brackets(text):
    from app.rag.citation import normalize_reference_markers
    assert normalize_reference_markers(text)==text

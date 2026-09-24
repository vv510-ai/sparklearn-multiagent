import asyncio
from xml.etree import ElementTree as ET

from app.services import one_page_renderer as renderer
from app.agents.eval_agent import _learner_summary


MAP = """# 六级学习框架
用考点组织练习，用作答发现薄弱项。
## 试卷结构
听力35%；阅读35%。
写作15%；翻译15%。
## 阅读与词汇
证据句 → 同义改写 → 排除干扰。
词汇放回原句，保留转折与否定。
## 听力与输出
完整听 → 对照文本 → 闭稿复听。
写作先观点后理由；翻译先搭主干。
## 本站支持
上传资料 → 对话答疑 → 练习反馈。
## 能力边界
起点训练不是完整真题库。
不承诺考试提分。
## 复习与检验
先独立作答，再看解析。
换题复测，不把重做同题当新证据。
## 学习路径
明确目标 → 找薄弱项 → 学原理 → 独立练习 → 换题复测
"""


def test_map_has_real_hierarchy_and_distinct_navigation(monkeypatch, tmp_path):
    monkeypatch.setattr(renderer, "GEN_DIR", tmp_path)
    result=renderer.render_one_page("六级学习框架",MAP,content_status="supplemented")
    assert result["renderer"] == "svg-map-v2" and len(result["pages"]) == 1
    assert result["relation_count"] == 10
    root=ET.parse(tmp_path/result["image_url"].rsplit("/",1)[-1]).getroot()
    branches=[n for n in root.iter() if n.get("data-relation") == "topic-branch"]
    order=[n for n in root.iter() if n.get("data-relation") == "learning-order"]
    assert len(branches) == 6 and len(order) == 4
    assert all(n.get("stroke-dasharray") for n in order)
    text="".join(n.text or "" for n in root.iter() if n.get("data-content"))
    for required in ["不承诺考试提分", "起点训练不是完整真题库", "35%", "转折与否定", "换题复测"]:
        assert required in text
    for n in root.iter():
        if n.tag.endswith("text"):
            assert 0 < float(n.get("y")) < 1080


def test_dense_text_preserved_without_claiming_diagram(monkeypatch, tmp_path):
    monkeypatch.setattr(renderer,"GEN_DIR",tmp_path)
    result=renderer.render_one_page("长资料", MAP.replace("听力35%；阅读35%。", "不得删除关键条件。"*50), content_status="checked")
    assert result["layout"] == "text_excerpt"
    summary=_learner_summary({"a":{"payload":{"one_page_visual":result}}},[],"one_page")
    assert "关系图尚未生成" in summary
    text="".join(n.text or "" for page in result["pages"] for n in ET.parse(tmp_path/page["image_url"].rsplit("/",1)[-1]).getroot().iter() if n.get("data-content"))
    assert "不得删除关键条件。"*50 in text


def test_source_excerpt_never_becomes_a_verified_diagram(monkeypatch, tmp_path):
    monkeypatch.setattr(renderer,"GEN_DIR",tmp_path)
    assert renderer.render_one_page("来源",MAP,content_status="source_excerpt")["layout"] == "text_excerpt"


def test_dense_generation_gets_one_bounded_repair_before_render(monkeypatch):
    from app.agents import doc_agent
    from app.services.knowledge_map_layout import map_plan
    dense = MAP.replace("听力35%；阅读35%。", "保留必要的限定条件。" * 25)
    calls = []
    async def complete(prompt, **kwargs):
        calls.append(prompt)
        assert kwargs["allow_mock_fallback"] is False
        return MAP
    monkeypatch.setattr(doc_agent, "llm_complete", complete)
    fixed = asyncio.run(doc_agent._fit_one_page("六级学习框架", dense, "用户要求考点、占分、方法和本站能力"))
    assert fixed == MAP and map_plan("六级学习框架", fixed)
    assert len(calls) == 1 and "必要的限定条件" in calls[0]
    assert asyncio.run(doc_agent._fit_one_page("六级学习框架", MAP, "同要求")) == MAP
    assert len(calls) == 1  # normal map never adds a call


def test_map_repair_cannot_drop_a_requested_branch(monkeypatch):
    from app.agents import doc_agent
    dense = MAP.replace("听力35%；阅读35%。", "重要条件。" * 50)
    async def complete(*args, **kwargs):
        return MAP.replace("## 本站支持", "## 其他建议")
    monkeypatch.setattr(doc_agent, "llm_complete", complete)
    assert asyncio.run(doc_agent._fit_one_page("六级学习框架", dense, "原请求")) == dense
    async def failed(*args, **kwargs):
        raise TimeoutError()
    monkeypatch.setattr(doc_agent, "llm_complete", failed)
    assert asyncio.run(doc_agent._fit_one_page("六级学习框架", dense, "原请求")) == dense


def test_abbreviated_whole_course_overview_keeps_real_course_concepts():
    from app.agents import doc_agent
    from app.services.learning_scope import _scope, graph_index
    token = _scope.set({"course": {"title": "大学英语六级（CET-6）", "kind": "cet6"}, "graph": graph_index({"nodes": [
        {"id": "cet6_listening", "name": "听力信息提取"}, {"id": "cet6_reading", "name": "仔细阅读与推断"}], "edges": []})})
    try:
        assert doc_agent._content_on_topic("# 六级备考\n听力信息提取：先读题。仔细阅读与推断：定位证据。", "大学英语六级（CET-6）", "custom_topic")
        assert not doc_agent._content_on_topic("# 其他课程\n生产者与消费者。", "大学英语六级（CET-6）", "custom_topic")
        assert not doc_agent._content_on_topic("听力信息提取：先读题。", "仔细阅读与推断", "cet6_reading")
    finally:
        _scope.reset(token)

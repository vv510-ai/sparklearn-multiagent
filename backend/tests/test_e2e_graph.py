"""端到端冒烟测试(演示模式,离线):
① intent=generate:profile→orchestrator→planner→path→四节点并行→eval,
   断言事件序列、四类资源产出、资源落库;
② intent=tutor:流式 token、引用 citations、最终 answer;
③ 评估闭环 evaluate_answers:BKT 掌握度变化、错因回写、路径重排。
真实环境下同样可跑(pytest backend/tests -q)。"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tests._stubs import install  # noqa: E402

install()

from app.agents.graph import run_with_events  # noqa: E402
from app.agents.eval_agent import evaluate_answers  # noqa: E402
from app.config import is_demo  # noqa: E402
from app.models.db import init_db  # noqa: E402
from app.rag.ingest import ingest_corpus  # noqa: E402
from app.services.profile_service import ensure_user, get_profile, merge_profile  # noqa: E402


async def _collect(state: dict) -> list[dict]:
    events = []
    async for ev in run_with_events(state):
        events.append(ev)
    return events


_QUIZ: list = []


def test_generate_pipeline():
    assert is_demo(), "无密钥环境应自动进入演示模式"
    init_db()
    n = ingest_corpus()
    assert n >= 20, f"语料切片数过少: {n}"
    ensure_user("stu1")

    events = asyncio.run(_collect({
        "user_id": "stu1", "session_id": "t-gen",
        "messages": [{"role": "user", "content": "我下周考试,帮我生成二叉树的学习资源"}],
        "knowledge_points": ["binary_tree"],
        "kinds": ["doc", "mindmap", "quiz", "video"],
        "intent": "generate",
    }))
    types = [e["type"] for e in events]
    assert types[-1] == "done"
    started = [e["agent"] for e in events if e["type"] == "agent_start"]
    for must in ("profile", "orchestrator", "planner", "path", "doc", "mindmap", "quiz", "media", "eval"):
        assert must in started, f"缺少 agent_start: {must}(实际 {started})"
    resources = [e["resource"] for e in events if e["type"] == "resource"]
    kinds = {r["kind"] for r in resources}
    assert {"doc", "mindmap", "quiz", "video"} <= kinds, f"资源类型不全: {kinds}"
    assert any(e["type"] == "path" for e in events)
    assert any(e["type"] == "profile" for e in events)
    assert any(e["type"] == "summary" for e in events)
    quiz = next(r for r in resources if r["kind"] == "quiz")
    questions = quiz["payload"]["questions"]
    assert len(questions) >= 6, f"题量不足: {len(questions)}"
    for question in questions:
        if question["type"] == "single" or (question["type"] == "complexity" and question.get("options")):
            assert question["answer"] in {"A", "B", "C", "D"}, question
    doc = next(r for r in resources if r["kind"] == "doc")
    assert doc["citations"], "文档资源应携带引用"
    # 落库验证(eval_agent.merge)
    from app.models.db import session
    from app.models.entities import Resource
    with session() as s:
        rows = s.query(Resource).filter(Resource.user_id == "stu1").all()
    assert len(rows) >= 4, f"资源未全部落库: {len(rows)}"
    print(f"  生成链路 ✓ 事件 {len(events)} 条,资源 {len(resources)} 份,落库 {len(rows)} 行")
    _QUIZ.append(quiz)


def test_tutor_pipeline():
    ensure_user("stu1")
    events = asyncio.run(_collect({
        "user_id": "stu1", "session_id": "t-tutor",
        "messages": [{"role": "user", "content": "为什么 Dijkstra 不能处理负权边?"}],
        "intent": "tutor",
    }))
    types = [e["type"] for e in events]
    assert types[-1] == "done"
    tokens = [e for e in events if e["type"] == "token"]
    assert len(tokens) >= 5, "应有流式 token 事件"
    assert any(e["type"] == "citations" and e.get("items") for e in events), "应推送引用"
    started = [e["agent"] for e in events if e["type"] == "agent_start"]
    assert "tutor" in started and "planner" not in started, "tutor 分支不应进入生成流水线"
    print(f"  答疑链路 ✓ token {len(tokens)} 段")


def test_eval_loop():
    quiz = _QUIZ[0] if _QUIZ else None
    if quiz is None:
        test_generate_pipeline()
        quiz = _QUIZ[0]
    merge_profile("stu1", {"knowledge_mastery": {"binary_tree": 0.3}})
    before = get_profile("stu1")["knowledge_mastery"]["binary_tree"]
    qs = quiz["payload"]["questions"]
    answers = [{"question_id": q["id"], "kp": q.get("kp", "binary_tree"),
                "correct": i % 2 == 0,
                "error_tags": q.get("error_tags", [])} for i, q in enumerate(qs)]
    report = evaluate_answers("stu1", answers)
    after = get_profile("stu1")["knowledge_mastery"]["binary_tree"]
    assert "accuracy" in report and report["per_kp"], "评估报告字段缺失"
    assert report["path"]["nodes"], "应返回重排后的路径"
    assert report["suggestions"], "应给出学习建议"
    assert after != before, f"BKT 应更新掌握度({before} → {after})"
    err_profile = get_profile("stu1").get("error_prone", [])
    if any(not a["correct"] and a["error_tags"] for a in answers):
        assert err_profile, "错因标签应回写画像"
    print(f"  评估闭环 ✓ 掌握度 {before:.3f}→{after:.3f},正确率 {report['accuracy']:.0%},"
          f"易错画像 {err_profile}")


if __name__ == "__main__":
    test_generate_pipeline()
    test_tutor_pipeline()
    test_eval_loop()
    print("ALL E2E SMOKE TESTS PASSED")

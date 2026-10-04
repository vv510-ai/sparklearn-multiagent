"""Initial advice must use saved intake, survive recovery and remain course-private."""
import asyncio
import copy
import datetime as dt
import json
import uuid

import pytest

from app.models.db import TENANT_TABLES, session
from app.models.entities import Cet6Advice
from app.services import cet6_advice as advice, cet6_learning as learning
from tests.test_learning_spaces import learner, prepare  # noqa: F401


def setup(learner, **values):
    client, user = learner
    book, _, _ = prepare(client, user, "cet6", "入门建议")
    base = f"/api/notebooks/{book['id']}/cet6"
    current = client.get(base).json()
    prefs = {**current["preferences"], **values}
    saved = client.post(base + "/preferences", json={"revision": 0, "preferences": prefs})
    assert saved.status_code == 200, saved.text
    return client, user, book["id"], base, saved.json()


def model(monkeypatch, prefs, transform=None):
    calls = []
    monkeypatch.setattr(advice, "is_demo", lambda: False)
    async def complete(prompt, **kwargs):
        calls.append((prompt, kwargs))
        text = advice.basic_text(prefs)
        text["summary"] = "根据你填写的情况，先围绕自己的学习目标安排短练，再保留首次答案与卡点。可以从阅读证据、听力理解和表达修改逐步检查，不必一开始给能力定级。"
        if transform:
            transform(text)
        return json.dumps(text, ensure_ascii=False)
    monkeypatch.setattr(advice, "llm_complete", complete)
    return calls


def test_save_then_generate_restore_cache_and_real_actions(learner, monkeypatch):
    client, user, book, base, saved = setup(learner, total_score=353, listening_score=145, reading_score=112,
        writing_translation_score=96, target_score=450, daily_minutes=20, goal="阅读常常做不完")
    calls = model(monkeypatch, saved["preferences"])
    assert client.get(base + "/advice").json()["status"] == "empty"
    assert calls == []  # Saving or opening the course does not spend a model call.
    result = client.post(base + "/advice", json={"profile_revision": 1, "user_id": "client-supplied-id-is-ignored"})
    assert result.status_code == 200, result.text
    with session() as db:
        assert db.get(Cet6Advice, book).user_id == user
    report = client.get(base + "/advice").json()
    assert report["status"] == "ready" and not report["stale"]
    assert report["input"]["total_score"] == 353 and report["facts"]["score_gap"] == 97
    assert report["content"]["priority_kind"] == "reading"
    assert len(report["content"]["sections"]) == 5
    assert all(sum(t["minutes"] for t in d["tasks"]) == 20 for d in report["week"])
    assert report["actions"][0]["kind"] == "reading"
    a = report["actions"][0]
    assert client.get(f"{base}/exams/{a['paper_id']}/{a['kind']}").status_code == 200
    client.post(base + "/advice", json={"profile_revision": 1})
    assert len(calls) == 1
    assert '"total_score": 353' in calls[0][0] and '"daily_minutes": 20' in calls[0][0]
    assert calls[0][1]["allow_mock_fallback"] is False and calls[0][1]["json_object"] is True
    assert calls[0][1]["reasoning_mode"] == "enabled"
    client.post(f"/api/notebooks/{book}/conversations", json={})
    assert client.get(base + "/advice").json()["content"] == report["content"]


@pytest.mark.parametrize("minutes,total,date,expected_days", [(20, None, None, 7), (90, 353, None, 7),
    (5, None, "2026-10-07", 3), (180, 500, "2026-10-01", 7), (20, None, "2026-10-04", 1)])
def test_missing_scores_time_budgets_and_dates(learner, monkeypatch, minutes, total, date, expected_days):
    monkeypatch.setattr(learning, "now", lambda: dt.datetime(2026, 10, 4, 8, tzinfo=dt.timezone.utc))
    client, _, _, base, saved = setup(learner, daily_minutes=minutes, total_score=total, exam_date=date)
    response = client.post(base + "/advice", json={"profile_revision": saved["revision"]})
    assert response.status_code == 200, response.text
    report = client.get(base + "/advice").json()
    assert report["status"] == "unavailable" and "演示" in report["message"]
    assert report["input"]["reading_score"] is None and report["input"]["target_score"] is None
    assert report["facts"]["score_gap"] is None
    assert len(report["week"]) == expected_days
    for day in report["week"]:
        assert day["minutes"] == minutes == sum(t["minutes"] for t in day["tasks"])
        assert all(t["minutes"] > 0 for t in day["tasks"])
    if minutes < 45:
        assert all(len({t["kind"] for t in d["tasks"]}) == 1 for d in report["week"])


def test_report_revisions_keep_previous_and_ignore_word_quota(learner, monkeypatch):
    client, _, _, base, saved = setup(learner, daily_minutes=20)
    calls = model(monkeypatch, saved["preferences"])
    client.post(base + "/advice", json={"profile_revision": 1})
    original = client.get(base + "/advice").json()
    saved = client.post(base + "/preferences", json={"revision": 1, "preferences": {**saved["preferences"], "daily_new_words": 5, "word_order": "family"}}).json()
    assert not client.get(base + "/advice").json()["stale"]
    client.post(base + "/advice", json={"profile_revision": saved["revision"]})
    assert len(calls) == 1
    saved = client.post(base + "/preferences", json={"revision": saved["revision"], "preferences": {**saved["preferences"], "daily_minutes": 90}}).json()
    assert client.get(base + "/advice").json()["stale"]
    assert client.post(base + "/advice", json={"profile_revision": 1}).status_code == 409
    model(monkeypatch, saved["preferences"])
    client.post(base + "/advice", json={"profile_revision": saved["revision"]})
    updated = client.get(base + "/advice").json()
    assert updated["status"] == "ready" and not updated["stale"]
    assert updated["previous"]["content"] == original["content"]
    assert updated["input"]["daily_minutes"] == 90


@pytest.mark.parametrize("bad", ["link", "unknown_reference", "known_question", "wrong_time", "promise", "made_up_target", "missing_section", "extra_daily", "wrong_listening", "old_answers", "invented_self_report", "wrong_translation"])
def test_reject_untrusted_or_inconsistent_model_output_with_recovery(learner, monkeypatch, bad):
    client, _, _, base, saved = setup(learner, preparation="regular", reading_completion="unfinished")
    def corrupt(text):
        if bad == "link": text["summary"] += " 访问 https://not-a-course.invalid/ 获取练习。"
        if bad == "unknown_reference": text["summary"] += " 参见[ref:invented]。"
        if bad == "known_question": text["followup_keys"] = ["preparation"]
        if bad == "wrong_time": text["summary"] += " 每天学习90分钟。"
        if bad == "promise": text["summary"] += " 保证通过考试。"
        if bad == "made_up_target": text["summary"] += " 目标设为450分。"
        if bad == "missing_section": text["sections"].pop()
        if bad == "extra_daily": text["sections"][0]["body"] += "每天完成阅读后，还要额外做完听力和整篇作文。"
        if bad == "wrong_listening": text["sections"][1]["body"] += "先选择六级短对话题，再独立听录音并回答问题。"
        if bad == "old_answers": text["sections"][0]["body"] += "旧题正确率提高就说明阅读能力提升。"
        if bad == "invented_self_report": text["summary"] += " 你自述认识单词，只是速度跟不上。"
        if bad == "wrong_translation": text["sections"][3]["body"] += "将英文原文译成中文，保持原意完整并保证中文自然。"
    model(monkeypatch, saved["preferences"], corrupt)
    client.post(base + "/advice", json={"profile_revision": 1})
    failed = client.get(base + "/advice").json()
    assert failed["status"] == "failed" and len(failed["content"]["sections"]) == 5
    assert failed["input"]["daily_minutes"] == 20
    assert failed["content"]["followup_keys"] == []
    model(monkeypatch, saved["preferences"])
    client.post(base + "/advice", json={"profile_revision": 1})
    assert client.get(base + "/advice").json()["status"] == "ready"


def test_correct_listening_exclusion_is_not_rejected(learner, monkeypatch):
    client, _, _, base, saved = setup(learner)
    def explain_scope(text):
        text["sections"][1]["body"] += "六级只按规定题型练习，不混入四级短篇新闻。"
    model(monkeypatch, saved["preferences"], explain_scope)
    client.post(base + "/advice", json={"profile_revision": 1})
    assert client.get(base + "/advice").json()["status"] == "ready"


def test_model_cannot_replace_the_program_schedule(learner, monkeypatch):
    client, _, _, base, saved = setup(learner, daily_minutes=20)
    def conflicting_schedule(text):
        text["week_note"] = "每天再额外做一篇作文，并增加90分钟训练。"
        text["stages"] = [{"title": "八到十周冲刺", "text": "考试日期未填，也要按这个固定周期准备。"}]
    model(monkeypatch, saved["preferences"], conflicting_schedule)
    client.post(base + "/advice", json={"profile_revision": 1})
    report = client.get(base + "/advice").json()
    assert report["status"] == "ready"
    assert report["content"]["week_note"] == advice.schedule_text(saved["preferences"])["week_note"]
    assert report["content"]["stages"] == advice.schedule_text(saved["preferences"])["stages"]
    assert all(day["minutes"] == 20 for day in report["week"])


def test_numerical_score_explanation_and_checked_target_combination(learner, monkeypatch):
    client, _, _, base, saved = setup(learner, total_score=353, listening_score=145, reading_score=112,
        writing_translation_score=96, target_score=450, daily_minutes=20)
    def explain(text):
        text["summary"] = "你的历史总分353，听力145，阅读112，写作和翻译96。**我建议优先排查阅读**，同时保持听力训练，并分别检查写作和翻译中的问题。"
        text["target_breakdown"] = {"listening": 170, "reading": 160, "writing_translation": 120,
            "reason": "这是一组供讨论的目标组合，把较多增量放在阅读；需要先通过独立练习观察具体问题，再调整分配，不能把它当作分数预测。"}
    model(monkeypatch, saved["preferences"], explain)
    client.post(base + "/advice", json={"profile_revision": 1})
    report = client.get(base + "/advice").json()
    assert report["status"] == "ready"
    assert "总分353" in report["content"]["summary"]
    assert "ref:scores" in report["content"]["score_analysis"]
    assert report["content"]["target_breakdown"]["reading"] == 160


@pytest.mark.parametrize("statement", ["你的总分400分。", "你的目标是500分。", "每天学习90分钟。", "425分及格线是目标。", "你的问题本质就是词汇量不足。", "同等分差下，听力和阅读对总分影响更大。"])
def test_reject_false_claims_without_banning_all_numbers(statement):
    prefs = {"total_score": 353, "target_score": 450, "daily_minutes": 20}
    with pytest.raises(ValueError):
        advice.validate_claims(statement, prefs)
    advice.validate_claims("你的总分353，目标450，每天学习20分钟。完整阅读考试参考用时40分钟。[考试结构](ref:structure)", prefs)
    advice.validate_claims("考试参考用时：听力30分钟、阅读40分钟、写作30分钟。听力35%、阅读35%。", prefs)
    advice.validate_claims("如果填出来是阅读210、听力100、写译110，则优先级会不同。", prefs)


def test_extra_metadata_and_equivalent_unfamiliar_material_keep_report(learner, monkeypatch):
    client, _, _, base, saved = setup(learner, preparation="regular", reading_completion="finished")
    def explain(text):
        text["sections"][0]["title_hint"] = None
        text["sections"][0]["body"] = text["sections"][0]["body"].replace("未做过", "没做过")
        text["sections"][0]["body"] += "你每天只有20分钟，因此轮到阅读时可以分段完成。"
    calls = model(monkeypatch, saved["preferences"], explain)
    client.post(base + "/advice", json={"profile_revision": 1})
    report = client.get(base + "/advice").json()
    assert report["status"] == "ready"
    assert "title_hint" not in report["content"]["sections"][0]
    assert "上次阅读已做完" in calls[0][0] and "上次有规律准备" in calls[0][0]


def test_method_does_not_replace_rotating_schedule(learner, monkeypatch):
    client, _, _, base, saved = setup(learner, daily_minutes=90)
    def extra_daily(text):
        text["sections"][1]["body"] += "每天听力22分钟，其他内容另行安排。"
    model(monkeypatch, saved["preferences"], extra_daily)
    client.post(base + "/advice", json={"profile_revision": 1})
    assert client.get(base + "/advice").json()["status"] == "failed"


@pytest.mark.parametrize("reference_style", ["label", "id"])
def test_bare_citations_and_missing_progress_note_are_completed(learner, monkeypatch, reference_style):
    client, _, _, base, saved = setup(learner)
    def partial(text):
        text["score_analysis"] = text["score_analysis"].replace("[官方分数解释](ref:scores)",
            "[官方分数解释]" if reference_style == "label" else "[ref:scores]")
        text["sections"][0]["body"] = "先独立完成阅读，记录不确定的地方；核对时回到原文找到依据。" * 4
        text["sections"][0]["body"] += "[六级笔试结构]" if reference_style == "label" else "[ref:structure]"
        text["sections"][4]["body"] += "[回忆练习研究]" if reference_style == "label" else "[ref:retrieval]"
    model(monkeypatch, saved["preferences"], partial)
    client.post(base + "/advice", json={"profile_revision": 1})
    report = client.get(base + "/advice").json()
    assert report["status"] == "ready"
    assert "[官方分数解释](ref:scores)" in report["content"]["score_analysis"]
    assert "[六级笔试结构](ref:structure)" in report["content"]["sections"][0]["body"]
    assert "[回忆练习研究](ref:retrieval)" in report["content"]["sections"][4]["body"]
    assert "请用未做过的材料" in report["content"]["sections"][0]["body"]


def test_running_claim_expiry_and_late_result_cannot_replace_new_report(learner, monkeypatch):
    client, user, book, base, saved = setup(learner)
    monkeypatch.setattr(advice, "is_demo", lambda: False)
    first, claim = advice.request(user, book, 1)
    duplicate, no_claim = advice.request(user, book, 1)
    assert duplicate["status"] == "running" and no_claim is None
    with session() as db:
        row = db.get(Cet6Advice, book)
        row.data = {**row.data, "started_at": (learning.now() - dt.timedelta(seconds=181)).isoformat()}
        db.commit()
    assert client.get(base + "/advice").json()["status"] == "failed"
    _, replacement = advice.request(user, book, 1)
    assert replacement != claim
    calls = model(monkeypatch, saved["preferences"])
    asyncio.run(advice.generate(user, book, claim))
    assert calls == []
    async def late(prompt, **kwargs):
        with session() as db:
            row = db.get(Cet6Advice, book)
            row.data = {**row.data, "claim": "newer-claim", "status": "running"}
            row.revision += 1
            db.commit()
        return json.dumps(advice.basic_text(saved["preferences"]), ensure_ascii=False)
    monkeypatch.setattr(advice, "llm_complete", late)
    asyncio.run(advice.generate(user, book, replacement))
    with session() as db:
        assert db.get(Cet6Advice, book).data["claim"] == "newer-claim"
        assert db.get(Cet6Advice, book).data["status"] == "running"


def test_advice_is_account_and_course_scoped(learner):
    client, user, book, base, _ = setup(learner, goal="我的私人学习困难")
    client.post(base + "/advice", json={"profile_revision": 1})
    other, _, _ = prepare(client, user, "cet6", "另一门六级")
    other_base = f"/api/notebooks/{other['id']}/cet6/advice"
    assert client.get(other_base).json()["status"] == "empty"
    assert client.post(other_base, json={"profile_revision": 1}).status_code == 409
    foreign = client.post("/api/auth/register", json={"email": f"advice-{uuid.uuid4().hex}@example.test", "password": "Advice-Test-Password!", "name": "隔离验收"}).json()
    client.headers["Authorization"] = f"Bearer {foreign['access_token']}"
    assert client.get(base + "/advice").status_code == 404
    assert client.post(base + "/advice", json={"profile_revision": 1}).status_code == 404
    assert "cet6_advice" in TENANT_TABLES

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
    assert calls[0][1]["reasoning_mode"] == "disabled"
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
    saved = client.post(base + "/preferences", json={"revision": 1, "preferences": {**saved["preferences"], "daily_new_words": 5}}).json()
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


@pytest.mark.parametrize("bad", ["link", "known_question", "wrong_time", "promise", "made_up_target", "missing_section"])
def test_reject_untrusted_or_inconsistent_model_output_with_recovery(learner, monkeypatch, bad):
    client, _, _, base, saved = setup(learner, preparation="regular", reading_completion="unfinished")
    def corrupt(text):
        if bad == "link": text["summary"] += " 访问 https://not-a-course.invalid/ 获取练习。"
        if bad == "known_question": text["followup_keys"] = ["preparation"]
        if bad == "wrong_time": text["summary"] += " 每天学习90分钟。"
        if bad == "promise": text["summary"] += " 保证通过考试。"
        if bad == "made_up_target": text["summary"] += " 目标设为450分。"
        if bad == "missing_section": text["sections"].pop()
    model(monkeypatch, saved["preferences"], corrupt)
    client.post(base + "/advice", json={"profile_revision": 1})
    failed = client.get(base + "/advice").json()
    assert failed["status"] == "failed" and len(failed["content"]["sections"]) == 5
    assert failed["input"]["daily_minutes"] == 20
    assert failed["content"]["followup_keys"] == []
    model(monkeypatch, saved["preferences"])
    client.post(base + "/advice", json={"profile_revision": 1})
    assert client.get(base + "/advice").json()["status"] == "ready"


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

"""Daily quotas, source lessons and private paper attempts across real API calls."""
import datetime as dt
import json
import uuid

from app.models.db import session, TENANT_TABLES
from app.models.entities import VocabularyCard
from app.services import cet6_learning as learning, cet6_vocabulary as vocabulary, vocabulary_lessons as lessons
from app.services.cet6_papers import papers
from tests.test_cet6_learning import setup, find_word, word_action
from tests.test_learning_spaces import learner, prepare  # noqa: F401


def target(client, base, amount):
    revision = client.get(base).json()["revision"]
    r = client.post(base + "/word-plan", json={"revision": revision, "daily_new_words": amount, "user_id": "ignored-client-identity"})
    assert r.status_code == 200, r.text
    return r.json()


def introduce(client, base, item):
    detail = client.get(base + "/words/" + item).json()
    card = next(c for c in detail["cards"] if c["sense_id"] == detail["next_review"]["sense_id"])
    card, _ = word_action(client, base, detail, card, "start")
    card, _ = word_action(client, base, detail, card, "reveal", answer="先回忆，再核对")
    card, _ = word_action(client, base, detail, card, "rate", rating="good")
    return detail, card


def test_quota_stable_across_refresh_changes_and_two_tracks_count_once(learner):
    client, _, _, base = setup(learner)
    plan = target(client, base, 3)
    assert len(plan["new_ids"]) == 3
    assert client.get(base + "/word-plan").json()["new_ids"] == plan["new_ids"]
    assert [i["id"] for i in client.get(base + "/words?view=today").json()["items"]] == plan["new_ids"]
    detail, card = introduce(client, base, plan["new_ids"][0])
    card, _ = word_action(client, base, detail, card, "start", mode="spelling")
    card, _ = word_action(client, base, detail, card, "reveal", answer=detail["entry"]["word"])
    word_action(client, base, detail, card, "rate", rating="good")
    after = client.get(base + "/word-plan").json()
    assert after["new_done"] == 1 and after["new_ids"] == plan["new_ids"][1:]
    assert target(client, base, 1)["new_ids"] == []
    raised = target(client, base, 5)
    assert raised["new_done"] == 1 and len(raised["new_ids"]) == 4
    assert raised["new_ids"][:2] == plan["new_ids"][1:]
    assert target(client, base, 0)["new_done"] == 1
    assert client.get(base + "/words?view=today").json()["total"] == 0


def test_review_not_limited_by_new_quota_or_daily_minutes(learner):
    client, user, book, base = setup(learner)
    detail = find_word(client, base)
    _, card = introduce(client, base, detail["entry"]["id"])
    with session() as db:
        row = db.get(VocabularyCard, learning.stable_id("vocab", user, book, f"{detail['entry']['id']}:{card['sense_id']}"))
        row.data = {**row.data, "tracks": {k: {**v, "due_at": "2000-01-01T00:00:00+00:00"} for k, v in row.data["tracks"].items()}}
        db.commit()
    plan = target(client, base, 0)
    assert plan["new_remaining"] == 0 and plan["review_due"] == 1
    assert client.get(base + "/words?view=today").json()["items"][0]["id"] == detail["entry"]["id"]
    detail = client.get(base + "/words/" + detail["entry"]["id"]).json()
    card = detail["cards"][0]
    card, _ = word_action(client, base, detail, card, "start")
    card, _ = word_action(client, base, detail, card, "reveal", answer="证据")
    word_action(client, base, detail, card, "rate", rating="good")
    assert client.get(base + "/word-plan").json()["review_done"] == 1


def test_beijing_day_rollover_carries_pending_and_preserves_active(learner, monkeypatch):
    clock = [dt.datetime(2026, 10, 2, 15, 59, tzinfo=dt.timezone.utc)]
    monkeypatch.setattr(learning, "now", lambda: clock[0])
    client, _, _, base = setup(learner)
    original = target(client, base, 3)
    introduce(client, base, original["new_ids"][0])
    clock[0] += dt.timedelta(minutes=2)
    today = client.get(base + "/word-plan").json()
    assert original["day"] == "2026-10-02" and today["day"] == "2026-10-03"
    assert today["new_done"] == 0 and today["new_ids"][:2] == original["new_ids"][1:]
    detail = client.get(base + "/words/" + today["new_ids"][0]).json()
    card = next(c for c in detail["cards"] if c["sense_id"] == detail["next_review"]["sense_id"])
    word_action(client, base, detail, card, "start")
    target(client, base, 0)
    assert detail["entry"]["id"] in [w["id"] for w in client.get(base + "/words?view=today").json()["items"]]


def test_target_stale_save_cannot_overwrite_other_preferences(learner):
    client, _, _, base = setup(learner)
    initial = client.get(base).json()
    prefs = {**initial["preferences"], "goal": "保留我在另一页填写的目标"}
    assert client.post(base + "/preferences", json={"revision": initial["revision"], "preferences": prefs}).status_code == 200
    assert client.post(base + "/word-plan", json={"revision": initial["revision"], "daily_new_words": 5}).status_code == 409
    target(client, base, 5)
    assert client.get(base).json()["preferences"]["goal"] == prefs["goal"]
    for value in [-1, 201, 1.5]:
        assert client.post(base + "/word-plan", json={"revision": 2, "daily_new_words": value}).status_code == 422


def test_adjacent_cross_mode_recall_records_recent_answer_exposure(learner, monkeypatch):
    clock = [dt.datetime(2026, 10, 3, 1, 0, tzinfo=dt.timezone.utc)]
    monkeypatch.setattr(learning, "now", lambda: clock[0])
    client, _, _, base = setup(learner)
    detail = find_word(client, base, "evidence")
    detail, card = introduce(client, base, detail["entry"]["id"])
    card, _ = word_action(client, base, detail, card, "start", mode="spelling", used_help=False)
    assert card["active"]["used_help"] and "同词" in card["active"]["help_reason"]
    card, _ = word_action(client, base, detail, card, "reveal", answer="evidence")
    card, _ = word_action(client, base, detail, card, "rate", rating="good")
    assert card["last"]["used_help"] and card["tracks"]["spelling"]["independent_due_reviews"] == 0
    clock[0] += dt.timedelta(minutes=11)
    card, _ = word_action(client, base, detail, card, "start", mode="meaning", used_help=False)
    assert not card["active"]["used_help"]


def test_supplemented_senses_keep_original_ids_and_separate_recall_target(learner):
    client, _, _, base = setup(learner)
    for word, meaning in [("approach", "方法"), ("sustainable", "可持续")]:
        original = next(e for e in vocabulary.corpus()["entries"] if e["word"] == word)
        detail = find_word(client, base, word)
        old_ids = {s["id"] for s in original["senses"]}
        assert old_ids < {s["id"] for s in detail["entry"]["senses"]}
        selected = next(s for s in detail["entry"]["senses"] if s["id"] == detail["preferred_sense_id"])
        assert selected["id"] not in old_ids and meaning in selected["definition"]
        assert selected["source_url"].startswith("https://www.merriam-webster.com/")
        assert detail["version"].endswith("+sense-v1")


def test_curated_lessons_match_real_senses_and_do_not_claim_real_exam_examples(learner):
    client, _, _, base = setup(learner)
    for row in lessons.curated()["entries"]:
        entry = next(e for e in vocabulary.entries().values() if e["word"] == row["word"])
        sense = entry["senses"][row["sense_index"]]["id"]
        r = client.get(f"{base}/words/{entry['id']}/lesson", params={"sense_id": sense})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["origin"] == "curated" and "自编" in data["source_note"]
        assert data["check"]["answer"] in "ABCD" and len(set(data["check"]["options"])) == 4
        assert data["sources"][0]["checked_on"] == "2026-10-03"


def test_generated_lesson_is_cached_and_invalid_output_does_not_poison_cache(learner, monkeypatch):
    monkeypatch.setattr(lessons, "LESSON_VERSION", f"lesson-test-{uuid.uuid4()}")
    client, _, _, base = setup(learner)
    detail = find_word(client, base, "ability")
    url = f"{base}/words/{detail['entry']['id']}/lesson?sense_id={detail['cards'][0]['sense_id']}"
    assert client.get(url).json()["status"] == "missing"
    monkeypatch.setattr(lessons, "is_demo", lambda: False)
    calls = []
    async def fail(prompt, **kwargs):
        return '{"focus":"missing required parts"}'
    monkeypatch.setattr(lessons, "llm_complete", fail)
    assert client.post(url, json={}).status_code == 503
    assert client.get(url).json()["status"] == "missing"
    source = lessons.curated()["entries"][0]
    payload = {k: v for k, v in source.items() if k not in {"word", "sense_index", "exam_occurrences"}}
    monkeypatch.setattr("app.services.course_learning_service.context_summary", lambda: {"goal": "PRIVATE_LEARNER_GOAL"})
    async def invalid_review(prompt, **kwargs):
        return '{}' if "TASK=english_word_lesson_review" in prompt else json.dumps(payload)
    monkeypatch.setattr(lessons, "llm_complete", invalid_review)
    assert client.post(url, json={}).status_code == 503
    assert client.get(url).json()["status"] == "missing"
    async def fake(prompt, **kwargs):
        calls.append(prompt)
        assert "PRIVATE_LEARNER_GOAL" not in prompt
        assert not kwargs["allow_mock_fallback"] and not kwargs["allow_model_fallback"]
        return json.dumps({**payload, "focus": "审校后保留的重点"} if "TASK=english_word_lesson_review" in prompt else payload)
    monkeypatch.setattr(lessons, "llm_complete", fake)
    assert client.post(url, json={}).json()["origin"] == "generated"
    assert client.get(url).json()["status"] == "ready"
    assert client.get(url).json()["focus"] == "审校后保留的重点"
    assert "尚未人工校核" in client.get(url).json()["source_note"]
    assert client.post(url, json={}).status_code == 200 and len(calls) == 2


def paper_action(client, url, state, action, **patch):
    draft = {k: state[k] for k in ("answers", "writing", "translation", "reflection", "used_help")}
    body = {**draft, **patch, "revision": state["revision"], "request_id": str(uuid.uuid4()), "action": action, "user_id": "ignored-client-identity"}
    response = client.post(url, json=body)
    assert response.status_code == 200, response.text
    return response.json(), body


def test_official_paper_save_submit_retry_immutable_answers_and_repeat(learner):
    client, user, _, base = setup(learner)
    item = client.get(base + "/papers").json()["items"][0]
    assert item["source_type"].endswith("官方样卷") and "待核验" in item["audio_status"]
    url = base + "/papers/" + item["id"]
    state = client.get(url).json()
    assert len(state["paper"]["questions"]) == 30
    assert all("answer" not in q and "explanation" not in q for q in state["paper"]["questions"])
    state, body = paper_action(client, url, state, "save", answers={"26": "C", "55": "B"}, writing="My first draft.")
    assert client.post(url, json=body).json()["revision"] == state["revision"]
    assert client.get(url).json()["writing"] == "My first draft."
    stale = {**body, "request_id": str(uuid.uuid4()), "writing": "stale window"}
    assert client.post(url, json=stale).status_code == 409
    state, body = paper_action(client, url, state, "submit")
    assert state["first"]["correct"] == 1 and state["first"]["answered"] == 2 and state["first"]["total"] == 30
    assert state["paper"]["questions"][0]["answer"] == "C"
    assert client.post(url, json={**body, "request_id": str(uuid.uuid4()), "revision": state["revision"], "action": "save", "answers": {"26": "D"}}).status_code == 409
    state, _ = paper_action(client, url, state, "save", reflection="第55题把说服力误解成另一个评价。")
    state, _ = paper_action(client, url, state, "restart")
    assert state["answers"] == {} and state["phase"] == "answer"
    assert state["history"][0]["first"]["answers"] == {"26": "C", "55": "B"}
    assert all("answer" not in q for q in state["paper"]["questions"])
    other, _, _ = prepare(client, user, "cet6", "另一门六级")
    assert client.get(f"/api/notebooks/{other['id']}/cet6/papers/{item['id']}").json()["history"] == []
    foreign = client.post("/api/auth/register", json={"email": f"paper-{uuid.uuid4().hex}@example.test", "password": "Cet6-Test-Password!", "name": "另一学生"}).json()
    client.headers["Authorization"] = f"Bearer {foreign['access_token']}"
    assert client.get(url).status_code == 404
    assert client.get(base + "/word-plan").status_code == 404
    assert {"cet6_paper_attempts", "vocabulary_days"} <= set(TENANT_TABLES)


def test_paper_answers_and_word_context_are_validated(learner):
    client, _, _, base = setup(learner)
    item = next(iter(papers()))
    url = base + "/papers/" + item
    state = client.get(url).json()
    body = {"revision": 0, "request_id": str(uuid.uuid4()), "action": "submit", "answers": {}}
    assert client.post(url, json=body).status_code == 422
    for invalid in [{"1": "A"}, {"55": "O"}, {"26": "Z"}]:
        assert client.post(url, json={**body, "answers": invalid}).status_code == 422
    detail = find_word(client, base, "evidence")
    card, _ = word_action(client, base, detail, detail["cards"][0], "collect", paper_id=item, paper_question=50,
        context="The evidence needs careful analysis.", context_note="自己摘录的练习语境")
    assert card["contexts"][0]["paper_id"] == item
    assert "未逐字校核" in card["contexts"][0]["source"]

"""Learner journeys and failure boundaries, using isolated accounts/courses."""
import copy
import datetime as dt
from pathlib import Path
import json
import uuid

from app.models.db import TENANT_TABLES, session
from app.models.entities import VocabularyCard
from app.services import cet6_learning as learning, cet6_vocabulary as vocabulary
from app.services.learning_scope import course_scope
from app.services.course_learning_service import context_summary
from tests.test_learning_spaces import learner, prepare  # noqa: F401


def setup(learner):
    client, user = learner
    book, _, _ = prepare(client, user, "cet6", "六级备考")
    return client, user, book["id"], f"/api/notebooks/{book['id']}/cet6"


def find_word(client, base, word="evidence"):
    response = client.get(base + "/words", params={"q": word})
    assert response.status_code == 200, response.text
    item = next(w for w in response.json()["items"] if w["word"] == word)
    return client.get(base + "/words/" + item["id"]).json()


def word_action(client, base, detail, state, action, **kwargs):
    body = {"revision": state["revision"], "version": detail["version"], "request_id": str(uuid.uuid4()),
            "sense_id": state["sense_id"], "action": action, "user_id": "ignored-client-identity", **kwargs}
    response = client.post(base + "/words/" + detail["entry"]["id"], json=body)
    assert response.status_code == 200, response.text
    return response.json(), body


def practice_action(client, url, state, action, **kwargs):
    body = {"revision": state["revision"], "request_id": str(uuid.uuid4()), "action": action, "user_id": "ignored-client-identity", **kwargs}
    response = client.post(url, json=body)
    assert response.status_code == 200, response.text
    return response.json(), body


def test_goals_optional_editable_isolated_and_survive_new_conversation(learner):
    client, user, book, base = setup(learner)
    defaults = client.get(base).json()
    prefs = {**defaults["preferences"], "goal": "阅读时辨认转折", "daily_minutes": 10, "mode": "foundation", "focus": ["reading"], "target_score": 500, "total_score": 400}
    body = {"revision": 0, "preferences": prefs}
    saved = client.post(base + "/preferences", json=body)
    assert saved.status_code == 200, saved.text
    assert client.post(base + "/preferences", json=body).json()["revision"] == 1
    stale = client.post(base + "/preferences", json={**body, "preferences": {**prefs, "goal": "另一个窗口"}})
    assert stale.status_code == 409
    state = client.get(base).json()
    assert state["recommendation"]["kind"] == "reading" and state["daily_new_limit"] == 5
    assert state["preferences"]["total_score"] == 400
    with course_scope(user, book):
        summary = context_summary()
        assert summary["goal"] == prefs["goal"] and summary["daily_minutes"] == 10
        assert "学习者自述" in summary["support"]
    other, _, _ = prepare(client, user, "cet6", "另一门六级")
    assert client.get(f"/api/notebooks/{other['id']}/cet6").json()["preferences"]["goal"] == ""
    assert client.post(base + "/preferences", json={"revision": 1, "preferences": {**prefs, "daily_minutes": 0}}).status_code == 422
    assert client.post(base + "/preferences", json={"revision": 1, "preferences": {**prefs, "total_score": 400, "listening_score": 200, "reading_score": 200, "writing_translation_score": 100}}).status_code == 422
    response = client.post(f"/api/notebooks/{book}/conversations", json={"user_id": user})
    assert response.status_code in (200, 201), response.text
    assert client.get(base).json()["preferences"] == prefs
    foreign = client.post("/api/auth/register", json={"email": f"cet-other-{uuid.uuid4().hex}@example.test", "password": "Cet6-Test-Password!", "name": "另一学生"}).json()
    client.headers["Authorization"] = f"Bearer {foreign['access_token']}"
    assert client.get(base).status_code == 404
    assert client.post(base + "/preferences", json=body).status_code == 404


def test_corpus_all_visible_forms_provenance_and_search(learner):
    client, _, _, base = setup(learner)
    corpus = vocabulary.corpus()
    assert len(corpus["entries"]) == 8014
    assert len({e["id"] for e in corpus["entries"]}) == 8014
    assert corpus["manifest"]["headword_rows"] == 5377
    assert corpus["manifest"]["declared_headword_rows"] == 5418
    assert len(corpus["manifest"]["missing_definitions"]) == 9
    rows = json.loads((Path(__file__).parents[1] / "app/data/cet6_official_rows_v1.json").read_text(encoding="utf-8"))
    assert {r["source_id"] for r in rows} == {loc["row_id"] for e in corpus["entries"] for loc in e["locators"]}
    for word in ("a", "an", "according to", "ability", "zoology", "zoom", "baby boom"):
        found = find_word(client, base, word)
        assert found["entry"]["source_pages"] and found["entry"]["source_url"].startswith("https://cet.neea.edu.cn/")
    today = client.get(base + "/words?view=today").json()
    assert len(today["items"]) <= 10
    assert all(not w["meaning"] for w in today["items"])
    assert client.get(base + "/words?group=invalid").status_code == 422
    assert "vocabulary_cards" in TENANT_TABLES and "cet6_profiles" in TENANT_TABLES and "cet6_practices" in TENANT_TABLES


def test_context_word_recall_wrong_spelling_early_help_and_idempotent_retry(learner, monkeypatch):
    client, user, book, base = setup(learner)
    time = [dt.datetime(2026, 10, 2, 8, tzinfo=dt.timezone.utc)]
    monkeypatch.setattr(learning, "now", lambda: time[0])
    detail = find_word(client, base)
    state = detail["cards"][0]
    state, _ = word_action(client, base, detail, state, "collect", context="The evidence supports this claim.", context_note="支持结论的证据")
    state, _ = word_action(client, base, detail, state, "start", mode="spelling")
    assert client.get(base).json()["recommendation"]["id"] == detail["entry"]["id"]
    queued = client.get(base + "/words?view=today").json()["items"][0]
    assert queued["id"] == detail["entry"]["id"] and queued["word"] == queued["meaning"] == ""
    state, _ = word_action(client, base, detail, state, "reveal", answer="evidance")
    assert state["active"]["correct"] is False
    state, body = word_action(client, base, detail, state, "rate", rating="good")
    assert state["tracks"]["spelling"]["fsrs"]["state"] == 1
    assert dt.datetime.fromisoformat(state["last"]["due_at"]) == time[0] + dt.timedelta(minutes=1)
    again = client.post(base + "/words/" + detail["entry"]["id"], json=body).json()
    assert again["revision"] == state["revision"] and again["tracks"]["spelling"]["attempts"] == 1
    assert client.post(base + "/words/" + detail["entry"]["id"], json={**body, "rating": "again"}).status_code == 409
    original_due = state["last"]["due_at"]
    state, _ = word_action(client, base, detail, state, "start", mode="spelling")
    state, _ = word_action(client, base, detail, state, "reveal", answer="EVIDENCE")
    state, _ = word_action(client, base, detail, state, "rate", rating="good")
    assert state["last"]["early"] and state["last"]["due_at"] == original_due
    time[0] += dt.timedelta(minutes=11)
    assert client.get(base + "/words/" + detail["entry"]["id"]).json()["next_review"] == {"sense_id": state["sense_id"], "mode": "spelling"}
    state, _ = word_action(client, base, detail, state, "start", mode="spelling")
    state, _ = word_action(client, base, detail, state, "reveal", answer="evidence", used_help=True)
    state, _ = word_action(client, base, detail, state, "rate", rating="good")
    assert state["tracks"]["spelling"]["fsrs"]["state"] == 1 and state["last"]["used_help"]
    assert state["tracks"]["spelling"]["independent_due_reviews"] == 0
    # A meaning recall remains separate and is explicitly self-reported.
    state, _ = word_action(client, base, detail, state, "start", mode="meaning")
    state, _ = word_action(client, base, detail, state, "reveal", answer="证据")
    state, _ = word_action(client, base, detail, state, "rate", rating="good")
    assert state["last"]["basis"] == "学习者自评" and set(state["tracks"]) == {"meaning", "spelling"}
    assert client.get(base + "/words?view=mine").json()["items"][0]["id"] == detail["entry"]["id"]
    restored = client.get(base + "/words/" + detail["entry"]["id"]).json()["cards"][0]
    assert restored["contexts"][0]["text"] == "The evidence supports this claim."
    other, _, _ = prepare(client, user, "cet6", "隔离生词")
    assert client.get(f"/api/notebooks/{other['id']}/cet6/words?view=mine").json()["total"] == 0


def test_reading_word_requires_owned_source_and_exact_quote(learner):
    client, user, book, base = setup(learner)
    reading = client.post(f"/api/notebooks/{book}/reading/examples/original-library-v1").json()
    detail = find_word(client, base, "library")
    question = reading["material"]["questions"][1]
    state, _ = word_action(client, base, detail, detail["cards"][0], "collect", context=reading["material"]["paragraphs"][0], reading_id=reading["id"], question_id=question["id"])
    assert state["contexts"][0]["source"] == reading["material"]["title"]
    assert state["contexts"][0]["question_number"] == 2 and state["contexts"][0]["question_prompt"] == question["prompt"]
    body = {"action": "collect", "revision": state["revision"], "request_id": str(uuid.uuid4()), "sense_id": state["sense_id"], "version": detail["version"], "reading_id": reading["id"], "context": "made up quotation"}
    assert client.post(base + "/words/" + detail["entry"]["id"], json=body).status_code == 422
    invalid_question = {**body, "context": reading["material"]["paragraphs"][0], "question_id": "not-in-this-reading", "request_id": str(uuid.uuid4())}
    assert client.post(base + "/words/" + detail["entry"]["id"], json=invalid_question).status_code == 422
    other, _, _ = prepare(client, user, "cet6", "另外的阅读")
    body.update(revision=0, request_id=str(uuid.uuid4()), context=reading["material"]["paragraphs"][0])
    assert client.post(f"/api/notebooks/{other['id']}/cet6/words/" + detail["entry"]["id"], json=body).status_code == 404


def test_first_attempt_revision_delayed_recall_and_answer_hiding(learner, monkeypatch):
    client, _, _, base = setup(learner)
    time = [dt.datetime(2026, 10, 2, 8, tzinfo=dt.timezone.utc)]
    monkeypatch.setattr(learning, "now", lambda: time[0])
    url = base + "/practice/translation-library-v1"
    state = client.get(url).json()
    assert "reference" not in state["task"] and "checklist" not in state["task"]
    state, _ = practice_action(client, url, state, "draft", answer="Many libraries have longer opening hours.")
    assert client.get(base).json()["recommendation"]["id"] == "translation-library-v1"
    time[0] += dt.timedelta(minutes=12)
    state, body = practice_action(client, url, state, "submit", answer="Many libraries have longer opening hours.")
    assert state["first"]["elapsed_seconds"] == 720
    first = copy.deepcopy(state["first"])
    assert "reference" in state["task"]
    assert client.post(url, json=body).json()["revision"] == state["revision"]
    assert client.post(url, json={**body, "revision": state["revision"], "request_id": str(uuid.uuid4())}).status_code == 409
    state, _ = practice_action(client, url, state, "finish", revision_text="In recent years, many public libraries have extended their opening hours.", reflection="补回了时间范围。")
    assert state["first"] == first and state["phase"] == "done"
    due = state["due_at"]
    state, _ = practice_action(client, url, state, "restart")
    assert "reference" not in state["task"] and "first" not in state["history"][0] and "first" not in state
    state, _ = practice_action(client, url, state, "submit", answer="In recent years, libraries have extended opening hours.")
    state, _ = practice_action(client, url, state, "finish", revision_text="In recent years, many libraries have extended their opening hours.", reflection="再次核对范围。")
    assert state["due_at"] == due and state["last_early"]
    listening = client.get(base + "/practice/listening-library-v1").json()
    assert "speech_text" not in listening["task"] and "answer" not in listening["task"]
    assert listening["task"]["audio_url"].endswith("listening-library-v1.mp3")
    audio = client.get(listening["task"]["audio_url"])
    assert audio.status_code == 200 and audio.headers["content-type"].startswith("audio/")


def test_failed_first_profile_save_leaves_usable_defaults(learner):
    client, _, _, base = setup(learner)
    defaults = client.get(base).json()["preferences"]
    assert client.post(base + "/preferences", json={"revision": 1, "preferences": defaults}).status_code == 409
    assert client.get(base).json()["preferences"] == defaults
    assert client.get(base + "/words?view=today").status_code == 200
    assert client.post(base + "/preferences", json={"revision": 0, "preferences": defaults}).status_code == 200

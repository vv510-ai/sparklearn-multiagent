"""Reading excerpts must remain traceable without inventing mastery or losing scheduling."""
import json
import uuid

import pytest

from app.services import exam_sentence
from tests.test_cet6_learning import setup, find_word, word_action
from tests.test_learning_spaces import learner, prepare  # noqa: F401

PAPER = "cet6-2026-06-1"
KIND = "reading_careful"


def context(client, base):
    exam = client.get(f"{base}/exams/{PAPER}/{KIND}").json()
    return dict(exam_id=PAPER, exam_kind=KIND, exam_question=46, exam_version=exam["version"],
                context="There is evidence that practice helps.", context_note="在此处指证据")


def test_collection_enters_review_without_learning_credit_and_preserves_due_date(learner):
    client, user, _, base = setup(learner)
    detail = find_word(client, base)
    card, body = word_action(client, base, detail, detail["cards"][0], "collect", **context(client, base))
    assert card["queued_at"] and card["tracks"] == {}
    assert client.post(base + "/words/" + detail["entry"]["id"], json=body).json() == card
    card, _ = word_action(client, base, detail, card, "collect", **context(client, base))
    assert len(card["contexts"]) == 1
    plan = client.get(base + "/word-plan").json()
    assert plan["coverage"]["learned"] == 0 and plan["review_due"] == 1
    assert client.get(base).json()["stats"]["word_due"] == 1
    round_ = client.post(base + "/word-rounds", json={"kind": "review", "request_id": str(uuid.uuid4())}).json()
    assert round_["total"] == 1 and round_["items"][0]["entry_id"] == detail["entry"]["id"]
    card, _ = word_action(client, base, detail, card, "start")
    card, _ = word_action(client, base, detail, card, "reveal")
    card, _ = word_action(client, base, detail, card, "rate", rating="good")
    assert not card["queued_at"] and card["tracks"]["meaning"]["attempts"] == 1
    assert client.get(base + "/word-rounds/" + round_["id"]).json()["finished"]
    due = card["tracks"]["meaning"]["due_at"]
    card, _ = word_action(client, base, detail, card, "collect", **context(client, base))
    assert not card["queued_at"] and card["tracks"]["meaning"]["due_at"] == due
    assert len(card["contexts"]) == 1
    other, _, _ = prepare(client, user, "cet6", "另一门六级")
    other_base = f"/api/notebooks/{other['id']}/cet6"
    assert client.get(other_base).json()["stats"]["word_due"] == 0
    assert not find_word(client, other_base)["cards"][0]["contexts"]


def test_editing_exam_note_keeps_one_excerpt_and_preserves_other_questions(learner):
    client, _, _, base = setup(learner)
    detail = find_word(client, base)
    excerpt = context(client, base)
    card, first_request = word_action(client, base, detail, detail["cards"][0], "collect", **excerpt)
    queued = card["queued_at"]
    card, _ = word_action(client, base, detail, card, "collect", **(excerpt | {"context_note": "修改后的笔记"}))
    assert len(card["contexts"]) == 1 and card["contexts"][0]["note"] == "修改后的笔记"
    assert card["queued_at"] == queued and card["tracks"] == {}
    client.post(base + "/words/" + detail["entry"]["id"], json=first_request)
    restored = client.get(base + "/words/" + detail["entry"]["id"]).json()["cards"][0]
    assert restored["contexts"][0]["note"] == "修改后的笔记"
    card, _ = word_action(client, base, detail, card, "collect", **(excerpt | {"exam_question": 47}))
    assert {c["exam_question"] for c in card["contexts"]} == {46, 47}


@pytest.mark.parametrize("patch,status", [({"exam_question": 26}, 422), ({"exam_version": "old"}, 409),
    ({"exam_id": "missing"}, 404), ({"context": ""}, 422), ({"reading_id": "other"}, 422), ({"exam_id": ""}, 422)])
def test_invalid_excerpt_source_does_not_collect(learner, patch, status):
    client, _, _, base = setup(learner)
    detail = find_word(client, base)
    body = dict(action="collect", revision=0, request_id=str(uuid.uuid4()), version=detail["version"],
                sense_id=detail["cards"][0]["sense_id"], **(context(client, base) | patch))
    result = client.post(base + "/words/" + detail["entry"]["id"], json=body)
    assert result.status_code == status, result.text
    assert not find_word(client, base)["cards"][0]["collected"]
    assert client.get(base).json()["stats"]["word_due"] == 0


def test_help_flag_is_monotonic_until_restart_and_frozen_on_submission(learner):
    client, _, _, base = setup(learner)
    path = f"{base}/exams/{PAPER}/{KIND}"
    state = client.get(path).json()
    def act(action, help=False):
        nonlocal state
        response = client.post(path, json=dict(action=action, revision=state["revision"], version=state["version"],
            request_id=str(uuid.uuid4()), used_help=help, answers={"46": "A"}, allow_incomplete=True))
        assert response.status_code == 200, response.text
        state = response.json()
    act("save", True)
    act("save", False)
    assert state["used_help"]
    act("submit")
    assert state["first"]["used_help"]
    act("restart")
    assert not state.get("used_help") and not state.get("first")


def test_sentence_gateway_quotes_no_answers_and_rejects_hallucinated_evidence(learner, monkeypatch):
    client, _, _, base = setup(learner)
    request = dict(version=context(client, base)["exam_version"], question=46, user_id="ignored-bff-identity",
                   sentence="Although it was difficult, she managed to finish it.",
                   paragraph="Although it was difficult, she managed to finish it.")
    output = dict(main_clause="she managed to finish it", clauses=[dict(quote="Although it was difficult", role="让步", explanation="虽然有困难")],
                  translation="虽然很困难，她还是设法完成了。", connection="让步关系", check_question="她完成了吗？", check_answer="完成了。")
    calls = []
    async def model(prompt, **kwargs):
        calls.append(prompt)
        assert kwargs["allow_mock_fallback"] is False
        return json.dumps(output, ensure_ascii=False)
    monkeypatch.setattr(exam_sentence, "is_demo", lambda: False)
    monkeypatch.setattr(exam_sentence, "llm_complete", model)
    path = f"{base}/exams/{PAPER}/{KIND}/sentence"
    result = client.post(path, json=request)
    assert result.status_code == 200, result.text
    assert result.json()["content"] == output
    assert "option_reasons" not in calls[0] and "submission_id" not in calls[0]
    assert client.post(path, json={**request, "sentence": "This sentence is absent."}).status_code == 422
    output["clauses"][0]["quote"] = "An invented phrase"
    assert client.post(path, json=request).status_code == 503
    monkeypatch.setattr(exam_sentence, "is_demo", lambda: True)
    assert client.post(path, json=request).status_code == 503
    foreign = client.post("/api/auth/register", json={"email": f"excerpt-{uuid.uuid4().hex}@example.test", "password": "Excerpt-Test-Password!", "name": "其他学生"}).json()
    client.headers["Authorization"] = f"Bearer {foreign['access_token']}"
    assert client.post(path, json=request).status_code == 404

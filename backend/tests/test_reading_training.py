"""Reading journeys: ownership, exact source evidence, recovery and delayed recall."""
import copy
import datetime as dt
import uuid

from app.models.db import TENANT_TABLES
from app.services import reading_training as reading
from tests.test_learning_spaces import learner, prepare  # noqa: F401


def start(client, user):
    book, _, _ = prepare(client, user, "cet6", "六级阅读")
    url = f"/api/notebooks/{book['id']}/reading"
    result = client.post(url + "/examples/original-library-v1")
    assert result.status_code == 200, result.text
    return url, result.json(), book["id"]


def operation(client, url, state, action, **kwargs):
    body = dict(request_id=str(uuid.uuid4()), revision=state["revision"], version=state["version"], action=action, **kwargs)
    result = client.post(url + "/" + state["id"], json=body)
    assert result.status_code == 200, result.text
    return result.json(), body


def full_first(client, url, state):
    material = reading.examples()["original-library-v1"]
    answers = {q["id"]: q["answer"] for q in material["questions"]}
    answers[material["questions"][0]["id"]] = (answers[material["questions"][0]["id"]] + 1) % 4
    state, _ = operation(client, url, state, "submit", answers=answers, uncertain=[material["questions"][1]["id"]], elapsed_seconds=120)
    state, _ = operation(client, url, state, "reflect", note="把使用量误认为学习效果；重新对照原文。")
    drill = {q["id"]: q["drill"]["answer"] for q in material["questions"] if q["id"] in state["focus_ids"]}
    state, _ = operation(client, url, state, "drill", answers=drill)
    state, _ = operation(client, url, state, "finish")
    return state


def test_answers_hidden_draft_recovery_first_immutable_and_retry(learner):
    client, user = learner
    url, state, book = start(client, user)
    before = client.get(f"/api/profile/{user}?notebook_id={book}").json()
    assert "reading_trainings" in TENANT_TABLES
    assert state["demo"] and state["first"] is None and "feedback" not in state
    assert all("answer" not in q and "evidence" not in q and "drill" not in q for q in state["material"]["questions"])
    q = state["material"]["questions"][0]["id"]
    state, body = operation(client, url, state, "draft", answers={q: 2}, uncertain=[q])
    assert client.get(url + "/" + state["id"]).json()["draft"] == {q: 2}
    assert client.post(url + "/" + state["id"], json=body).json()["revision"] == state["revision"]
    stale = {**body, "request_id": str(uuid.uuid4()), "answers": {q: 1}}
    assert client.post(url + "/" + state["id"], json=stale).status_code == 409
    incomplete = {**stale, "revision": state["revision"], "action": "submit"}
    assert client.post(url + "/" + state["id"], json=incomplete).status_code == 422
    state = full_first(client, url, state)
    assert state["first"]["correct"] == 4 and state["first"]["elapsed_seconds"] == 120
    assert state["phase"] == "done" and state["note"]
    assert len(state["focus_ids"]) == 2
    overwritten = {**incomplete, "revision": state["revision"], "answers": {q["id"]: q["answer"] for q in reading.examples()["original-library-v1"]["questions"]}}
    assert client.post(url + "/" + state["id"], json=overwritten).status_code == 409
    assert client.get(url + "/" + state["id"]).json()["first"] == state["first"]
    after = client.get(f"/api/profile/{user}?notebook_id={book}").json()
    assert {k: v for k, v in after.items() if k != "_updated_at"} == {k: v for k, v in before.items() if k != "_updated_at"}


def test_recall_early_does_not_advance_and_due_correct_wrong_scheduling(learner, monkeypatch):
    client, user = learner
    clock = [dt.datetime(2026, 10, 2, 9, tzinfo=dt.timezone.utc)]
    monkeypatch.setattr(reading, "utc_now", lambda: clock[0])
    url, state, _ = start(client, user)
    state = full_first(client, url, state)
    first = copy.deepcopy(state["first"])
    schedule = copy.deepcopy(state["review"])
    state, _ = operation(client, url, state, "start_review")
    assert "feedback" not in state and state["active_review"]["early"]
    assert all("answer" not in q for q in state["exercises"])
    answers = {q["id"]: q["recall"]["answer"] for q in reading.examples()["original-library-v1"]["questions"] if q["id"] in state["focus_ids"]}
    state, _ = operation(client, url, state, "review_draft", answers={next(iter(answers)): next(iter(answers.values()))})
    assert client.get(url + "/" + state["id"]).json()["exercise_answers"] == state["exercise_answers"]
    state, _ = operation(client, url, state, "review_submit", answers=answers)
    assert state["review"]["due_at"] == schedule["due_at"] and state["history"][-1]["early"]
    assert state["review"]["fsrs"] == schedule["fsrs"]
    assert state["review"]["attempts"] == schedule["attempts"] + 1
    clock[0] += dt.timedelta(days=1, seconds=1)
    assert client.get(url).json()["due"] == 1
    state, _ = operation(client, url, state, "start_review")
    state, body = operation(client, url, state, "review_submit", answers=answers)
    assert state["review"]["scheduler"].startswith("fsrs-6/")
    assert state["history"][-1]["effective_rating"] == "good"
    assert dt.datetime.fromisoformat(state["review"]["due_at"]) > clock[0]
    repeated = client.post(url + "/" + state["id"], json=body).json()
    assert len(repeated["history"]) == 2 and repeated["review"] == state["review"]
    assert client.get(url).json()["due"] == 0
    clock[0] += dt.timedelta(days=3, seconds=1)
    state, _ = operation(client, url, state, "start_review")
    wrong = {q["id"]: (answers[q["id"]] + 1) % len(q["options"]) for q in state["exercises"]}
    state, _ = operation(client, url, state, "review_submit", answers=wrong)
    assert state["history"][-1]["effective_rating"] == "again"
    assert dt.timedelta(0) < dt.datetime.fromisoformat(state["review"]["due_at"]) - clock[0] <= dt.timedelta(minutes=10)
    assert state["first"] == first


def test_private_import_exact_evidence_validation_and_original_recall(learner):
    client, user = learner
    url, _, _ = start(client, user)
    material = copy.deepcopy(reading.examples()["original-bus-v1"])
    material.update(title="用户导入材料", source="用户提供：练习册页码 24；验收样本", source_type="past_paper")
    material["questions"] = material["questions"][:1]
    q = material["questions"][0]
    q["drill"] = q["recall"] = None
    payload = {"request_id": str(uuid.uuid4()), "material": material}
    response = client.post(url + "/import", json=payload)
    assert response.status_code == 200, response.text
    state = response.json()
    assert not state["demo"] and state["material"]["source"] == material["source"]
    assert client.post(url + "/import", json=payload).json()["id"] == state["id"]
    assert len(client.get(url).json()["items"]) == 2
    bad = copy.deepcopy(payload)
    bad["request_id"] = str(uuid.uuid4())
    bad["material"]["questions"][0]["evidence"]["quote"] = "This evidence is not in the passage."
    assert client.post(url + "/import", json=bad).status_code == 422
    bad = copy.deepcopy(payload)
    bad["material"]["source_url"] = "javascript:alert(1)"
    assert client.post(url + "/import", json=bad).status_code == 422
    bad = copy.deepcopy(payload)
    bad["material"]["questions"][0]["options"][1] = q["options"][0]
    assert client.post(url + "/import", json=bad).status_code == 422
    state, _ = operation(client, url, state, "submit", answers={q["id"]: q["answer"]})
    state, _ = operation(client, url, state, "reflect")
    assert state["exercises"][0]["kind"] == "original"
    state, _ = operation(client, url, state, "drill", answers={q["id"]: q["answer"]})
    state, _ = operation(client, url, state, "finish")
    assert client.get(url).json()["private_completed"] == 1
    state, _ = operation(client, url, state, "start_review")
    assert state["exercises"][0]["kind"] == "original"


def test_reading_requires_auth_and_isolated_course_account(learner):
    client, user = learner
    url, state, _ = start(client, user)
    other_book, _, _ = prepare(client, user, "cet6", "另一门六级课")
    other_url = f"/api/notebooks/{other_book['id']}/reading"
    assert not client.get(other_url).json()["items"]
    assert client.get(other_url + "/" + state["id"]).status_code == 404
    py, _, _ = prepare(client, user, "python", "Python")
    assert client.get(f"/api/notebooks/{py['id']}/reading").status_code == 404
    headers = dict(client.headers)
    client.headers.pop("authorization", None)
    assert client.get(url).status_code == 401
    assert client.get(url + "/" + state["id"]).status_code == 401
    client.headers.update(headers)
    other = client.post("/api/auth/register", json={"email": f"reading-{uuid.uuid4().hex}@example.test", "password": "Reading-Private-2026!", "name": "另一账户"}).json()
    client.headers["Authorization"] = "Bearer " + other["access_token"]
    assert client.get(url).status_code == 404
    assert client.get(url + "/" + state["id"]).status_code == 404
    assert client.post(url + "/examples/original-library-v1").status_code == 404


def test_all_missed_and_uncertain_questions_recur_and_help_is_sticky(learner, monkeypatch):
    client, user = learner
    clock = [dt.datetime(2026, 10, 2, 9, tzinfo=dt.timezone.utc)]
    monkeypatch.setattr(reading, "utc_now", lambda: clock[0])
    url, state, _ = start(client, user)
    material = reading.examples()["original-library-v1"]
    wrong = {q["id"]: (q["answer"] + 1) % 4 for q in material["questions"]}
    state, _ = operation(client, url, state, "draft", answers=wrong, used_help=True, user_id=user, elapsed_seconds=35)
    assert state["elapsed_seconds"] == 35
    state, _ = operation(client, url, state, "submit", answers=wrong, used_help=False, user_id=user)
    assert state["first"]["used_help"] is True
    assert len(state["focus_ids"]) == 5
    state, _ = operation(client, url, state, "reflect")
    assert len(state["exercises"]) == 2
    state, _ = operation(client, url, state, "drill", answers={q["id"]: q["drill"]["answer"] for q in material["questions"][:2]})
    state, _ = operation(client, url, state, "finish")
    clock[0] += dt.timedelta(days=1, seconds=1)
    schedule = copy.deepcopy(state["review"])
    state, _ = operation(client, url, state, "start_review")
    assert len(state["exercises"]) == 5 and not state["used_help"]
    answers = {q["id"]: q["recall"]["answer"] for q in material["questions"]}
    state, _ = operation(client, url, state, "review_draft", answers=answers, used_help=True)
    state, _ = operation(client, url, state, "review_submit", answers=answers, used_help=False)
    assert state["review"]["independent_due_reviews"] == schedule["independent_due_reviews"]
    assert state["history"][-1]["effective_rating"] == "again"
    assert dt.datetime.fromisoformat(state["review"]["due_at"]) - clock[0] <= dt.timedelta(minutes=10)
    assert state["history"][-1]["used_help"] is True
    state, _ = operation(client, url, state, "start_review")
    assert not state["used_help"]
    assert "answers" not in state["first"] and not state["draft"] and not state["note"]
    assert all("answers" not in h for h in state["history"])
    assert "last_review" not in state and "feedback" not in state

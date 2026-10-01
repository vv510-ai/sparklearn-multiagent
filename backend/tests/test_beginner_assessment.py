"""Short entry checks and readable review must retain independent evidence."""
import copy

from app.models.db import session
from app.models.entities import AssessmentSession
from tests.test_learning_spaces import learner, prepare_custom_assessment_fixture as prepare  # noqa: F401


def submit(client, state, status="answered", choice="A"):
    q = state["question"]
    result = client.post(f"/api/assessment/{state['id']}/answers", json={
        "revision": state["revision"], "question_id": q["id"], "status": status,
        "choice": choice if status == "answered" and q["type"] == "single" else None,
        "choices": [choice] if status == "answered" and q["type"] == "multiple" else [],
    })
    assert result.status_code == 200, result.text
    return result.json()


def test_short_custom_entry_keeps_unchecked_modules_pending_and_can_extend(learner):
    client, user = learner
    _, survey, _ = prepare(client, user, "cet6", "大学英语六级")
    state = client.post("/api/assessment/start", json={"survey": survey, "mode": "screening"}).json()
    assert state["maximum"] == 12
    seen = set()
    while state["question"]:
        q = state["question"]
        assert "提交" in q["instruction"]
        assert not {"answer", "explain", "transcript"} & q.keys()
        seen.add(q["id"])
        state = submit(client, state)
    assert len(seen) == state["answered"] == 12
    assert state["report"]["coverage"] == 4
    assert sum(s["status"] == "unmeasured" for s in state["report"]["skills"]) == 2
    report = copy.deepcopy(state["report"])
    state = client.post(f"/api/assessment/{state['id']}/extend", json={"revision": state["revision"]}).json()
    while state["question"]:
        assert state["question"]["id"] not in seen
        seen.add(state["question"]["id"])
        state = submit(client, state, "dont_know")
        if state["status"] == "active":
            # Pending continuation must not reveal new reference answers early.
            assert state["report"] == report
    assert state["answered"] == 18 and state["report"]["coverage"] == 6


def test_old_report_is_enriched_from_its_own_snapshot_without_rescoring(learner):
    client, user = learner
    book, survey, _ = prepare(client, user, "cet6", "大学英语六级")
    state = client.post("/api/assessment/start", json={"survey": survey, "mode": "screening"}).json()
    first_question = copy.deepcopy(state["question"])
    state = submit(client, state, choice="B")
    state = submit(client, state, "skipped")
    while state["question"]:
        state = submit(client, state, "dont_know")
    report = state["report"]
    assert report["explanations"][0]["options"] == first_question["options"]
    assert report["explanations"][0]["learner_answer"] == "B. " + first_question["options"][1]
    assert report["explanations"][1]["learner_answer"] == "暂时跳过（不计错）"
    skipped_kp = report["explanations"][1]["kp"]
    skill = next(s for s in report["skills"] if s["kp"] == skipped_kp)
    assert skill["attempts"] == 2 and skill["status"] == "unmeasured"
    with session() as db:
        row = db.get(AssessmentSession, state["id"])
        value = copy.deepcopy(row.data)
        for item in value["report"]["explanations"]:
            for key in ("options", "learner_answer", "topic", "instruction", "audio_url"):
                item.pop(key, None)
        row.data = value
        db.commit()
    restored = client.get(f"/api/assessment?notebook_id={book['id']}").json()["assessment"]
    assert restored["report"] == report
    with session() as db:
        assert "learner_answer" not in db.get(AssessmentSession, state["id"]).data["report"]["explanations"][0]


def test_short_entry_honors_selected_modules_and_retains_multiple_choices(learner):
    client, user = learner
    _, survey, _ = prepare(client, user, "cet6", "大学英语六级")
    survey["target_kps"] = ["cet6_vocab"]
    state = client.post("/api/assessment/start", json={"survey": survey, "mode": "screening"}).json()
    assert state["maximum"] == 3
    multiple_id = None
    while state["question"]:
        q = state["question"]
        if q["type"] == "multiple":
            multiple_id = q["id"]
            result = client.post(f"/api/assessment/{state['id']}/answers", json={
                "revision": state["revision"], "question_id": q["id"], "status": "answered", "choices": ["A", "C"]})
            assert result.status_code == 200
            state = result.json()
        else:
            state = submit(client, state)
    assert multiple_id is not None
    item = next(i for i in state["report"]["explanations"] if i["id"] == multiple_id)
    assert item["learner_answer"] == f"A. {item['options'][0]}；C. {item['options'][2]}"
    assert "可多选" in item["instruction"]

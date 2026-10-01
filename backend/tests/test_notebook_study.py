"""Source-based course journey: authentic material, isolation and resumable work."""
import copy
import uuid
from app.data.study_paths import PATHS, VERSION
from app.models.db import session, TENANT_TABLES
from app.models.entities import LearningSpace, NotebookStudy
from app.services import study_paths
from app.services.learning_scope import course_scope
from tests.test_learning_spaces import learner  # noqa: F401


def create(client, user, key):
    notebook = client.post("/api/notebooks", json={"user_id": user, "title": PATHS[key]["title"]}).json()
    response = client.post(f"/api/notebooks/{notebook['id']}/learning/prepare", json={"title": notebook["title"], "course_key": key})
    assert response.status_code == 200, response.text
    return notebook["id"], response.json()


def test_all_five_courses_offer_material_tasks_without_default_original_bank(learner):
    client, user = learner
    assert len(PATHS["cet6"]["units"]) >= 25
    for key in PATHS:
        notebook, course = create(client, user, key)
        assert course["question_count"] == 0 and not course["practice_available"]
        assert course["study_path"]["course"] == key
        response = client.get(f"/api/notebooks/{notebook}/study")
        assert response.status_code == 200, response.text
        units = response.json()["path"]["units"]
        assert len(units) == len(PATHS[key]["units"])
        assert all(u["source"]["url"].startswith("https://") and u["location"] and u["task"] and u["check"] for u in units)
        blocked = client.post("/api/assessment/start", json={"survey": {"notebook_id": notebook, "course_revision": course["revision"]}, "mode": "screening"})
        assert blocked.status_code == 409 and "原教材" in blocked.text
    assert client.post("/api/assessment/start", json={}).status_code == 409
    assert "notebook_studies" in TENANT_TABLES


def test_notebook_progress_auth_ownership_revisions_drafts_and_mastery(learner):
    client, user = learner
    first, course = create(client, user, "cet6")
    second, _ = create(client, user, "cet6")
    url = f"/api/notebooks/{first}/study"
    auth = dict(client.headers)
    client.headers.pop("authorization", None)
    assert client.get(url).status_code == 401
    assert client.post(url + "/exam-map", json={}).status_code == 401
    client.headers.update(auth)
    before = client.get(f"/api/profile/{user}?notebook_id={first}").json()
    payload = dict(revision=0, version=VERSION, read=True, practiced=True, checked=True, completed=True, notes="已经核对官方题型，先提高阅读。", next_review="2026-10-03")
    assert client.post(url + "/unknown", json=payload).status_code == 404
    assert client.post(url + "/exam-map", json={**payload, "notes": ""}).status_code == 422
    response = client.post(url + "/exam-map", json=payload)
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["revision"] == 1
    assert client.post(url + "/exam-map", json=payload).json() == saved
    assert client.post(url + "/exam-map", json={**payload, "notes": "stale"}).status_code == 409
    assert client.get(url).json()["progress"] == saved
    assert client.get(f"/api/notebooks/{second}/study").json()["progress"]["units"] == {}
    after = client.get(f"/api/profile/{user}?notebook_id={first}").json()
    assert {k: v for k, v in after.items() if k != "_updated_at"} == {k: v for k, v in before.items() if k != "_updated_at"}
    other = client.post("/api/auth/register", json={"email": f"path-other-{uuid.uuid4().hex}@example.test", "password": "Path-QA-Password!", "name": "另一账号"}).json()
    client.headers["Authorization"] = "Bearer " + other["access_token"]
    assert client.get(url).status_code == 404
    assert client.post(url + "/exam-map", json={**payload, "revision": 1}).status_code == 404


def test_old_original_snapshot_keeps_history_but_is_not_a_default_rag_source(learner, monkeypatch):
    from app.data.cet6_course import build_course
    from app.rag.retriever import retrieve
    from app.services.course_learning_service import public_course
    from app.services.assessment_service import question_bank
    client, user = learner
    notebook, _ = create(client, user, "cet6")
    original = build_course()
    original.update(revision="historical-course-revision", source_ids=[], sources=[])
    with session() as db:
        db.get(LearningSpace, notebook).course = copy.deepcopy(original)
        db.commit()
    public = public_course(original)
    assert not public["textbook"] and public["question_count"] == 0
    assert public["study_path"]["course"] == "cet6"
    monkeypatch.setattr("app.services.textbook_service.course_textbook_chunks", lambda *_: (_ for _ in ()).throw(AssertionError("original book requested")))
    with course_scope(user, notebook):
        assert retrieve("六级词汇", user_id=user, source_ids=[]) == []
        assert retrieve("六级词汇", user_id=user, source_ids=["__course__"]) == []
        assert question_bank() == []
    with session() as db:
        assert db.get(LearningSpace, notebook).course == original


def test_reading_historical_builtin_report_does_not_rebuild_original_materials(learner, monkeypatch):
    from app.models.entities import AssessmentSession
    from app.services import assessment_service
    from tests.test_learning_spaces import prepare_custom_assessment_fixture, finish
    client, user = learner
    book, survey, _ = prepare_custom_assessment_fixture(client, user, "cet6", "大学英语六级")
    old = finish(client, survey, False)
    with session() as db:
        space = db.get(LearningSpace, book["id"])
        space.course = {**space.course, "kind": "cet6"}
        row = db.get(AssessmentSession, old["id"])
        row.data = {**row.data, "course_snapshot": {**row.data["course_snapshot"], "kind": "cet6"}}
        original = copy.deepcopy(row.data)
        db.commit()
    def forbidden(*args):
        raise AssertionError("Reading a historical publisher course must not rebuild its materials")
    monkeypatch.setattr(assessment_service, "_refresh_from_practice", forbidden)
    restored = client.get(f"/api/assessment?notebook_id={book['id']}")
    assert restored.status_code == 200, restored.text
    assert restored.json()["assessment"]["report"] == old["report"]
    with session() as db:
        assert db.get(AssessmentSession, old["id"]).data == original
    assert client.post(f"/api/assessment/{old['id']}/practice", json={"kp": "cet6_listening"}).status_code == 409

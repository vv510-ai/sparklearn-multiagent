"""English pilots: real media integrity, answer boundaries and withdrawal."""
import copy
import hashlib
import json
import uuid
import pytest
from app.services import course_library as library
from app.models.db import session
from app.models.entities import LearningSpace
from app.rag.library_index import retrieve_release
from tests.test_learning_spaces import learner  # noqa: F401


def bundle():
    b = json.loads(library.ENGLISH_BUNDLE_PATH.read_text(encoding="utf-8"))
    b["release_id"] = "english-test-" + uuid.uuid4().hex
    b["course_id"] = b["release_id"]
    for section in b["textbook"]["sections"]:
        section["url"] = f"/api/library/releases/{b['release_id']}/sections/{section['id']}"
    return b


def enroll(client):
    b = bundle(); library.publish(b)
    study = client.post("/api/library/enroll", json={"release_id": b["release_id"]}).json()
    return b, study, f"/api/library/studies/{study['id']}/lessons/invitation"


def test_all_scenes_audio_and_cues_are_actual_validated_media():
    b = bundle(); library.validate_bundle(b)
    assert len(b["lessons"]) == 3
    for l in b["lessons"]:
        assert len(l["scene"]["lines"]) == 8
        assert 30 < l["scene"]["audio"]["duration"] < 90
        assert l["work_reference"] not in str(b["textbook"]["sections"])
    for mutate in (lambda x: x["lessons"][0]["scene"]["audio"].update(file="../secret.wav"),
                   lambda x: x["lessons"][0]["scene"]["audio"].update(sha256="0"*64),
                   lambda x: x["lessons"][0]["scene"]["lines"][0].update(text="mismatched transcript"),
                   lambda x: x["lessons"][0]["scene"]["audio"]["cues"][1].update(start=0)):
        invalid=copy.deepcopy(b); mutate(invalid)
        with pytest.raises(ValueError): library.validate_bundle(invalid)


def test_playback_and_reference_records_do_not_grant_mastery(learner):
    client,user=learner
    b,study,url=enroll(client)
    l=client.get(url).json()
    assert "work_reference" not in l and "answer" not in l["question"]
    assert l["sources"][0]["source_type"] == "platform_original"
    assert "file" not in l["scene"]["audio"]
    assert client.post(url,json={"action":"reveal_work","revision":0}).status_code == 422
    assert client.post(url,json={"action":"listen","revision":0,"audio_sha256":"0"*64}).status_code == 422
    saved=client.post(url,json={"action":"listen","revision":0,"audio_sha256":l["scene"]["audio"]["sha256"]}).json()
    assert saved["progress"]["lessons"]["invitation"]["listening"]["status"] == "client_reported"
    assert client.post(url,json={"action":"read","revision":0}).status_code == 409
    for action,extra in [("work",{"work":"Could we meet at ten thirty?"}), ("reveal_work",{}), ("work",{"work":"Revised with reference", "assisted":False})]:
        response=client.post(url,json={"action":action,"revision":saved["revision"],**extra})
        assert response.status_code == 200,response.text
        saved=response.json()
    assert saved["progress"]["lessons"]["invitation"]["work"]["assisted"]
    assert client.get(url).json()["work_reference"] == b["lessons"][0]["work_reference"]
    with session() as db:
        space=db.get(LearningSpace,study["notebook_id"])
        assert space.data["knowledge_mastery"] == {}
        assert space.course["kind"] == "english_scenes"
    token=client.headers.pop("Authorization")
    assert client.get(l["scene"]["audio"]["url"]).status_code == 401
    client.headers["Authorization"]=token
    other=client.post("/api/auth/register",json={"email":uuid.uuid4().hex+"@example.test","password":"Course-Test-Password!","name":"隔离"}).json()
    client.headers["Authorization"]="Bearer "+other["access_token"]
    assert client.get(url).status_code == 404
    assert client.post(url,json={"action":"listen","revision":saved["revision"],"audio_sha256":l["scene"]["audio"]["sha256"]}).status_code == 404


def test_range_source_rag_and_withdrawal_share_release_boundary(learner):
    client,_=learner
    b,study,url=enroll(client)
    l=client.get(url).json(); media=l["scene"]["audio"]["url"]
    response=client.get(media,headers={"Range":"bytes=0-127"})
    assert response.status_code == 206 and len(response.content) == 128
    assert response.content.startswith(b"RIFF") and response.headers["cache-control"] == "private, no-store"
    source=l["sources"][0]["url"]
    assert client.get(source).text.endswith(l["sources"][0]["text"])
    hits=retrieve_release(b["release_id"],"Would four thirty work for you?",kp="english_scene_invitation")
    assert hits and all(h["source_type"] == "platform_original" for h in hits)
    assert all(h["course_release_id"] == b["release_id"] for h in hits)
    from app.rag.citation import build_context
    _, evidence = build_context(hits)
    assert all(item["source_type"] == "platform_original" for item in evidence)
    library.withdraw(b["release_id"],"test removal")
    for path in (media,source,url): assert client.get(path).status_code == 410
    assert client.post(url,json={"action":"listen","revision":0,"audio_sha256":l["scene"]["audio"]["sha256"]}).status_code == 410
    assert client.get(f"/api/library/studies/{study['id']}").json()["withdrawn"]

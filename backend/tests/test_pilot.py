from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app import config
from app.main import app
from app.models.db import init_db, session
from app.models.entities import AuthAccount, PilotObservation, PilotStudy, User
from app.services import pilot_service as pilot


@pytest.fixture
def study():
    init_db();owner="pilot-test-"+uuid.uuid4().hex
    result=pilot.create_study(owner,pilot.StudyInput(title="测试课程试点",course="数据结构",mode="demo",protocol="匿名配对前后测，不将演示数据当作真实效果。"))
    yield owner,result["id"]
    with session() as db:
        db.execute(delete(PilotObservation).where(PilotObservation.user_id==owner))
        db.execute(delete(PilotStudy).where(PilotStudy.user_id==owner))
        db.execute(delete(User).where(User.id==owner));db.commit()


def row(participant="anon-001",phase="pre",correct=4,kp="binary_tree",arm="intervention",**extra):
    return {"participant":participant,"phase":phase,"knowledge_point":kp,"arm":arm,
            "correct":correct,"total":10,"independent":10,"minutes":12,
            "observed_on":{"pre":"2020-08-01","post":"2020-08-29","delayed":"2020-09-05"}[phase],
            "consent":True,"provenance":"synthetic integration fixture","data_kind":"demo","errors":[],**extra}


def put(study, rows):return pilot.import_observations(*study,pilot.ImportInput(observations=rows))


def test_missing_data_stays_null_and_pairs_same_student_same_topic(study):
    assert pilot.study_report(*study)["independent_rate"] is None
    put(study,[row(),row(phase="post",correct=7),row("anon-002",arm="control"),row("anon-002",phase="post",correct=5,arm="control")])
    report=pilot.study_report(*study)
    assert report["participants"]==2
    assert report["difference_in_gains"]==pytest.approx(.2)
    assert all(s["mean_accuracy"] is None and s["n"]==0 for s in report["summary"] if s["phase"]=="delayed")
    put(study,[row("anon-003",correct=0,kp="tree"),row("anon-003",phase="post",correct=10,kp="sorting")])
    assert pilot.study_report(*study)["paired"][0]["n"]==1


def test_duplicate_idempotency_and_conflict_are_atomic(study):
    assert put(study,[row()])["inserted"]==1
    assert put(study,[row()])["duplicates"]==1
    with pytest.raises(HTTPException) as caught:put(study,[row("anon-new"),row(correct=8)])
    assert caught.value.status_code==409
    assert pilot.study_report(*study)["participants"]==1


@pytest.mark.parametrize("rows", [
    [row(data_kind="field")],
    [row(),row(phase="post",arm="control")],
    [row(phase="post"),row(phase="delayed",observed_on="2020-08-29")],
    [row(),row(phase="post",observed_on="2020-07-01")],
])
def test_mixed_provenance_group_and_invalid_dates_rejected(study,rows):
    with pytest.raises(HTTPException):put(study,rows)
    assert pilot.study_report(*study)["observations"]==[]


@pytest.mark.parametrize("changes",[{"consent":False},{"correct":11},{"independent":11},
                                      {"observed_on":"2099-01-01"},{"user_id":"other"},{"participant":"姓名 张三"}])
def test_invalid_observations_fail_validation(changes):
    with pytest.raises(ValueError):pilot.Observation.model_validate(row(**changes))


def test_demo_study_cannot_be_promoted_to_field(study):
    with pytest.raises(HTTPException):
        pilot.create_study(study[0],pilot.StudyInput(title="现场试点",course="数据结构",mode="field",protocol="此协议不能在离线演示模式建立现场试点。"))


def test_private_routes_and_public_evidence_separate(monkeypatch):
    monkeypatch.setenv("DEMO_MODE","false");monkeypatch.setenv("AUTH_REQUIRED","true")
    monkeypatch.setenv("AUTH_SECRET","test-only-pilot-auth-secret-at-least-32-characters");config.get_settings.cache_clear()
    ids=[]
    try:
        with TestClient(app) as client:
            assert client.get("/api/competition").status_code==200
            public=client.get("/api/competition").json()
            assert public["field_results"]==[]
            assert client.get("/api/pilot/studies").status_code==401
            headers=[]
            for _ in range(2):
                result=client.post("/api/auth/register",json={"email":uuid.uuid4().hex+"@example.test","password":"test-pilot-password","name":"隔离测试"})
                assert result.status_code==201
                ids.append(result.json()["user"]["id"]);headers.append({"Authorization":"Bearer "+result.json()["access_token"]})
            result=client.post("/api/pilot/studies",headers=headers[0],json={"title":"私有试点","course":"数据结构","mode":"demo","protocol":"仅使用明确标注的匿名合成测试数据。"})
            assert result.status_code==200
            target="/api/pilot/studies/"+result.json()["id"]
            assert client.get(target,headers=headers[1]).status_code==404
            assert client.post(target+"/observations",headers=headers[1],json={"observations":[row()]}).status_code==404
            assert client.post(target+"/observations",headers=headers[0],json={"observations":[row()]}).status_code==200
            assert client.get("/api/pilot/studies",headers=headers[1]).json()["studies"]==[]
            assert client.delete(target,headers=headers[1]).status_code==404
            assert client.delete(target,headers=headers[0]).json()=={"deleted":True}
            assert client.get(target,headers=headers[0]).status_code==404
    finally:
        with session() as db:
            for model in (PilotObservation,PilotStudy,AuthAccount):
                field=model.user_id
                db.execute(delete(model).where(field.in_(ids)))
            db.execute(delete(User).where(User.id.in_(ids)));db.commit()

"""Claude teaching videos: owner-only pairing, two-stage jobs, uploads, approval and recovery."""
import asyncio
import hashlib
import io
import time

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import config
from app.agents import media_agent
from app.auth import create_access_token
from app.main import app
from app.models import db as database
from app.models.entities import AuthAccount, ClaudeVideoJob, Resource, User, UserAsset
from app.services import claude_video as service
from app.services.ownership_service import asset_belongs_to_user
from app.tenant import current_user_context

TOKEN = "claude-video-worker-pairing-secret-for-tests-only"
WORKER = {"Authorization": "Bearer " + TOKEN}
INFO = {"info": {"cli_version": "2.1.299 (Claude Code)", "auth": {"logged_in": True, "method": "claude.ai", "plan": "max"},
                 "tools": {"hyperframes": "0.8.163", "ffmpeg": "6.0", "secret": "must-not-be-stored"}}}


@pytest.fixture
def store(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///" + str(tmp_path / "video.db"), connect_args={"check_same_thread": False})
    monkeypatch.setattr(database, "_engine", engine)
    monkeypatch.setattr(database, "_SessionLocal", sessionmaker(bind=engine, expire_on_commit=False))
    monkeypatch.setattr(database, "_initialized_engine", None)
    monkeypatch.setenv("CLAUDE_VIDEO_ENABLED", "true")
    monkeypatch.setenv("CLAUDE_VIDEO_OWNER_ID", "owner")
    monkeypatch.setenv("CLAUDE_VIDEO_WORKER_TOKEN_SHA256", hashlib.sha256(TOKEN.encode()).hexdigest())
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("AUTH_SECRET", "test-only-jwt-secret-with-at-least-32-characters")
    monkeypatch.setattr(service, "GEN_DIR", tmp_path / "gen")
    from app.services import object_storage
    monkeypatch.setattr(object_storage, "GEN_DIR", tmp_path / "gen")
    config.get_settings.cache_clear()
    database.init_db()
    with database.session() as db:
        for user in ("owner", "other"):
            db.add(User(id=user))
            db.add(AuthAccount(user_id=user, email=f"{user}@example.test", password_hash="unused-test-only"))
        db.commit()
    token = current_user_context.set("owner")
    yield tmp_path
    current_user_context.reset(token)
    engine.dispose()
    config.get_settings.cache_clear()


def user_headers(user="owner"):
    jwt, _ = create_access_token({"id": user})
    return {"Authorization": "Bearer " + jwt}


def queue_video(topic="光合作用", key="job-1", resource_id="res-1"):
    return service.request(topic=topic, goal="看懂光合作用的原料、产物和场所", persona="零基础学习者",
                           content="讲解稿：植物用光能把二氧化碳和水合成葡萄糖并释放氧气。",
                           material="[1] 光合作用在叶绿体中进行。", resource_id=resource_id, job_key=key)


def timed_storyboard():
    return {"title": "光合作用 90 秒看懂", "visual_style": "浅色玻璃质感", "duration": 21.5, "scenes": [
        {"title": "一句话结论", "narration": "光合作用就是植物用光能造糖。", "visual": "叶片发光", "on_screen": ["光能→化学能"],
         "start": 0, "end": 9.2},
        {"title": "原料与产物", "narration": "原料是二氧化碳和水，产物是葡萄糖和氧气。", "visual": "分子拆分重组",
         "start": 9.6, "end": 21.5},
    ]}


def mp4_bytes():
    return b"\x00\x00\x00\x20ftypisom" + b"\x00" * 4096


def png_bytes():
    buffer = io.BytesIO()
    Image.new("RGB", (640, 360), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def add_resource(resource_id="res-1", user="owner"):
    with database.session() as db:
        db.add(Resource(id=resource_id, user_id=user, kind="video", kp="custom_topic", title="光合作用·讲解视频",
                        payload={"script": {"title": "草稿"}}, citations=[], safety={}))
        db.commit()


def test_only_the_pairing_token_reaches_the_worker_api(store):
    client = TestClient(app)
    for authorization in ("", "Bearer wrong-token-of-sufficient-length-000000", user_headers()["Authorization"]):
        assert client.post("/api/claude-video-worker/claim", headers={"Authorization": authorization}, json=INFO).status_code == 401
    assert client.post("/api/claude-video-worker/claim", headers=WORKER, json=INFO).json() == {"job": None}
    # The pairing token is not a website login.
    assert client.get("/api/settings/claude-video", headers=WORKER).status_code == 401


def test_request_is_owner_only_and_idempotent_per_generation_job(store):
    first = queue_video()
    assert first["status"] == "queued" and first["provider"] == "claude_code"
    assert service.is_task(first["task_id"])
    again = queue_video(resource_id="res-2")
    assert again["task_id"] == first["task_id"]
    with database.session() as db:
        assert db.query(ClaudeVideoJob).count() == 1
        assert db.get(ClaudeVideoJob, first["task_id"]).resource_id == "res-2"
    token = current_user_context.set("other")
    try:
        assert queue_video(key="job-2") == {}
    finally:
        current_user_context.reset(token)


def test_full_two_stage_flow_updates_resource_assets_and_chapters(store):
    add_resource()
    state = queue_video()
    client = TestClient(app)
    job = client.post("/api/claude-video-worker/claim", headers=WORKER, json=INFO).json()["job"]
    assert job["kind"] == "video" and job["stage"] == "storyboard" and "api_key" not in job
    assert "光合作用" in job["prompts"]["storyboard"] and "叶绿体" in job["prompts"]["storyboard"]
    assert "storyboard.json" in job["prompts"]["storyboard"] and "hyperframes" in job["prompts"]["production"].lower()
    assert "不访问网络" in job["prompts"]["rules"]
    lease = job["lease"]
    beat = client.post(f"/api/claude-video-worker/{job['id']}/heartbeat", headers=WORKER,
                       json={"lease": lease, "phase": "storyboard", "message": ""}).json()
    assert beat == {"status": "running", "cancelled": False}
    polled = client.get(f"/api/resources/video/task/{state['task_id']}", headers=user_headers()).json()
    assert polled["status"] == "running" and polled["phase"] == "storyboard" and polled["worker_online"] is True

    nxt = client.post(f"/api/claude-video-worker/{job['id']}/storyboard", headers=WORKER,
                      json={"lease": lease, "storyboard": timed_storyboard()}).json()
    assert nxt == {"next": "production"}
    assert client.post(f"/api/claude-video-worker/{job['id']}/finish", headers=WORKER,
                       json={"lease": lease, "meta": {"duration": 21.5, "width": 1920, "height": 1080}}).status_code == 409
    bad = client.post(f"/api/claude-video-worker/{job['id']}/video", headers={**WORKER, "x-video-lease": lease},
                      content=b"not a video" * 200)
    assert bad.status_code == 422
    uploaded = client.post(f"/api/claude-video-worker/{job['id']}/video", headers={**WORKER, "x-video-lease": lease},
                           content=mp4_bytes())
    assert uploaded.status_code == 200
    poster = client.post(f"/api/claude-video-worker/{job['id']}/poster",
                         headers={**WORKER, "x-video-lease": lease, "content-type": "image/png"}, content=png_bytes())
    assert poster.status_code == 200
    done = client.post(f"/api/claude-video-worker/{job['id']}/finish", headers=WORKER, json={"lease": lease, "meta": {
        "duration": 21.5, "width": 1920, "height": 1080, "title": "光合作用 90 秒看懂",
        "chapters": [{"start": 0, "title": "一句话结论"}, {"start": 9.6, "title": "原料与产物"}]}}).json()
    assert done["status"] == "succeeded" and done["url"].endswith(".mp4") and done["poster_url"].endswith(".png")
    assert [c["title"] for c in done["chapters"]] == ["一句话结论", "原料与产物"]

    with database.session() as db:
        payload = db.get(Resource, "res-1").payload
        assert payload["video"]["status"] == "succeeded" and payload["video"]["url"] == done["url"]
        assert payload["script"] == {"title": "草稿"}
        assert db.query(UserAsset).filter_by(user_id="owner", path=done["url"]).count() == 1
    assert asset_belongs_to_user("owner", done["url"]) is True
    assert asset_belongs_to_user("other", done["url"]) is False
    # A finished job never accepts another upload under the old lease.
    assert client.post(f"/api/claude-video-worker/{job['id']}/video", headers={**WORKER, "x-video-lease": lease},
                       content=mp4_bytes()).status_code == 409


def test_storyboard_approval_pauses_then_production_gets_notes(store):
    client = TestClient(app)
    view = client.get("/api/settings/claude-video", headers=user_headers()).json()
    assert view["available"] is True and view["config"]["model"] == "claude-opus-5-5"
    saved = client.post("/api/settings/claude-video", headers=user_headers(), json={
        "revision": view["config"]["revision"], "config": {"approve_storyboard": True, "effort": "medium"}}).json()
    assert saved["config"]["approve_storyboard"] is True and saved["config"]["effort"] == "medium"
    state = queue_video()
    job = client.post("/api/claude-video-worker/claim", headers=WORKER, json=INFO).json()["job"]
    assert job["settings"]["effort"] == "medium"
    nxt = client.post(f"/api/claude-video-worker/{job['id']}/storyboard", headers=WORKER,
                      json={"lease": job["lease"], "storyboard": timed_storyboard()}).json()
    assert nxt == {"next": "wait"}
    waiting = client.get(f"/api/resources/video/task/{state['task_id']}", headers=user_headers()).json()
    assert waiting["status"] == "awaiting_approval" and waiting["storyboard"]["scenes"][1]["title"] == "原料与产物"
    assert client.post("/api/claude-video-worker/claim", headers=WORKER, json=INFO).json() == {"job": None}
    assert client.post(f"/api/claude-video/{state['task_id']}/approve", headers=user_headers("other"),
                       json={"notes": "x"}).status_code == 404
    approved = client.post(f"/api/claude-video/{state['task_id']}/approve", headers=user_headers(),
                           json={"notes": "把分子模型做成 3D 的"}).json()
    assert approved["status"] == "queued"
    second = client.post("/api/claude-video-worker/claim", headers=WORKER, json=INFO).json()["job"]
    assert second["stage"] == "production" and second["storyboard"]["timed"] is True
    assert "把分子模型做成 3D 的" in second["prompts"]["production"]


def test_cancel_reaches_the_worker_and_blocks_uploads(store):
    client = TestClient(app)
    state = queue_video()
    job = client.post("/api/claude-video-worker/claim", headers=WORKER, json=INFO).json()["job"]
    cancelled = client.post(f"/api/claude-video/{state['task_id']}/cancel", headers=user_headers()).json()
    assert cancelled["status"] == "cancelled" and cancelled["retryable"] is True
    beat = client.post(f"/api/claude-video-worker/{job['id']}/heartbeat", headers=WORKER,
                       json={"lease": job["lease"], "phase": "compose"}).json()
    assert beat == {"status": "cancelled", "cancelled": True}
    assert client.post(f"/api/claude-video-worker/{job['id']}/video", headers={**WORKER, "x-video-lease": job["lease"]},
                       content=mp4_bytes()).status_code == 409
    assert client.post(f"/api/claude-video-worker/{job['id']}/fail", headers=WORKER,
                       json={"lease": job["lease"], "code": "cancelled"}).json() == {"ok": True}
    retried = client.post(f"/api/claude-video/{state['task_id']}/retry", headers=user_headers()).json()
    assert retried["status"] == "queued" and retried["error"] == ""


def test_lost_worker_is_requeued_once_then_failed(store):
    state = queue_video()
    for attempt in (1, 2):
        job = service.claim("owner", {})
        assert job and job["id"] == state["task_id"]
        with database.session() as db:
            db.get(ClaudeVideoJob, job["id"]).lease_until = time.time() - 1
            db.commit()
    assert service.claim("owner", {}) is None
    final = service.poll("owner", state["task_id"])
    assert final["status"] == "failed" and final["code"] == "worker_lost" and final["retryable"] is True


def test_never_claimed_job_tells_the_learner_to_start_the_worker(store):
    state = queue_video()
    polled = service.poll("owner", state["task_id"])
    assert polled["status"] == "queued" and "启动讲解视频接入" in polled["message"]
    with database.session() as db:
        row = db.get(ClaudeVideoJob, state["task_id"])
        row.data = {**row.data, "queued_at": time.time() - service.QUEUE_TTL - 5}
        db.commit()
    expired = service.poll("owner", state["task_id"])
    assert expired["status"] == "failed" and expired["code"] == "not_started"


def test_worker_failure_codes_map_to_learner_messages(store):
    client = TestClient(app)
    state = queue_video()
    job = client.post("/api/claude-video-worker/claim", headers=WORKER, json=INFO).json()["job"]
    client.post(f"/api/claude-video-worker/{job['id']}/fail", headers=WORKER,
                json={"lease": job["lease"], "code": "usage_limit", "detail": "resets 3pm"})
    failed = service.poll("owner", state["task_id"])
    assert failed["status"] == "failed" and "额度" in failed["error"] and "resets 3pm" in failed["error"]


def test_owner_settings_stay_visible_when_video_is_disabled(store, monkeypatch):
    monkeypatch.setenv("CLAUDE_VIDEO_ENABLED", "false")
    monkeypatch.delenv("CLAUDE_VIDEO_OWNER_ID")
    monkeypatch.setenv("PERSONAL_IMAGE_OWNER_ID", "owner")
    client = TestClient(app)
    owner = client.get("/api/settings/claude-video", headers=user_headers()).json()
    other = client.get("/api/settings/claude-video", headers=user_headers("other")).json()
    assert owner["owner_settings"] is True and owner["available"] is False
    assert other["owner_settings"] is False and other["available"] is False
    assert client.post("/api/settings/claude-video/test", headers=user_headers()).status_code == 403


def test_settings_validate_keys_revisions_and_owner(store):
    client = TestClient(app)
    view = client.get("/api/settings/claude-video", headers=user_headers()).json()
    assert view["worker"]["online"] is False and view["options"]["durations"] == [60, 90, 120, 180]
    bad_key = client.post("/api/settings/claude-video", headers=user_headers(),
                          json={"revision": 0, "config": {}, "api_key": "not-a-key"})
    assert bad_key.status_code == 422
    no_key = client.post("/api/settings/claude-video", headers=user_headers(),
                         json={"revision": 0, "config": {"access": "api_key"}})
    assert no_key.status_code == 422
    ok = client.post("/api/settings/claude-video", headers=user_headers(), json={
        "revision": 0, "config": {"access": "api_key", "model": "not-a-model", "max_seconds": 999},
        "api_key": "sk-ant-api03-test-key-0123456789"}).json()
    assert ok["config"]["access"] == "api_key" and ok["config"]["has_api_key"] is True
    assert ok["config"]["model"] == "claude-opus-5-5" and ok["config"]["max_seconds"] == 120
    assert "sk-ant" not in str(ok)
    stale = client.post("/api/settings/claude-video", headers=user_headers(), json={"revision": 0, "config": {}})
    assert stale.status_code == 409
    assert client.post("/api/settings/claude-video", headers=user_headers("other"),
                       json={"revision": 0, "config": {}}).status_code == 403
    queue_video()
    job = service.claim("owner", INFO["info"])
    assert job["api_key"] == "sk-ant-api03-test-key-0123456789" and job["settings"]["access"] == "api_key"
    with database.session() as db:
        stored = db.get(service.ClaudeVideoConfig, "owner")
        assert "sk-ant" not in stored.credential and "secret" not in stored.worker["tools"]


def test_connection_test_is_claimed_first_and_reported(store):
    client = TestClient(app)
    queue_video()
    test = client.post("/api/settings/claude-video/test", headers=user_headers()).json()["test"]
    assert test["status"] == "queued"
    job = client.post("/api/claude-video-worker/claim", headers=WORKER, json=INFO).json()["job"]
    assert job["kind"] == "ping" and "prompts" not in job
    client.post(f"/api/claude-video-worker/{job['id']}/ping", headers=WORKER,
                json={"lease": job["lease"], "ok": True, "reply": "连接成功"})
    view = client.get("/api/settings/claude-video", headers=user_headers()).json()
    assert view["test"]["status"] == "succeeded" and view["test"]["reply"] == "连接成功"
    assert view["worker"]["online"] is True and view["worker"]["auth"]["method"] == "claude.ai"


def test_media_agent_hands_video_to_claude_without_calling_cloud_video(store, monkeypatch, tmp_path):
    monkeypatch.setattr(media_agent, "GEN_DIR", tmp_path)
    monkeypatch.setattr(media_agent, "is_demo", lambda: False)

    async def script(*args, **kwargs):
        return ('{"title":"光合作用","narration":"光合作用是植物利用光能把二氧化碳和水合成有机物并释放氧气的过程。",'
                '"scenes":[{"t":"0-20s","visual":"叶片吸收光","caption":"光能"}],"video_prompt":"leaf"}')

    async def must_not_call(*args, **kwargs):
        raise AssertionError("Claude videos must not also submit a cloud video")

    async def no_audio(*args, **kwargs):
        return {"ok": False, "data": {}, "error": "tts unavailable"}

    monkeypatch.setattr(media_agent, "llm_complete", script)
    monkeypatch.setattr(media_agent.multimodal_gateway, "video_create", must_not_call)
    monkeypatch.setattr(media_agent.multimodal_gateway, "tts", no_audio)
    out = asyncio.run(media_agent.run({"kinds": ["video"], "learning_goal": "光合作用", "topic_label": "光合作用",
                                       "user_id": "owner", "session_id": "claude-video", "job_id": "gen-1"}))
    resource = next(iter(out["generated_resources"].values()))
    video = resource["payload"]["video"]
    assert video["provider"] == "claude_code" and video["status"] == "queued"
    assert "manim_code" not in resource["payload"]
    assert out["progress_events"] == [{"agent": "media", "mode": "claude_code"}]
    with database.session() as db:
        row = db.get(ClaudeVideoJob, video["task_id"])
        assert row.resource_id == resource["id"] and "光合作用" in row.brief["content"]

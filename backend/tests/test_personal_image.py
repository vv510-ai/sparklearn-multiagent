"""Owner binding, durable handoff, upload validation, and no duplicate UI submission."""
import asyncio
import hashlib
import io
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import config
from app.auth import create_access_token
from app.main import app
from app.models import db as database
from app.models.entities import AuthAccount, User, PersonalImageJob, GenerationJob, GenerationEvent, GenerationTicket, UserAsset
from app.services import generation_jobs as jobs, personal_image as bridge
from app.tenant import current_user_context

TOKEN = "test-worker-pairing-secret-unique-to-this-test"


@pytest.fixture
def store(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///" + str(tmp_path / "bridge.db"), connect_args={"check_same_thread": False})
    monkeypatch.setattr(database, "_engine", engine)
    monkeypatch.setattr(database, "_SessionLocal", sessionmaker(bind=engine, expire_on_commit=False))
    monkeypatch.setattr(database, "_initialized_engine", None)
    monkeypatch.setenv("PERSONAL_CHAT_IMAGE_ENABLED", "true")
    monkeypatch.setenv("PERSONAL_CHAT_IMAGE_OWNER_ID", "owner")
    monkeypatch.setenv("PERSONAL_CHAT_IMAGE_WORKER_TOKEN_SHA256", hashlib.sha256(TOKEN.encode()).hexdigest())
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    monkeypatch.setenv("AUTH_SECRET", "test-only-jwt-secret-with-at-least-32-characters")
    monkeypatch.setattr(bridge, "GEN_DIR", tmp_path / "images")
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


def queue(prompt="栈后进先出", key="request1"):
    job = jobs.submit({"user_id": "owner", "session_id": "test", "messages": []}, "resource", key, jobs.digest(key))
    lease = jobs.claim("generation-worker")
    token = jobs._context.set(lease)
    try:
        with pytest.raises(jobs.ProviderPending):
            bridge.request_image(prompt)
    finally:
        jobs._context.reset(token)
    return job, lease


def image_bytes(color="white"):
    buffer = io.BytesIO()
    Image.new("RGB", (256, 144), color).save(buffer, format="PNG")
    return buffer.getvalue()


def test_only_pairing_token_can_reach_worker_api_and_cannot_access_other_api(store):
    client = TestClient(app)
    path = "/api/personal-image-worker/claim"
    jwt, _ = create_access_token({"id": "owner"})
    for authorization in ("", "Bearer bad", "Bearer " + jwt):
        assert client.post(path, headers={"Authorization": authorization}, json={}).status_code == 401
    headers = {"Authorization": "Bearer " + TOKEN}
    assert client.post(path, headers=headers, json={}).json() == {"job": None}
    assert client.get("/api/resources?user_id=owner", headers=headers).status_code == 401


def test_owner_binding_ignores_claim_body_and_rejects_other_context(store):
    queue()
    client = TestClient(app)
    response = client.post("/api/personal-image-worker/claim", headers={"Authorization": "Bearer " + TOKEN},
                           json={"user_id": "other"})
    assert response.status_code == 200 and response.json()["job"]["prompt"] == "栈后进先出"
    token = current_user_context.set("other")
    try:
        assert not bridge.enabled_for_user()
        assert not bridge.request_image("other request")["ok"]
        with pytest.raises(HTTPException) as error:
            bridge.claim()
        assert error.value.status_code == 403
    finally:
        current_user_context.reset(token)


def test_concurrent_claims_and_expired_fences_do_not_duplicate_submitted_image(store):
    queue()
    def claim(_):
        token = current_user_context.set("owner")
        try:
            return bridge.claim()
        finally:
            current_user_context.reset(token)
    with ThreadPoolExecutor(max_workers=5) as pool:
        claimed = [value for value in pool.map(claim, range(5)) if value]
    assert len(claimed) == 1
    first = claimed[0]
    with database.session() as db:
        db.get(PersonalImageJob, first["id"]).lease_until = 0
        db.commit()
    second = bridge.claim()
    assert second["id"] == first["id"] and second["lease"] != first["lease"]
    with pytest.raises(HTTPException):
        bridge.transition(first["id"], first["lease"], "submitted")
    bridge.transition(second["id"], second["lease"], "submitted")
    with database.session() as db:
        db.get(PersonalImageJob, second["id"]).lease_until = 0
        db.commit()
    assert bridge.claim() is None
    with database.session() as db:
        row = db.get(PersonalImageJob, second["id"])
        assert row.status == "failed" and row.detail_code == "uncertain"


def test_completed_image_is_idempotent_owned_and_resumes_without_resubmitting(store):
    _, generation_lease = queue()
    claim = bridge.claim()
    bridge.transition(claim["id"], claim["lease"], "submitted")
    raw = image_bytes()
    result = bridge.complete(claim["id"], claim["lease"], raw, "image/png")
    assert bridge.complete(claim["id"], claim["lease"], raw, "image/png") == result
    assert (bridge.GEN_DIR / result["image_url"].split("/")[-1]).read_bytes() == raw
    with pytest.raises(HTTPException) as error:
        bridge.complete(claim["id"], claim["lease"], image_bytes("red"), "image/png")
    assert error.value.status_code == 409
    token = jobs._context.set(generation_lease)
    try:
        generated = bridge.request_image("栈后进先出")
        assert generated["ok"] and generated["provider"] == "chatgpt_web"
    finally:
        jobs._context.reset(token)
    assert bridge.claim() is None
    with database.session() as db:
        assert db.query(UserAsset).one().user_id == "owner"
        assert db.get(PersonalImageJob, claim["id"]).prompt == ""


@pytest.mark.parametrize("payload,mime", [(b"<svg></svg>", "image/svg+xml"), (b"not an image", "image/png"),
                                             (image_bytes(), "image/jpeg"), (image_bytes()[:100], "image/png")])
def test_invalid_upload_never_creates_an_asset(store, payload, mime):
    queue()
    claim = bridge.claim()
    bridge.transition(claim["id"], claim["lease"], "submitted")
    with pytest.raises(HTTPException) as error:
        bridge.complete(claim["id"], claim["lease"], payload, mime)
    assert error.value.status_code == 422
    with database.session() as db:
        assert db.query(UserAsset).count() == 0


def test_cancelled_parent_cannot_be_sent_or_receive_image(store):
    job, _ = queue()
    claim = bridge.claim()
    with database.session() as db:
        db.get(GenerationJob, job["id"]).status = "cancelled"
        db.commit()
    with pytest.raises(HTTPException):
        bridge.transition(claim["id"], claim["lease"], "submitted")
    assert bridge.claim() is None


def test_disabled_bridge_preserves_existing_provider_for_owner(store, monkeypatch):
    from app.services import one_page_image as pipeline
    monkeypatch.setenv("PERSONAL_CHAT_IMAGE_ENABLED", "false")
    called = []
    async def generate(prompt, **kwargs):
        called.append(kwargs["preferred_provider"])
        return {"ok": False, "data": {}}
    monkeypatch.setattr(pipeline.gateway, "text_to_image", generate)
    result = asyncio.run(pipeline.generate_one_page("栈", ["后进先出"], content_status="checked", trace_id="test"))
    assert called == ["xiaoyunque"] and result["provider"] == "xiaoyunque"


def test_personal_pipeline_does_not_fallback_and_keeps_unverified_label(store, monkeypatch):
    from app.services import one_page_image as pipeline
    from app.agents.eval_agent import _learner_summary
    async def generate(prompt, **kwargs):
        assert kwargs["preferred_provider"] == "chatgpt_web" and not kwargs["allow_provider_fallback"]
        return {"ok": True, "data": {"provider": "chatgpt_web", "image_url": "/static/gen/test.png"}}
    async def inspect(*args, **kwargs):
        return pipeline.unverified("测试中未运行真实读图")
    monkeypatch.setattr(pipeline.gateway, "text_to_image", generate)
    monkeypatch.setattr(pipeline, "inspect_image", inspect)
    page = asyncio.run(pipeline.generate_one_page("栈", ["后进先出"], content_status="checked", trace_id="test"))
    assert page["renderer"] == "chatgpt-web-infographic-v1" and page["generation_attempts"] == 1
    assert "未确认" in _learner_summary({"r": {"payload": {"one_page_visual": page}}}, [], "one_page")


def test_waiting_for_image_preserves_events_and_only_resumes_graph_after_upload(store):
    job, lease = queue()
    claim = bridge.claim()
    bridge.transition(claim['id'], claim['lease'], 'submitted', phase='wait_image')
    with database.session() as db:
        db.get(GenerationJob, job['id']).status = 'running'
        event = GenerationEvent(job_id=job['id'], user_id='owner', data={'type':'progress', 'text':'文字稿已核对'})
        db.add(event)
        db.commit()
        cursor = event.id
    calls = []
    async def runner(state):
        calls.append(state['job_id'])
        yield {'type':'summary', 'text':'图片已归档'}
    for _ in range(3):
        asyncio.run(jobs.execute(*lease, runner=runner))
        with database.session() as db:
            events = db.query(GenerationEvent).filter_by(job_id=job['id']).all()
            assert [(e.id, e.data['text']) for e in events] == [(cursor, '文字稿已核对')]
            assert '正在绘图' in db.get(GenerationJob, job['id']).detail
            db.get(GenerationTicket, job['id']).lease_until = 0
            db.commit()
        lease = jobs.claim('test')
    assert calls == []
    bridge.complete(claim['id'], claim['lease'], image_bytes(), 'image/png')
    asyncio.run(jobs.execute(*lease, runner=runner))
    assert calls == [job['id']] and jobs.owned('owner', job['id'])['status'] == 'completed'


def test_progress_is_enum_bounded_and_does_not_accept_browser_text(store):
    queue()
    claim = bridge.claim()
    client = TestClient(app)
    headers = {'Authorization':'Bearer ' + TOKEN}
    url = f"/api/personal-image-worker/{claim['id']}/heartbeat"
    assert client.post(url, headers=headers, json={'lease':claim['lease'], 'phase':'read_image'}).status_code == 200
    assert client.post(url, headers=headers, json={'lease':claim['lease'], 'phase':'private browser content'}).status_code == 422
    with database.session() as db:
        parent_id = db.get(PersonalImageJob, claim['id']).generation_job_id
        assert '正在取回原图' in bridge.pending_message(db, parent_id)


def test_late_heartbeat_cannot_move_progress_backwards(store):
    queue()
    claim = bridge.claim()
    bridge.transition(claim['id'], claim['lease'], 'submitted', phase='wait_image')
    bridge.transition(claim['id'], claim['lease'], 'heartbeat', phase='submit')
    with database.session() as db:
        assert db.get(PersonalImageJob, claim['id']).data['phase'] == 'wait_image'
    bridge.transition(claim['id'], claim['lease'], 'heartbeat', phase='upload_image')
    bridge.transition(claim['id'], claim['lease'], 'heartbeat', phase='read_image')
    with database.session() as db:
        assert db.get(PersonalImageJob, claim['id']).data['phase'] == 'upload_image'


def test_multi_image_answer_is_stored_by_position_and_resumes_with_all_pictures(store):
    job, generation_lease = queue_multi()
    claim = bridge.claim()
    assert claim["multi"] is True and claim["max_images"] == bridge.MAX_IMAGES
    bridge.transition(claim["id"], claim["lease"], "submitted", phase="wait_image")
    bridge.transition(claim["id"], claim["lease"], "heartbeat", phase="continue_more")
    first, second = image_bytes("white"), image_bytes("green")
    stored = bridge.store_image(claim["id"], claim["lease"], 1, first, "image/png")
    assert bridge.store_image(claim["id"], claim["lease"], 1, first, "image/png") == stored
    with pytest.raises(HTTPException) as error:
        bridge.store_image(claim["id"], claim["lease"], 1, second, "image/png")
    assert error.value.status_code == 409
    with pytest.raises(HTTPException) as error:
        bridge.finish(claim["id"], claim["lease"], 2)  # picture 2 was never uploaded
    assert error.value.status_code == 422
    bridge.store_image(claim["id"], claim["lease"], 2, second, "image/png")
    done = bridge.finish(claim["id"], claim["lease"], 2, "https://chatgpt.com/c/abc-12345678")
    assert done["count"] == 2 and [item["index"] for item in done["images"]] == [1, 2]
    assert done["conversation_url"].startswith("https://chatgpt.com/c/")
    assert bridge.finish(claim["id"], claim["lease"], 2) == done
    token = jobs._context.set(generation_lease)
    try:
        generated = bridge.request_image("帮我弄一个一图看懂光合作用的内容", multi=True)
    finally:
        jobs._context.reset(token)
    assert generated["ok"] and len(generated["images"]) == 2 and generated["image_url"] == done["images"][0]["image_url"]
    with database.session() as db:
        assert db.query(UserAsset).count() == 2


def test_multi_image_routes_are_worker_only(store):
    queue_multi()
    claim = bridge.claim()
    bridge.transition(claim["id"], claim["lease"], "submitted")
    client = TestClient(app)
    headers = {"Authorization": "Bearer " + TOKEN, "Content-Type": "image/png", "X-Image-Lease": claim["lease"]}
    url = f"/api/personal-image-worker/{claim['id']}/image/1"
    assert client.post(url, headers={**headers, "Authorization": "Bearer nope"}, content=image_bytes()).status_code == 401
    assert client.post(url, headers=headers, content=image_bytes()).status_code == 200
    assert client.post(f"/api/personal-image-worker/{claim['id']}/image/9", headers=headers, content=image_bytes()).status_code == 422
    finish = client.post(f"/api/personal-image-worker/{claim['id']}/finish",
                         headers={"Authorization": "Bearer " + TOKEN}, json={"lease": claim["lease"], "count": 1})
    assert finish.status_code == 200 and finish.json()["count"] == 1


def queue_multi(prompt="帮我弄一个一图看懂光合作用的内容", key="multi1"):
    job = jobs.submit({"user_id": "owner", "session_id": "test", "messages": []}, "resource", key, jobs.digest(key))
    lease = jobs.claim("generation-worker")
    token = jobs._context.set(lease)
    try:
        with pytest.raises(jobs.ProviderPending):
            bridge.request_image(prompt, multi=True)
    finally:
        jobs._context.reset(token)
    return job, lease

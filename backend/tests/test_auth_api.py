from __future__ import annotations

import json
import shutil
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import event

from app import config
from app.api import resources as resources_api
from app.config import GEN_DIR, RUNS_DIR
from app.main import app
from app.models.db import get_engine, session
from app.models.entities import AuthAccount, ExternalTask, Resource, User, UserAsset
from app.services.ownership_service import sync_resource_ownership


def _enable_real_auth(monkeypatch) -> None:
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    monkeypatch.setenv("AUTH_SECRET", "test-only-auth-secret-with-at-least-32-characters")
    config.get_settings.cache_clear()


def _enable_sqlite_foreign_keys() -> None:
    """Mirror PostgreSQL FK enforcement in the local integration test."""
    engine = get_engine()
    if engine.dialect.name != "sqlite":
        return

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")


def _delete_accounts(user_ids: list[str]) -> None:
    with session() as db:
        for user_id in user_ids:
            account = db.get(AuthAccount, user_id)
            if account:
                db.delete(account)
            user = db.get(User, user_id)
            if user:
                db.delete(user)
        db.commit()


def test_register_login_and_user_scope(monkeypatch):
    _enable_real_auth(monkeypatch)
    _enable_sqlite_foreign_keys()
    marker = uuid.uuid4().hex
    created_ids: list[str] = []
    generated_file = None
    debug_dir = None

    try:
        with TestClient(app) as client:
            assert client.get("/api/resources?user_id=someone").status_code == 401

            first = client.post(
                "/api/auth/register",
                json={"email": f"first-{marker}@example.com", "password": "correct-horse", "name": "学习者甲"},
            )
            assert first.status_code == 201, first.text
            first_data = first.json()
            first_id = first_data["user"]["id"]
            created_ids.append(first_id)
            first_headers = {"Authorization": f"Bearer {first_data['access_token']}"}

            with session() as db:
                stored_account = db.get(AuthAccount, first_id)
                assert stored_account is not None
                assert "m=19456,t=2,p=1" in stored_account.password_hash

            me = client.get("/api/auth/me", headers=first_headers)
            assert me.status_code == 200
            assert me.json() == {
                "id": first_id,
                "email": f"first-{marker}@example.com",
                "name": "学习者甲",
                "demo": False,
            }

            duplicate = client.post(
                "/api/auth/register",
                json={"email": f"FIRST-{marker}@example.com", "password": "another-password", "name": "重复"},
            )
            assert duplicate.status_code == 409

            second = client.post(
                "/api/auth/register",
                json={"email": f"second-{marker}@example.com", "password": "correct-horse", "name": "学习者乙"},
            )
            assert second.status_code == 201, second.text
            second_id = second.json()["user"]["id"]
            created_ids.append(second_id)
            second_headers = {"Authorization": f"Bearer {second.json()['access_token']}"}

            # A valid token cannot be paired with another user's query parameter.
            cross_user = client.get(
                f"/api/knowledge/sources?user_id={second_id}",
                headers=first_headers,
            )
            assert cross_user.status_code == 403

            # Generated files, provider tasks, and trace bundles are tenant-owned.
            generated_file = GEN_DIR / f"tenant-{marker}.txt"
            generated_file.write_text("private learning artifact", encoding="utf-8")
            asset_url = f"/static/gen/{generated_file.name}"
            resource_id = f"security-{marker}"
            task_id = f"task-{marker}"
            payload = {"cover_url": asset_url, "video": {"task_id": task_id}}
            with session() as db:
                db.add(Resource(
                    id=resource_id,
                    user_id=first_id,
                    kind="doc",
                    kp="",
                    title="private",
                    payload=payload,
                    citations=[],
                    safety={},
                ))
                db.commit()
            sync_resource_ownership(first_id, resource_id, payload)

            first_asset = client.get(asset_url, headers=first_headers)
            assert first_asset.status_code == 200
            assert first_asset.text == "private learning artifact"
            assert client.get(asset_url, headers=second_headers).status_code == 404

            async def fake_video_poll(value: str):
                return {"task_id": value, "status": "running"}

            monkeypatch.setattr(resources_api.multimodal_gateway, "video_poll", fake_video_poll)
            assert client.get(
                f"/api/resources/video/task/{task_id}", headers=first_headers,
            ).status_code == 200
            assert client.get(
                f"/api/resources/video/task/{task_id}", headers=second_headers,
            ).status_code == 404

            debug_dir = RUNS_DIR / f"tenant-{marker}"
            debug_dir.mkdir(parents=True, exist_ok=True)
            (debug_dir / "state.summary.json").write_text(
                json.dumps({"user_id": first_id}), encoding="utf-8",
            )
            assert client.get(
                f"/api/debug/runs/{debug_dir.name}", headers=first_headers,
            ).status_code == 200
            assert client.get(
                f"/api/debug/runs/{debug_dir.name}", headers=second_headers,
            ).status_code == 404

            wrong_password = client.post(
                "/api/auth/login",
                json={"email": f"first-{marker}@example.com", "password": "wrong-password"},
            )
            assert wrong_password.status_code == 401

            login = client.post(
                "/api/auth/login",
                json={"email": f"first-{marker}@example.com", "password": "correct-horse"},
            )
            assert login.status_code == 200
            assert login.json()["user"]["id"] == first_id
    finally:
        with session() as db:
            db.query(UserAsset).filter(UserAsset.user_id.in_(created_ids)).delete()
            db.query(ExternalTask).filter(ExternalTask.user_id.in_(created_ids)).delete()
            db.query(Resource).filter(Resource.user_id.in_(created_ids)).delete()
            db.commit()
        if generated_file is not None:
            generated_file.unlink(missing_ok=True)
        if debug_dir is not None:
            shutil.rmtree(debug_dir, ignore_errors=True)
        _delete_accounts(created_ids)
        config.get_settings.cache_clear()

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.models.db import session
from app.models.entities import AuthAccount, User


def _enable_real_auth(monkeypatch) -> None:
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    monkeypatch.setenv("AUTH_SECRET", "test-only-auth-secret-with-at-least-32-characters")
    config.get_settings.cache_clear()


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
    marker = uuid.uuid4().hex
    created_ids: list[str] = []

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

            # A valid token cannot be paired with another user's query parameter.
            cross_user = client.get(
                f"/api/knowledge/sources?user_id={second_id}",
                headers=first_headers,
            )
            assert cross_user.status_code == 403

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
        _delete_accounts(created_ids)
        config.get_settings.cache_clear()

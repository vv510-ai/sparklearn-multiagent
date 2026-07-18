from __future__ import annotations

import json
import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.db import session
from app.models.entities import ConversationMessage, Notebook, User
from app.rag import ingest
from app.services.conversation_service import append_message


def test_notebook_library_persists_subject_workspaces_and_enforces_owner():
    marker = uuid.uuid4().hex
    first_user = f"notebook-user-{marker}"
    second_user = f"other-notebook-user-{marker}"
    created_id = ""
    try:
        with TestClient(app) as client:
            created = client.post(
                "/api/notebooks",
                json={"user_id": first_user, "title": "  高等数学  "},
            )
            assert created.status_code == 201, created.text
            payload = created.json()
            created_id = payload["id"]
            assert payload["title"] == "高等数学"
            assert payload["session_id"].startswith("book-")
            assert payload["source_count"] == 0

            listed = client.get(f"/api/notebooks?user_id={first_user}")
            assert listed.status_code == 200
            assert [item["id"] for item in listed.json()["items"]] == [created_id]

            detail = client.get(f"/api/notebooks/{created_id}?user_id={first_user}")
            assert detail.status_code == 200
            assert detail.json()["messages"] == []

            old_session_id = payload["session_id"]
            append_message(first_user, old_session_id, "user", "什么是二叉树")
            rotated = client.post(
                f"/api/notebooks/{created_id}/conversations",
                json={"user_id": first_user},
            )
            assert rotated.status_code == 201, rotated.text
            assert rotated.json()["session_id"] != old_session_id
            assert rotated.json()["messages"] == []
            clean_detail = client.get(f"/api/notebooks/{created_id}?user_id={first_user}")
            assert clean_detail.json()["messages"] == []

            denied_rotation = client.post(
                f"/api/notebooks/{created_id}/conversations",
                json={"user_id": second_user},
            )
            assert denied_rotation.status_code == 404

            client.get(f"/api/notebooks?user_id={second_user}")
            denied = client.get(f"/api/notebooks/{created_id}?user_id={second_user}")
            assert denied.status_code == 404
    finally:
        with session() as db:
            db.query(ConversationMessage).filter(
                ConversationMessage.user_id.in_([first_user, second_user]),
            ).delete(synchronize_session=False)
            if created_id:
                row = db.get(Notebook, created_id)
                if row:
                    db.delete(row)
            for user_id in (first_user, second_user):
                row = db.get(User, user_id)
                if row:
                    db.delete(row)
            db.commit()


def test_selected_sources_cannot_cross_notebook_boundary(monkeypatch, tmp_path):
    meta = {
        "id": "source-a",
        "user_id": "alice",
        "notebook_id": "notebook-a",
        "status": "indexed",
        "active": True,
    }
    (tmp_path / "source-a.meta.json").write_text(json.dumps(meta), encoding="utf-8")
    monkeypatch.setattr(ingest, "UPLOAD_SOURCES_DIR", tmp_path)
    monkeypatch.setattr(ingest, "load_all_chunks", lambda: [{"source_id": "source-a"}])

    assert ingest.validate_source_scope("alice", ["source-a"], "notebook-a") == ["source-a"]
    with pytest.raises(ValueError, match="selected sources are unavailable"):
        ingest.validate_source_scope("alice", ["source-a"], "notebook-b")

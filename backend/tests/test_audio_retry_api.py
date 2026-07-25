"""Interactive-audio retry contract and durable resource state."""
from __future__ import annotations

import os
import sys

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tests._stubs import install  # noqa: E402

install()

from app.api import resources as resources_api  # noqa: E402
from app.main import app  # noqa: E402
from app.models.db import init_db, session  # noqa: E402
from app.models.entities import Resource  # noqa: E402
from app.services.profile_service import ensure_user  # noqa: E402


USER_ID = "audio_retry_contract_user"


def _seed(resource_id: str, *, with_narration: bool = True) -> None:
    init_db()
    ensure_user(USER_ID)
    payload = {
        "markdown": "# 二叉树\n\n二叉树每个节点最多有两个孩子。",
        "template": "interactive_audio",
        "audio": {
            "status": "fallback",
            "provider": "browser_speech",
            "error": "provider timeout",
            "retryable": True,
        },
    }
    if with_narration:
        payload["audio_narration"] = "本节讲解二叉树。二叉树每个节点最多有两个孩子。"
    with session() as db:
        db.query(Resource).filter(Resource.user_id == USER_ID).delete()
        db.add(Resource(
            id=resource_id,
            user_id=USER_ID,
            kind="doc",
            kp="binary_tree",
            title="二叉树·互动讲解",
            payload=payload,
            citations=[],
            safety={"flags": [{"type": "audio_degraded"}]},
        ))
        db.commit()


def test_audio_retry_persists_cloud_audio_and_clears_degraded_flag(monkeypatch):
    resource_id = "audio-retry-ready"
    _seed(resource_id)

    async def working_tts(text: str, **_kwargs):
        assert text.startswith("本节讲解二叉树")
        return {"ok": True, "data": {"audio_url": "/static/gen/retry-ready.mp3"}}

    monkeypatch.setattr(resources_api.multimodal_gateway, "tts", working_tts)
    with TestClient(app) as client:
        response = client.post(f"/api/resources/{resource_id}/audio", json={"user_id": USER_ID})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["reused"] is False
    assert payload["audio"]["status"] == "ready"
    assert payload["resource"]["payload"]["audio_url"] == "/static/gen/retry-ready.mp3"
    with session() as db:
        stored = db.get(Resource, resource_id)
        assert stored.payload["audio"]["provider"] == "spark_tts"
        assert stored.safety["flags"] == []


def test_audio_retry_never_substitutes_another_voice_in_strict_super_mode(monkeypatch):
    resource_id = "audio-retry-strict-super"
    _seed(resource_id)

    async def failed_tts(_text: str, **_kwargs):
        return {
            "ok": False,
            "degraded": True,
            "data": {
                "provider": "spark_super_tts",
                "strict_voice": True,
                "retryable": True,
            },
            "error": "super TTS returned a silent frame; sid=test-sid",
        }

    monkeypatch.setattr(resources_api.multimodal_gateway, "tts", failed_tts)
    with TestClient(app) as client:
        response = client.post(
            f"/api/resources/{resource_id}/audio",
            json={"user_id": USER_ID},
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["audio"] == {
        "status": "unavailable",
        "provider": "spark_super_tts",
        "error": "super TTS returned a silent frame; sid=test-sid",
        "retryable": True,
        "strict_voice": True,
    }
    assert "audio_url" not in payload["resource"]["payload"]


def test_audio_retry_keeps_browser_fallback_and_exposes_provider_error(monkeypatch):
    resource_id = "audio-retry-fallback"
    _seed(resource_id, with_narration=False)

    async def failed_tts(text: str, **_kwargs):
        assert "二叉树" in text
        return {"ok": False, "degraded": True, "data": {}, "error": "TTS permission denied"}

    monkeypatch.setattr(resources_api.multimodal_gateway, "tts", failed_tts)
    with TestClient(app) as client:
        response = client.post(f"/api/resources/{resource_id}/audio", json={"user_id": USER_ID})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["audio"] == {
        "status": "fallback",
        "provider": "browser_speech",
        "error": "TTS permission denied",
        "retryable": True,
    }
    assert "audio_url" not in payload["resource"]["payload"]
    assert payload["resource"]["payload"]["audio_narration"].startswith("本节讲解")

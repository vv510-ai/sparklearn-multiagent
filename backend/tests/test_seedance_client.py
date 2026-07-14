from __future__ import annotations

from types import SimpleNamespace

from app.llm import seedance_client


def _settings(**overrides):
    values = {
        "ark_api_key": "test-ark-key",
        "ark_base_url": "https://ark.example.test/api/v3",
        "seedance_model": "doubao-seedance-2-0-260128",
        "seedance_ratio": "16:9",
        "seedance_duration": 5,
        "seedance_generate_audio": True,
        "seedance_watermark": False,
        "mm_video_create_timeout_s": 15,
        "mm_video_poll_timeout_s": 15,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_create_task_uses_seedance_2_request_contract(monkeypatch):
    sent = {}

    class FakeResponse:
        status_code = 200
        reason = "OK"
        headers = {}

        @staticmethod
        def raise_for_status():
            return None

        @staticmethod
        def json():
            return {"id": "task-123"}

    def fake_post(url, **kwargs):
        sent["url"] = url
        sent["headers"] = kwargs["headers"]
        sent["json"] = kwargs["json"]
        sent["timeout"] = kwargs["timeout"]
        return FakeResponse()

    monkeypatch.setattr(seedance_client, "get_settings", lambda: _settings())
    monkeypatch.setattr(seedance_client.requests, "post", fake_post)

    task_id = seedance_client.create_task(
        "Animate a binary tree traversal.",
        "https://assets.example.test/tree.png",
    )

    assert task_id == "task-123"
    assert sent["url"] == "https://ark.example.test/api/v3/contents/generations/tasks"
    assert sent["headers"]["Authorization"] == "Bearer test-ark-key"
    assert sent["json"] == {
        "model": "doubao-seedance-2-0-260128",
        "content": [
            {"type": "text", "text": "Animate a binary tree traversal."},
            {
                "type": "image_url",
                "image_url": {"url": "https://assets.example.test/tree.png"},
                "role": "reference_image",
            },
        ],
        "generate_audio": True,
        "ratio": "16:9",
        "duration": 5,
        "watermark": False,
    }
    assert sent["timeout"] == 15


def test_poll_task_returns_generated_video_url(monkeypatch):
    sent = {}

    class FakeResponse:
        @staticmethod
        def raise_for_status():
            return None

        @staticmethod
        def json():
            return {
                "id": "task-123",
                "status": "succeeded",
                "content": {"video_url": "https://assets.example.test/tree.mp4"},
            }

    def fake_get(url, **kwargs):
        sent["url"] = url
        sent["headers"] = kwargs["headers"]
        return FakeResponse()

    monkeypatch.setattr(seedance_client, "get_settings", lambda: _settings())
    monkeypatch.setattr(seedance_client.requests, "get", fake_get)

    result = seedance_client.poll_task("task-123")

    assert sent["url"].endswith("/contents/generations/tasks/task-123")
    assert result == {
        "status": "succeeded",
        "task_id": "task-123",
        "url": "https://assets.example.test/tree.mp4",
    }

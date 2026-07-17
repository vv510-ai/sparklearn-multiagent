from __future__ import annotations

from types import SimpleNamespace

from app.llm import spark_ppt


class _Response:
    ok = True
    status_code = 200

    def __init__(self, payload: dict):
        self.payload = payload

    def json(self):
        return self.payload


def _settings():
    return SimpleNamespace(
        spark_ppt_appid="ppt-app",
        spark_ppt_api_secret="ppt-secret",
        spark_appid="",
        spark_api_secret="",
        spark_ppt_base_url="https://zwapi.xfyun.cn",
    )


def test_ppt_signature_is_stable():
    assert spark_ppt.signature("ppt-app", "ppt-secret", 1720000000) == "CflW4z985qrd1gZ8G5vYuXyR7hU="


def test_create_ppt_uses_v2_explicit_source_safe_options(monkeypatch):
    captured = {}
    monkeypatch.setattr(spark_ppt, "get_settings", _settings)
    monkeypatch.setattr(spark_ppt.time, "time", lambda: 1720000000)

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return _Response({
            "flag": True,
            "code": 0,
            "data": {"sid": "ppt-task-123", "title": "二叉树复习"},
        })

    monkeypatch.setattr(spark_ppt.requests, "post", fake_post)
    result = spark_ppt.create_task("只根据课程资料生成二叉树复习PPT")

    assert captured["url"].endswith("/api/ppt/v2/create")
    assert captured["headers"]["appId"] == "ppt-app"
    assert captured["headers"]["signature"] == "CflW4z985qrd1gZ8G5vYuXyR7hU="
    assert captured["files"]["search"] == (None, "false")
    assert captured["files"]["isFigure"] == (None, "true")
    assert result["task_id"] == "ppt-task-123"
    assert result["status"] == "building"


def test_poll_ppt_waits_for_image_completion(monkeypatch):
    monkeypatch.setattr(spark_ppt, "get_settings", _settings)
    monkeypatch.setattr(spark_ppt.requests, "get", lambda *args, **kwargs: _Response({
        "flag": True,
        "code": 0,
        "data": {
            "pptStatus": "done",
            "aiImageStatus": "building",
            "pptUrl": "https://cdn.example/review.pptx",
            "totalPages": 9,
            "donePages": 9,
        },
    }))
    building = spark_ppt.poll_task("ppt-task-123")
    assert building["status"] == "building"

    monkeypatch.setattr(spark_ppt.requests, "get", lambda *args, **kwargs: _Response({
        "flag": True,
        "code": 0,
        "data": {
            "pptStatus": "done",
            "aiImageStatus": "done",
            "pptUrl": "https://cdn.example/review.pptx",
            "totalPages": 9,
            "donePages": 9,
        },
    }))
    ready = spark_ppt.poll_task("ppt-task-123")
    assert ready["status"] == "ready"
    assert ready["total_pages"] == 9

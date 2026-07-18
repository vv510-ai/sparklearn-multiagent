from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.llm import xiaoyunque_client as client


def _settings(**overrides):
    values = {
        "xyq_access_key": "test-xyq-key",
        "xyq_base_url": "https://xyq.example.test",
        "xyq_video_model": "Seedance_2.0_mini_lite",
        "xyq_video_ratio": "16:9",
        "xyq_video_duration": 5,
        "xyq_video_resolution": "720p",
        "mm_video_create_timeout_s": 15,
        "mm_video_poll_timeout_s": 12,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class _Response:
    status_code = 200
    reason = "OK"
    headers = {}
    text = ""

    def __init__(self, payload):
        self.payload = payload

    @staticmethod
    def raise_for_status():
        return None

    def json(self):
        return self.payload


def test_create_task_uses_official_video_part_contract(monkeypatch):
    sent = {}

    def fake_post(url, **kwargs):
        sent.update(url=url, **kwargs)
        return _Response({
            "ret": "0",
            "errmsg": "",
            "data": {
                "run": {"thread_id": "thread-1", "run_id": "run-1"},
                "web_thread_link": "https://xyq.example.test/thread/1",
            },
        })

    monkeypatch.setattr(client, "get_settings", lambda: _settings())
    monkeypatch.setattr(client.requests, "post", fake_post)

    task_id = client.create_task(" 生成 一个 教学 视频 ")

    assert client.is_task_id(task_id)
    assert client._decode_task_id(task_id) == ("thread-1", "run-1")  # noqa: SLF001
    assert sent["url"] == "https://xyq.example.test/api/biz/v1/skill/submit_run"
    assert sent["headers"]["Authorization"] == "Bearer test-xyq-key"
    assert sent["timeout"] == 15
    assert sent["json"] == {
        "agent_name": "pippit_video_part_agent",
        "message": "生成 一个 教学 视频",
        "video_part_tool_param": {
            "prompt": "生成 一个 教学 视频",
            "duration_sec": 10,
            "ratio": "16:9",
            "model": "Seedance_2.0_mini_lite",
            "resolution": "720p",
        },
    }


def test_poll_task_extracts_video_artifact_from_json_string(monkeypatch):
    sent = {}
    task_id = client._encode_task_id("thread-2", "run-2")  # noqa: SLF001

    def fake_post(url, **kwargs):
        sent.update(url=url, **kwargs)
        return _Response({
            "ret": "0",
            "errmsg": "",
            "data": {
                "thread": {
                    "thread_id": "thread-2",
                    "run_list": [{
                        "run_id": "run-2",
                        "state": 3,
                        "entry_list": [{
                            "artifact": {
                                "content": [{
                                    "sub_type": "biz/x_data_video",
                                    "data": json.dumps({
                                        "video": {"download_url": "https://cdn.test/video.mp4"}
                                    }),
                                }]
                            }
                        }],
                    }],
                }
            },
        })

    monkeypatch.setattr(client, "get_settings", lambda: _settings())
    monkeypatch.setattr(client.requests, "post", fake_post)

    result = client.poll_task(task_id)

    assert sent["url"] == "https://xyq.example.test/api/biz/v1/skill/get_thread"
    assert sent["json"] == {"thread_id": "thread-2", "run_id": "run-2"}
    assert result["status"] == "succeeded"
    assert result["provider"] == "xiaoyunque"
    assert result["url"] == "https://cdn.test/video.mp4"


def test_poll_task_maps_failed_run(monkeypatch):
    task_id = client._encode_task_id("thread-3", "run-3")  # noqa: SLF001
    monkeypatch.setattr(client, "get_settings", lambda: _settings())
    monkeypatch.setattr(
        client.requests,
        "post",
        lambda *args, **kwargs: _Response({
            "ret": "0",
            "data": {
                "thread": {
                    "run_list": [{
                        "run_id": "run-3",
                        "state": 4,
                        "fail_reason": "quota exhausted",
                    }]
                }
            },
        }),
    )

    result = client.poll_task(task_id)

    assert result["status"] == "failed"
    assert result["error"] == "quota exhausted"


def test_poll_task_reads_error_from_artifact(monkeypatch):
    task_id = client._encode_task_id("thread-4", "run-4")  # noqa: SLF001
    monkeypatch.setattr(client, "get_settings", lambda: _settings())
    monkeypatch.setattr(
        client.requests,
        "post",
        lambda *args, **kwargs: _Response({
            "ret": "0",
            "data": {
                "thread": {
                    "run_list": [{
                        "run_id": "run-4",
                        "state": 4,
                        "entry_list": [{
                            "artifact": {
                                "content": [{
                                    "sub_type": "biz/x_data_video",
                                    "data": json.dumps({"error_message": "content rejected"}),
                                }]
                            }
                        }],
                    }]
                }
            },
        }),
    )

    result = client.poll_task(task_id)

    assert result["status"] == "failed"
    assert result["error"] == "content rejected"


def test_business_error_does_not_leak_access_key(monkeypatch):
    monkeypatch.setattr(client, "get_settings", lambda: _settings())
    monkeypatch.setattr(
        client.requests,
        "post",
        lambda *args, **kwargs: _Response({
            "ret": "401",
            "errmsg": "invalid access key",
            "log_id": "log-1",
            "data": {},
        }),
    )

    with pytest.raises(RuntimeError) as error:
        client.create_task("test")

    assert "ret=401" in str(error.value)
    assert "test-xyq-key" not in str(error.value)


def test_upload_file_uses_multipart_file_field(monkeypatch, tmp_path):
    source = tmp_path / "reference.png"
    source.write_bytes(b"png-data")
    sent = {}

    def fake_post(url, **kwargs):
        sent.update(url=url, **kwargs)
        assert kwargs["files"]["file"][0] == "reference.png"
        assert kwargs["files"]["file"][1].read() == b"png-data"
        return _Response({"ret": "0", "data": {"pippit_asset_id": "asset-1"}})

    monkeypatch.setattr(client, "get_settings", lambda: _settings())
    monkeypatch.setattr(client.requests, "post", fake_post)

    asset_id = client.upload_file(source)

    assert asset_id == "asset-1"
    assert sent["url"].endswith("/api/biz/v1/skill/upload_file")
    assert "Content-Type" not in sent["headers"]

"""Image questions must reach the tutor, survive follow-ups, and fail honestly."""
import base64

import pytest

from app.api import chat
from tests.test_learning_spaces import learner  # noqa: F401


PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a7WQAAAAASUVORK5CYII=")
DATA_URL = "data:image/png;base64," + base64.b64encode(PNG).decode()


def test_image_question_persists_recognition_and_keeps_notebook_scope(learner, monkeypatch):
    client, user = learner
    book = client.post("/api/notebooks", json={"title": "图片题目", "user_id": user}).json()
    other = client.post("/api/notebooks", json={"title": "另一门课", "user_id": user}).json()
    seen = []
    calls = []

    async def ocr(image, **kwargs):
        assert image == PNG
        calls.append(kwargs)
        return {"ok": True, "data": {"text": "2x + 3 = 11；我的答案 x = 7"}}

    async def graph(state):
        seen.append(state)
        yield {"type": "token", "delta": "先两边减 3，再除以 2，x = 4。"}
        yield {"type": "done"}

    monkeypatch.setattr(chat.multimodal_gateway, "ocr_image", ocr)
    monkeypatch.setattr(chat, "run_with_events", graph)
    response = client.post("/api/chat", json={
        "user_id": user, "notebook_id": book["id"], "message": "哪里错了？",
        "image_base64": DATA_URL,
    })
    assert response.status_code == 200, response.text
    assert seen[0]["intent"] == "tutor"
    assert "2x + 3 = 11" in seen[0]["messages"][0]["content"]
    assert len(calls) == 1
    saved = client.get(f"/api/notebooks/{book['id']}?user_id={user}").json()["messages"]
    assert len(saved) == 2
    assert "图片识别内容" in saved[0]["content"]
    assert "base64" not in str(saved)
    assert client.get(f"/api/notebooks/{other['id']}?user_id={user}").json()["messages"] == []
    response = client.post("/api/chat", json={
        "user_id": user, "notebook_id": book["id"], "message": "为什么先减 3？",
    })
    assert response.status_code == 200
    assert len(calls) == 1
    assert any("2x + 3 = 11" in m["content"] for m in seen[1]["conversation"])


@pytest.mark.parametrize("encoded,status", [
    ("not-base64", 400),
    (base64.b64encode(b"not an image").decode(), 400),
    ("A" * (4 * ((4 * 1024 * 1024 + 2) // 3) + 4), 413),
], ids=["invalid-base64", "invalid-format", "too-large"])
def test_invalid_image_never_reaches_model_or_history(learner, monkeypatch, encoded, status):
    client, user = learner
    book = client.post("/api/notebooks", json={"title": "无效图片", "user_id": user}).json()

    async def unexpected(*args, **kwargs):
        pytest.fail("Invalid images must be rejected before OCR")

    monkeypatch.setattr(chat.multimodal_gateway, "ocr_image", unexpected)
    response = client.post("/api/chat", json={
        "user_id": user, "notebook_id": book["id"], "message": "讲解", "image_base64": encoded,
    })
    assert response.status_code == status
    assert client.get(f"/api/notebooks/{book['id']}?user_id={user}").json()["messages"] == []


@pytest.mark.parametrize("failure,status", [("empty", 422), ("unavailable", 503)])
def test_ocr_failure_does_not_fabricate_an_answer(learner, monkeypatch, failure, status):
    client, user = learner
    book = client.post("/api/notebooks", json={"title": "读不清的图片", "user_id": user}).json()

    async def ocr(*args, **kwargs):
        if failure == "unavailable":
            raise RuntimeError("provider unavailable")
        return {"ok": False, "data": {}}

    async def graph(*args, **kwargs):
        pytest.fail("The tutor must not answer an unreadable image")
        yield {}

    monkeypatch.setattr(chat.multimodal_gateway, "ocr_image", ocr)
    monkeypatch.setattr(chat, "run_with_events", graph)
    response = client.post("/api/chat", json={
        "user_id": user, "notebook_id": book["id"], "message": "", "image_base64": DATA_URL,
    })
    assert response.status_code == status
    assert "图片" in response.json()["detail"]
    assert client.get(f"/api/notebooks/{book['id']}?user_id={user}").json()["messages"] == []



def test_image_question_rejects_context_that_would_be_truncated(learner, monkeypatch):
    client, user = learner

    async def ocr(*args, **kwargs):
        return {"ok": True, "data": {"text": "x" * 19990}}

    monkeypatch.setattr(chat.multimodal_gateway, "ocr_image", ocr)
    response = client.post("/api/chat", json={
        "user_id": user, "message": "请解释图片中的完整内容", "image_base64": DATA_URL,
    })
    assert response.status_code == 422
    assert "太长" in response.json()["detail"]

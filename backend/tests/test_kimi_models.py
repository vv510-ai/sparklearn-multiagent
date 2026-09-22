from __future__ import annotations

import asyncio
import json
import uuid

import httpx
import openai
import pytest

from app import config
from app.llm import selected_model, spark_client
from app.services import model_preferences
from app.auth import bind_request_user, reset_request_user
from app.services.profile_service import ensure_user


@pytest.fixture
def kimi_transport(monkeypatch):
    for key, value in {
        "LLM_PROVIDER": "kimi", "DEMO_MODE": "false", "KIMI_API_KEY": "test-kimi-only",
        "KIMI_BASE_URL": "https://kimi.example.test/v1", "KIMI_MODEL": "kimi-k2.6",
        "KIMI_THINKING": "disabled", "KIMI_REASONING_EFFORT": "high",
    }.items():
        monkeypatch.setenv(key, value)
    config.get_settings.cache_clear()
    monkeypatch.setattr(model_preferences, "resolve", lambda _: None)
    sync_client, async_client = openai.OpenAI, openai.AsyncOpenAI
    calls = []

    def install(handler):
        def record(request):
            calls.append(request)
            return handler(request)
        monkeypatch.setattr(openai, "OpenAI", lambda **kw: sync_client(
            **kw, http_client=httpx.Client(transport=httpx.MockTransport(record))))
        monkeypatch.setattr(openai, "AsyncOpenAI", lambda **kw: async_client(
            **kw, http_client=httpx.AsyncClient(transport=httpx.MockTransport(record))))
        return calls
    return install


def completion(text='{"answer":"C"}', finish="stop"):
    return {"id": "chat-test", "object": "chat.completion", "created": 1,
            "model": "kimi-k2.6", "choices": [{"index": 0, "finish_reason": finish,
            "message": {"role": "assistant", "content": text}}]}


def test_kimi_only_config_activates_real_gateway(kimi_transport, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "auto")
    monkeypatch.setenv("LLM_PROVIDER", "auto")
    for key in ("OPENAI_API_KEY", "DEEPSEEK_API_KEY", "SPARK_API_PASSWORD"):
        monkeypatch.setenv(key, "")
    config.get_settings.cache_clear()
    assert not config.is_demo()
    assert spark_client.active_provider() == "kimi"
    assert spark_client.active_llm_label() == "kimi-k2.6"
    monkeypatch.setenv("KIMI_API_KEY", "")
    config.get_settings.cache_clear()
    assert config.is_demo()


def test_k26_json_wire_contract_and_short_budget(kimi_transport):
    calls = kimi_transport(lambda _: httpx.Response(200, json=completion()))
    result = asyncio.run(spark_client.llm_complete("题目 JSON", system="教学规则", json_object=True, max_tokens=300))
    assert json.loads(result) == {"answer": "C"}
    body = json.loads(calls[0].content)
    assert calls[0].url.path == "/v1/chat/completions"
    assert body["model"] == "kimi-k2.6" and body["max_tokens"] == 300
    assert body["thinking"] == {"type": "disabled"}
    assert body["response_format"] == {"type": "json_object"}
    assert body["messages"][0]["content"] == "教学规则"
    assert "temperature" not in body and "reasoning_effort" not in body


def test_reasoner_has_budget_for_thinking_but_classifier_stays_short(kimi_transport):
    calls = kimi_transport(lambda _: httpx.Response(200, json=completion()))
    asyncio.run(spark_client.llm_complete("推导", role="reasoner", max_tokens=2000))
    asyncio.run(spark_client.llm_complete("意图分类", role="reasoner", max_tokens=300))
    deep, helper = [json.loads(call.content) for call in calls]
    assert deep["thinking"] == {"type": "enabled"} and deep["max_tokens"] >= 4096
    assert helper["thinking"] == {"type": "disabled"} and helper["max_tokens"] == 300


def test_k3_uses_effort_and_completion_budget(kimi_transport, monkeypatch):
    monkeypatch.setenv("KIMI_MODEL", "kimi-k3")
    config.get_settings.cache_clear()
    calls = kimi_transport(lambda _: httpx.Response(200, json=completion()))
    asyncio.run(spark_client.llm_complete("综合资料", max_tokens=7000))
    asyncio.run(spark_client.llm_complete("分类", max_tokens=100))
    deep, helper = [json.loads(call.content) for call in calls]
    assert deep["reasoning_effort"] == "high" and deep["max_completion_tokens"] == 7000
    assert helper["reasoning_effort"] == "low" and helper["max_completion_tokens"] >= 4096
    assert all(k not in deep for k in ("thinking", "temperature", "max_tokens"))


@pytest.mark.parametrize("text,finish", [("partial", "length"), ("", "stop")])
def test_incomplete_answer_never_falls_back(kimi_transport, text, finish):
    calls = kimi_transport(lambda _: httpx.Response(200, json=completion(text, finish)))
    with pytest.raises(RuntimeError, match="调用失败"):
        asyncio.run(spark_client.llm_complete("课程", allow_mock_fallback=True))
    assert len(calls) == 1


def test_provider_error_is_redacted_and_not_retried(kimi_transport):
    calls = kimi_transport(lambda _: httpx.Response(429, json={"error": {
        "message": "private-key-private-prompt", "code": "insufficient_quota", "type": "rate_limit_error"}}))
    with pytest.raises(RuntimeError) as caught:
        asyncio.run(spark_client.llm_complete("private-prompt"))
    assert "private" not in str(caught.value) and "429" in str(caught.value)
    assert len(calls) == 1


def sse(finish="stop"):
    chunks = [{"delta": {"reasoning_content": "private reasoning"}},
              {"delta": {"content": "后进先出"}}]
    if finish is not None:
        chunks.append({"delta": {}, "finish_reason": finish})
    return "".join("data: " + json.dumps({"id": "sse-test", "object": "chat.completion.chunk",
        "created": 1, "model": "kimi-k2.6", "choices": [{"index": 0, **c}]}) + "\n\n"
        for c in chunks) + "data: [DONE]\n\n"


def test_stream_is_real_sse_and_never_exposes_reasoning(kimi_transport):
    calls = kimi_transport(lambda _: httpx.Response(200, content=sse(), headers={"content-type": "text/event-stream"}))
    async def read():
        return [part async for part in spark_client.llm_stream("解释栈")]
    assert asyncio.run(read()) == ["后进先出"]
    assert json.loads(calls[0].content)["stream"] is True


@pytest.mark.parametrize("finish", ["length", None])
def test_partial_stream_fails_without_appending_mock(kimi_transport, finish):
    calls = kimi_transport(lambda _: httpx.Response(200, content=sse(finish), headers={"content-type": "text/event-stream"}))
    pieces = []
    async def read():
        async for part in spark_client.llm_stream("解释栈"):
            pieces.append(part)
    with pytest.raises(RuntimeError, match="流式调用失败"):
        asyncio.run(read())
    assert pieces == ["后进先出"] and len(calls) == 1


def test_account_selection_overrides_server_and_streams(kimi_transport, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    config.get_settings.cache_clear()
    monkeypatch.setattr(model_preferences, "resolve", lambda _: {
        "provider": "kimi", "model": "kimi-k3", "key": "test-personal-only", "base_url": "https://kimi.example.test/v1"})
    calls = kimi_transport(lambda _: httpx.Response(200, content=sse(), headers={"content-type": "text/event-stream"}))
    async def read():
        return [part async for part in spark_client.llm_stream("解释栈")]
    assert asyncio.run(read()) == ["后进先出"]
    assert json.loads(calls[0].content)["model"] == "kimi-k3"
    assert calls[0].headers["authorization"] == "Bearer test-personal-only"


def test_explicit_demo_makes_no_external_request(kimi_transport, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    config.get_settings.cache_clear()
    def unexpected(_):
        raise AssertionError("demo contacted provider")
    calls = kimi_transport(unexpected)
    assert asyncio.run(spark_client.llm_complete("解释栈"))
    assert calls == []


def test_smart_server_routing_and_account_override(monkeypatch):
    for key, value in {"DEMO_MODE": "false", "LLM_PROVIDER": "deepseek",
                       "DEEPSEEK_API_KEY": "test-existing-deepseek", "KIMI_API_KEY": "test-kimi",
                       "KIMI_SMART_ROUTING": "true"}.items():
        monkeypatch.setenv(key, value)
    config.get_settings.cache_clear()
    user = "smart_" + uuid.uuid4().hex
    ensure_user(user)
    token = bind_request_user(user)
    try:
        before = model_preferences.view(user)
        assert all(p["available"] for p in before["presets"])
        assert before["routes"] == {} and before["server_routes"]["research"] == "kimi-k3"
        assert model_preferences.resolve("CAPABILITY=tutor.guided\n")["provider"] == "deepseek"
        assert model_preferences.resolve("CAPABILITY=english.scene\n")["provider"] == "deepseek"
        assert model_preferences.resolve("CAPABILITY=research.report\n")["model"] == "kimi-k3"
        assert model_preferences.resolve("CAPABILITY=doc.complete_notes\n")["model"] == "kimi-k3"
        assert model_preferences.resolve("CAPABILITY=media.storyboard\n")["model"] == "kimi-k3"
        model_preferences.save(user, {"default": "deepseek-v4-pro"}, {}, before["revision"])
        assert model_preferences.resolve("CAPABILITY=research.report\n")["provider"] == "deepseek"
        model_preferences.save(user, {"default": "kimi-k3"}, {})
        assert model_preferences.resolve("CAPABILITY=tutor.guided\n")["model"] == "kimi-k3"
    finally:
        reset_request_user(token)


def test_unconfigured_presets_are_unavailable_and_demo_stays_offline(monkeypatch):
    monkeypatch.setenv("KIMI_SMART_ROUTING", "true")
    config.get_settings.cache_clear()
    user = "smart_missing_" + uuid.uuid4().hex
    ensure_user(user)
    view = model_preferences.view(user)
    assert not any(p["available"] for p in view["presets"])
    assert view["server_routes"] == {}
    assert "API_KEY" not in json.dumps(view)

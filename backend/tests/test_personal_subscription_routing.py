"""Subscription-first text routing: Kimi ⇄ ChatGPT failover, never a paid API."""
import asyncio

import pytest

from app.llm import personal_subscription as subscription


@pytest.fixture
def relay(monkeypatch):
    monkeypatch.setenv("PORTABLE_RELAY_TOKEN", "t" * 48)
    monkeypatch.setattr(subscription, "model_for", lambda prompt, task_context=None: "kimi-subscription")
    calls = []

    def script(*results):
        answers = iter(results)

        async def ask(model, prompt, system, json_mode, token):
            calls.append(model)
            return next(answers)
        monkeypatch.setattr(subscription, "_ask", ask)
    return calls, script


def test_quota_on_kimi_fails_over_to_chatgpt_subscription(relay):
    calls, script = relay
    script((False, "limit_or_provider_error"), (True, "答案"))
    assert asyncio.run(subscription.complete("讲讲光合作用")) == "答案"
    assert calls == ["kimi-subscription", "chatgpt-subscription"]


def test_shared_worker_outage_does_not_retry_the_other_provider(relay):
    calls, script = relay
    script((False, "worker_unavailable"))
    with pytest.raises(RuntimeError, match="05-启动订阅接入"):
        asyncio.run(subscription.complete("讲讲光合作用"))
    assert calls == ["kimi-subscription"]


def test_both_subscriptions_failing_raises_without_api_fallback(relay):
    calls, script = relay
    script((False, "not_logged_in"), (False, "limit_or_provider_error"))
    with pytest.raises(RuntimeError, match="没有切换到收费 API"):
        asyncio.run(subscription.complete("讲讲光合作用"))
    assert calls == ["kimi-subscription", "chatgpt-subscription"]


def test_failover_can_be_disabled(relay, monkeypatch):
    calls, script = relay
    monkeypatch.setenv("PORTABLE_SUBSCRIPTION_FAILOVER", "false")
    script((False, "limit_or_provider_error"))
    with pytest.raises(RuntimeError):
        asyncio.run(subscription.complete("讲讲光合作用"))
    assert calls == ["kimi-subscription"]


@pytest.mark.parametrize("value,expected", [
    ("http://127.0.0.1:18431", "http://127.0.0.1:18431"),
    ("http://localhost:18431/", "http://localhost:18431"),
    ("https://evil.example/relay", "http://subscription-relay:18431"),
    ("", "http://subscription-relay:18431"),
])
def test_prompts_only_travel_to_the_paired_relay(monkeypatch, value, expected):
    monkeypatch.setenv("PERSONAL_RELAY_URL", value)
    assert subscription.relay_url() == expected

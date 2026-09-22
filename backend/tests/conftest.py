from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _offline_by_default(monkeypatch):
    """Keep pytest offline even when the developer .env contains real keys."""
    from app import config

    monkeypatch.setenv("DEMO_MODE", "true")
    # Tests may explicitly exercise a transport; never inherit developer routes/keys.
    monkeypatch.setenv("LLM_PROVIDER", "spark")
    monkeypatch.setenv("KIMI_SMART_ROUTING", "false")
    for key in ("OPENAI_API_KEY", "DEEPSEEK_API_KEY", "KIMI_API_KEY", "SPARK_API_PASSWORD"):
        monkeypatch.setenv(key, "")
    monkeypatch.setenv("EMBEDDING_BACKEND", "hash")
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()

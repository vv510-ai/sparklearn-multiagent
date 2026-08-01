from app import config


def test_demo_mode_keeps_one_click_access_without_explicit_auth_override(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.delenv("AUTH_REQUIRED", raising=False)
    config.get_settings.cache_clear()

    assert config.is_demo() is True
    assert config.auth_required() is False


def test_explicit_auth_override_works_with_offline_demo_model(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    config.get_settings.cache_clear()

    assert config.is_demo() is True
    assert config.auth_required() is True

import os
import pytest

from app.agent.notify_hub_client import ConfigError, _load_config


def test_load_config_missing_url_raises(monkeypatch):
    monkeypatch.delenv("NOTIFY_HUB_URL", raising=False)
    monkeypatch.setenv("NOTIFY_HUB_TOKEN", "af_xxx")
    with pytest.raises(ConfigError, match="NOTIFY_HUB_URL"):
        _load_config()


def test_load_config_missing_token_raises(monkeypatch):
    monkeypatch.setenv("NOTIFY_HUB_URL", "https://example.com/nh")
    monkeypatch.delenv("NOTIFY_HUB_TOKEN", raising=False)
    with pytest.raises(ConfigError, match="NOTIFY_HUB_TOKEN"):
        _load_config()


def test_load_config_strips_trailing_slash(monkeypatch):
    monkeypatch.setenv("NOTIFY_HUB_URL", "https://example.com/nh/")
    monkeypatch.setenv("NOTIFY_HUB_TOKEN", "af_xxx")
    cfg = _load_config()
    assert cfg.base_url == "https://example.com/nh"
    assert cfg.token == "af_xxx"

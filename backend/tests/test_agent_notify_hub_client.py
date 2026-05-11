import os
import pytest
import httpx

from app.agent.notify_hub_client import (
    ConfigError,
    HubDegradedError,
    _load_config,
    approve_request,
)


def _mock_transport(handler):
    return httpx.MockTransport(handler)


def _env(monkeypatch):
    monkeypatch.setenv("NOTIFY_HUB_URL", "https://example.com/nh")
    monkeypatch.setenv("NOTIFY_HUB_TOKEN", "af_test")


# ── _load_config ─────────────────────────────────────────────


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


# ── approve_request ──────────────────────────────────────────


def test_approve_request_201_returns_id(monkeypatch):
    _env(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path.endswith("/v1/approvals")
        assert request.headers["authorization"] == "Bearer af_test"
        assert request.headers.get("idempotency-key") == "key-1"
        return httpx.Response(201, json={
            "request_id": "abc-123",
            "status": "pending",
            "created_at": "2026-05-11T03:00:00Z",
            "expires_at": "2026-05-11T03:20:00Z",
            "push_state": "pushed",
        })

    rid = approve_request(
        project="alphaforge",
        title="test",
        items=[{"id": "1", "type": "t3", "summary": "s", "detail": "d"}],
        timeout_seconds=1200,
        idempotency_key="key-1",
        _transport=_mock_transport(handler),
    )
    assert rid == "abc-123"


def test_approve_request_connect_error_raises(monkeypatch):
    _env(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("network down")

    with pytest.raises(HubDegradedError, match="POST"):
        approve_request(
            project="alphaforge", title="t", items=[{"id": "1", "type": "t", "summary": "s"}],
            _transport=_mock_transport(handler),
        )


def test_approve_request_401_raises(monkeypatch):
    _env(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "auth"})

    with pytest.raises(HubDegradedError, match="401"):
        approve_request(
            project="alphaforge", title="t", items=[{"id": "1", "type": "t", "summary": "s"}],
            _transport=_mock_transport(handler),
        )

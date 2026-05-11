import os
from pathlib import Path

import pytest
import httpx

from app.agent.notify_hub_client import (
    ConfigError,
    HubDegradedError,
    _fallback_to_proposals,
    _load_config,
    approve_request,
    wait_result,
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


# ── wait_result ──────────────────────────────────────────────


def test_wait_result_first_call_approved(monkeypatch):
    _env(monkeypatch)
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json={
            "request_id": "abc-123",
            "status": "approved",
            "decided_at": "2026-05-11T03:05:00Z",
            "per_item": [{"id": "1", "decision": "approved", "reject_reason": None}],
        })

    result = wait_result(
        request_id="abc-123",
        overall_timeout_seconds=60,
        _transport=_mock_transport(handler),
    )
    assert result["status"] == "approved"
    assert result["per_item"][0]["decision"] == "approved"
    assert len(calls) == 1


def test_wait_result_multi_round_until_approved(monkeypatch):
    _env(monkeypatch)
    sequence = ["pending", "pending", "approved"]

    def handler(request: httpx.Request) -> httpx.Response:
        idx = handler.calls
        handler.calls += 1
        status = sequence[idx]
        body = {"request_id": "abc", "status": status, "per_item": []}
        if status == "approved":
            body["decided_at"] = "2026-05-11T03:05:00Z"
        return httpx.Response(200, json=body)
    handler.calls = 0

    result = wait_result(
        request_id="abc",
        overall_timeout_seconds=300,
        _transport=_mock_transport(handler),
    )
    assert result["status"] == "approved"
    assert handler.calls == 3


def test_wait_result_overall_timeout(monkeypatch):
    _env(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "request_id": "abc",
            "status": "pending",
            "per_item": [],
        })

    result = wait_result(
        request_id="abc",
        overall_timeout_seconds=1,
        _transport=_mock_transport(handler),
    )
    assert result["status"] == "timeout"
    assert result["request_id"] == "abc"


def test_wait_result_connect_error_raises(monkeypatch):
    _env(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("network down")

    with pytest.raises(HubDegradedError, match="wait"):
        wait_result(
            request_id="abc",
            overall_timeout_seconds=60,
            _transport=_mock_transport(handler),
        )


# ── _fallback_to_proposals ───────────────────────────────────


def test_fallback_writes_file_with_frontmatter(tmp_path: Path):
    items = [
        {"id": "1", "type": "t3-action", "summary": "改 X", "detail": "因 Y"},
        {"id": "2", "type": "memory-add", "summary": "記 Z", "detail": None},
    ]
    path = _fallback_to_proposals(
        items=items,
        title="2026-05-11 night tick - 2 項",
        date="2026-05-11",
        proposals_dir=tmp_path,
    )
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert content.startswith("---\n")
    assert "status: pending" in content
    assert "reason: notify-hub unreachable" in content
    assert "request_id: null" in content
    assert "## Item 1: t3-action — 改 X" in content
    assert "因 Y" in content
    assert "## Item 2: memory-add — 記 Z" in content


def test_fallback_slug_from_title(tmp_path: Path):
    path = _fallback_to_proposals(
        items=[{"id": "1", "type": "t", "summary": "s"}],
        title="Night Tick 2026-05-11",
        date="2026-05-11",
        proposals_dir=tmp_path,
    )
    assert path.name.startswith("2026-05-11-night-tick-2026-05-11")
    assert path.suffix == ".md"


def test_fallback_collision_appends_hash(tmp_path: Path):
    items = [{"id": "1", "type": "t", "summary": "s"}]
    path1 = _fallback_to_proposals(items, title="X", date="2026-05-11", proposals_dir=tmp_path)
    path2 = _fallback_to_proposals(items, title="X", date="2026-05-11", proposals_dir=tmp_path)
    assert path1 != path2
    assert path2.exists()


def test_fallback_includes_request_id_when_given(tmp_path: Path):
    path = _fallback_to_proposals(
        items=[{"id": "1", "type": "t", "summary": "s"}],
        title="t", date="2026-05-11",
        request_id="abc-123",
        proposals_dir=tmp_path,
    )
    assert "request_id: abc-123" in path.read_text(encoding="utf-8")

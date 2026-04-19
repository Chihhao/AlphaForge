from __future__ import annotations
from unittest.mock import patch, MagicMock
from app.agent.smoke_test import run_smoke, SmokeResult


def _fake_response(status: int, body: dict | None = None):
    m = MagicMock()
    m.status_code = status
    m.json.return_value = body or {}
    return m


def test_smoke_all_green():
    with patch("app.agent.smoke_test.httpx.get") as g:
        g.return_value = _fake_response(200, {"status": "ok"})
        result = run_smoke(base_url="http://localhost:8000")
    assert isinstance(result, SmokeResult)
    assert result.ok is True
    assert len(result.failures) == 0
    assert len(result.checks) == 3


def test_smoke_one_red_returns_not_ok():
    def side_effect(url, timeout):
        if "picks/today" in url:
            return _fake_response(500)
        return _fake_response(200, {"status": "ok"})
    with patch("app.agent.smoke_test.httpx.get", side_effect=side_effect):
        result = run_smoke(base_url="http://localhost:8000")
    assert result.ok is False
    assert any("picks/today" in f for f in result.failures)


def test_smoke_network_error_is_failure():
    import httpx
    with patch("app.agent.smoke_test.httpx.get",
               side_effect=httpx.ConnectError("boom")):
        result = run_smoke(base_url="http://localhost:8000")
    assert result.ok is False
    assert len(result.failures) == 3

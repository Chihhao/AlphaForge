"""notify-hub client helper for AlphaForge agent (Phase 2)。

Public API:
- approve_and_wait(...)  - prompt 主要 entry, 自動 hub failure fallback
- approve_request(...)   - 低階 POST only
- wait_result(...)       - 低階 long-poll only

Exceptions:
- HubDegradedError       - notify-hub call failed (network / HTTP / auth)
- ConfigError            - env var missing / invalid
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass

import httpx


class HubDegradedError(Exception):
    """notify-hub call failed (network / HTTP / auth)."""


class ConfigError(Exception):
    """環境變數 missing / invalid."""


@dataclass(frozen=True)
class _Config:
    base_url: str
    token: str


def _load_config() -> _Config:
    url = os.environ.get("NOTIFY_HUB_URL")
    token = os.environ.get("NOTIFY_HUB_TOKEN")
    if not url:
        raise ConfigError("NOTIFY_HUB_URL not set")
    if not token:
        raise ConfigError("NOTIFY_HUB_TOKEN not set")
    return _Config(base_url=url.rstrip("/"), token=token)


def approve_request(
    project: str,
    title: str,
    items: list[dict],
    timeout_seconds: int = 1200,
    idempotency_key: str | None = None,
    metadata: dict | None = None,
    _transport: httpx.BaseTransport | None = None,
) -> str:
    """POST /v1/approvals, return request_id。Hub fail raise HubDegradedError。

    `_transport` 給測試 inject MockTransport, production code 不 pass。
    """
    cfg = _load_config()
    body = {
        "project": project,
        "title": title,
        "items": items,
        "timeout_seconds": timeout_seconds,
        "metadata": metadata or {},
    }
    headers = {
        "Authorization": f"Bearer {cfg.token}",
        "Content-Type": "application/json",
    }
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key

    try:
        with httpx.Client(base_url=cfg.base_url, timeout=30.0, transport=_transport) as client:
            r = client.post("/v1/approvals", json=body, headers=headers)
    except httpx.HTTPError as e:
        raise HubDegradedError(f"POST /v1/approvals failed: {type(e).__name__}: {e}") from e

    if r.status_code != 201:
        raise HubDegradedError(f"POST /v1/approvals returned {r.status_code}: {r.text[:200]}")

    return r.json()["request_id"]


def wait_result(
    request_id: str,
    overall_timeout_seconds: int = 1200,
    _transport: httpx.BaseTransport | None = None,
) -> dict:
    """Long-poll loop, 多次 GET /<id>/wait?timeout=55 直到 status != pending or
    cumulative time >= overall_timeout。

    Return:
      - status='approved' | 'rejected': 含 decided_at + per_item
      - status='timeout': overall 過, 含 request_id
    Hub fail raise HubDegradedError。
    """
    cfg = _load_config()
    headers = {"Authorization": f"Bearer {cfg.token}"}

    deadline = time.monotonic() + overall_timeout_seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return {"status": "timeout", "request_id": request_id}
        # 每次 long-poll 上限 55s (notify-hub server cap), 但不超過 remaining
        per_call = min(55, max(1, int(remaining)))

        try:
            with httpx.Client(base_url=cfg.base_url, timeout=per_call + 5, transport=_transport) as client:
                r = client.get(
                    f"/v1/approvals/{request_id}/wait",
                    params={"timeout": per_call},
                    headers=headers,
                )
        except httpx.HTTPError as e:
            raise HubDegradedError(f"GET wait failed: {type(e).__name__}: {e}") from e

        if r.status_code != 200:
            raise HubDegradedError(f"GET wait returned {r.status_code}: {r.text[:200]}")

        body = r.json()
        if body.get("status") != "pending":
            return body
        # 仍 pending, loop 再來

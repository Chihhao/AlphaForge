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
from dataclasses import dataclass


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

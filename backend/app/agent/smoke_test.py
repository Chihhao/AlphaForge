from __future__ import annotations
from dataclasses import dataclass, field
from typing import List
import httpx


@dataclass
class SmokeResult:
    ok: bool
    checks: List[str] = field(default_factory=list)
    failures: List[str] = field(default_factory=list)


_ENDPOINTS = [
    "/market/system-events",
    "/strategy-miner/picks/today",
    "/health",  # 若不存在, 200 / 404 都當 ok; 500 才算紅
]


def run_smoke(base_url: str, timeout: float = 5.0) -> SmokeResult:
    checks: List[str] = []
    failures: List[str] = []
    for ep in _ENDPOINTS:
        url = base_url.rstrip("/") + ep
        checks.append(url)
        try:
            resp = httpx.get(url, timeout=timeout)
            if resp.status_code >= 500:
                failures.append(f"{url} -> {resp.status_code}")
            # 4xx 視為 endpoint 存在但 no content, 不算紅
        except Exception as exc:
            failures.append(f"{url} -> {type(exc).__name__}: {exc}")
    return SmokeResult(ok=len(failures) == 0, checks=checks, failures=failures)

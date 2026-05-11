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

import hashlib
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Union

import httpx


TAIPEI_TZ = timezone(timedelta(hours=8))


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


def _slugify(s: str, max_len: int = 50) -> str:
    """中文友善的 slugify: 留 a-z 0-9 與 CJK, 其餘 → '-'。"""
    s = s.lower()
    s = re.sub(r"[^a-z0-9一-鿿]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s[:max_len] or "untitled"


def _repo_root_proposals_dir() -> Path:
    """notify_hub_client.py 在 backend/app/agent/, parents[3] = repo root。"""
    return Path(__file__).resolve().parents[3] / "docs" / "proposals"


def _fallback_to_proposals(
    items: list[dict],
    title: str,
    date: str,
    request_id: str | None = None,
    proposals_dir: Union[Path, str, None] = None,
) -> Path:
    """Hub 失效時落盤一份 proposal markdown。
    proposals_dir=None 用 repo_root/docs/proposals/ (基於 __file__ 推導, cwd 無關)。
    Return: 寫入的 file path。
    """
    if proposals_dir is None:
        proposals_dir = _repo_root_proposals_dir()
    proposals_dir = Path(proposals_dir)
    proposals_dir.mkdir(parents=True, exist_ok=True)

    slug = _slugify(title)
    base_name = f"{date}-{slug}"
    candidate = proposals_dir / f"{base_name}.md"
    if candidate.exists():
        title_hash = hashlib.sha256(title.encode("utf-8")).hexdigest()[:4]
        candidate = proposals_dir / f"{base_name}-{title_hash}.md"
        # 仍 collision 再加 timestamp
        if candidate.exists():
            ts = datetime.now(TAIPEI_TZ).strftime("%H%M%S")
            candidate = proposals_dir / f"{base_name}-{title_hash}-{ts}.md"

    now = datetime.now(TAIPEI_TZ).strftime("%Y-%m-%d %H:%M")
    request_id_field = request_id if request_id else "null"
    lines = [
        "---",
        "status: pending",
        f"created_at: {now}",
        f"slug: {slug}",
        "reason: notify-hub unreachable; agent fallback (HubDegradedError)",
        f"request_id: {request_id_field}",
        "---",
        "",
        f"# {title}",
        "",
    ]
    for i, item in enumerate(items, 1):
        item_type = item.get("type", "unknown")
        summary = item.get("summary", "")
        detail = item.get("detail")
        lines.append(f"## Item {i}: {item_type} — {summary}")
        lines.append("")
        if detail:
            lines.append(detail)
            lines.append("")

    lines.append("---")
    lines.append("備援: 看完用 `git mv docs/proposals/<this>.md docs/proposals/approved/` 表態。")
    lines.append("")

    candidate.write_text("\n".join(lines), encoding="utf-8")
    return candidate


def approve_and_wait(
    project: str,
    title: str,
    items: list[dict],
    timeout_seconds: int = 1200,
    idempotency_key: str | None = None,
    metadata: dict | None = None,
    proposals_dir: Union[Path, str, None] = None,
    _transport: httpx.BaseTransport | None = None,
) -> dict:
    """Sync mode: POST + long-poll wait, hub 失效自動 fallback to docs/proposals/。

    Return shape:
      {"status": "approved" | "rejected", "decided_at": "...", "per_item": [...]}
      {"status": "timeout", "request_id": "..."}
      {"status": "degraded", "proposal_path": "docs/proposals/..."}

    `proposals_dir=None` 用 repo_root/docs/proposals/ (基於 __file__ 推導);
    給測試 inject tmp_path; `_transport` 給測試 inject MockTransport。
    """
    date_str = datetime.now(TAIPEI_TZ).strftime("%Y-%m-%d")
    request_id: str | None = None

    try:
        request_id = approve_request(
            project=project, title=title, items=items,
            timeout_seconds=timeout_seconds,
            idempotency_key=idempotency_key,
            metadata=metadata,
            _transport=_transport,
        )
    except HubDegradedError:
        path = _fallback_to_proposals(
            items=items, title=title, date=date_str,
            request_id=None, proposals_dir=proposals_dir,
        )
        return {"status": "degraded", "proposal_path": str(path)}

    try:
        result = wait_result(
            request_id=request_id,
            overall_timeout_seconds=timeout_seconds,
            _transport=_transport,
        )
    except HubDegradedError:
        path = _fallback_to_proposals(
            items=items, title=title, date=date_str,
            request_id=request_id, proposals_dir=proposals_dir,
        )
        return {"status": "degraded", "proposal_path": str(path)}

    return result

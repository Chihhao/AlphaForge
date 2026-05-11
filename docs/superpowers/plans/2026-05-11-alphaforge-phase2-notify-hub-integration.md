###### tags: `專案`,`AlphaForge`,`Phase 2`,`Plan`

# AlphaForge Phase 2 — notify-hub 整合 Implementation Plan

`文件版本: 2026-05-11a`

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** AlphaForge night tick Stage 6 透過 `notify_hub_client` 推 pending proposals 到 user Telegram, hub 失效 fallback 落 `docs/proposals/`, e2e 跑通一次。

**Architecture:** 新增 `backend/app/agent/notify_hub_client.py` Python module (高層 `approve_and_wait` + 低階 `approve_request`/`wait_result` + 內部 fallback), 跟 Phase 1 helpers 同 pattern; `tick_night.md` Stage 6 改寫為具體 Bash 呼叫; 用 httpx 內建 `MockTransport` 做 unit / integration test, 不新增 dependency。

**Tech Stack:** Python 3.11+, httpx (`MockTransport` mock), pytest (Phase 1 已用), notify-hub v0.1.0 (NAS, 已上線)。

**Spec:** `docs/superpowers/specs/2026-05-11-alphaforge-phase2-notify-hub-integration-design.md`

---

## File Structure

**新增**:
- `backend/app/agent/notify_hub_client.py` — 主 module, ~200 行
- `backend/tests/test_agent_notify_hub_client.py` — unit + integration tests (用 `MockTransport`)
- `backend/scripts/notify_hub_e2e.py` — e2e 手動驗收 script
- `backend/.env.example` — 環境變數範本 (新建; 若已存在 append)
- `docs/proposals/.gitkeep` — 目錄占位 (若 dir 已存在 skip)

**修改**:
- `backend/app/agent/prompts/tick_night.md` line 56-61 — Stage 6 改寫
- `backend/requirements.txt` — **不動** (httpx 已裝)
- `backend/.env` — user 自填, **不在 plan 範圍**

**不動**:
- Phase 1 helpers (`deploy_lock` / `path_tier` / `smoke_test` / `site_restore` / `alpha_ledger` / `report_builder`)
- `tick_evening.md` (T0 體檢型, 無 Stage 6, 不需 approval)
- `agent_run.py`、launchd plist / wrapper
- notify-hub repo (read-side only)

---

## Task 1: 骨架 + ConfigError + env 讀取

**Files:**
- Create: `backend/app/agent/notify_hub_client.py`
- Create: `backend/tests/test_agent_notify_hub_client.py`

- [ ] **Step 1: 寫 failing test (ConfigError when env missing)**

寫到 `backend/tests/test_agent_notify_hub_client.py`:

```python
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
```

- [ ] **Step 2: 跑 test 看到 fail**

```bash
cd backend && ./.venv/bin/pytest tests/test_agent_notify_hub_client.py -v
```

預期: `ModuleNotFoundError: No module named 'app.agent.notify_hub_client'` (RED 正確)

- [ ] **Step 3: 寫 minimal 實作**

寫 `backend/app/agent/notify_hub_client.py`:

```python
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
```

- [ ] **Step 4: 跑 test 看到 pass**

```bash
cd backend && ./.venv/bin/pytest tests/test_agent_notify_hub_client.py -v
```

預期: 3 passed

- [ ] **Step 5: commit**

```bash
git add backend/app/agent/notify_hub_client.py backend/tests/test_agent_notify_hub_client.py
git commit -m "feat(agent): notify_hub_client skeleton + ConfigError"
```

---

## Task 2: approve_request() — POST + mock tests

**Files:**
- Modify: `backend/app/agent/notify_hub_client.py`
- Modify: `backend/tests/test_agent_notify_hub_client.py`

- [ ] **Step 1: 寫 failing tests (POST 201 / ConnectError / 401)**

加到 `backend/tests/test_agent_notify_hub_client.py`:

```python
import httpx

from app.agent.notify_hub_client import (
    HubDegradedError,
    approve_request,
)


def _mock_transport(handler):
    return httpx.MockTransport(handler)


def _env(monkeypatch):
    monkeypatch.setenv("NOTIFY_HUB_URL", "https://example.com/nh")
    monkeypatch.setenv("NOTIFY_HUB_TOKEN", "af_test")


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
```

- [ ] **Step 2: 跑 test 看到 fail**

```bash
cd backend && ./.venv/bin/pytest tests/test_agent_notify_hub_client.py::test_approve_request_201_returns_id -v
```

預期: `ImportError: cannot import name 'approve_request'` (RED 正確)

- [ ] **Step 3: 寫 minimal 實作**

把以下加進 `backend/app/agent/notify_hub_client.py` 結尾:

```python
import httpx


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
```

- [ ] **Step 4: 跑 test 看到 pass**

```bash
cd backend && ./.venv/bin/pytest tests/test_agent_notify_hub_client.py -v
```

預期: 6 passed (3 from Task 1 + 3 new)

- [ ] **Step 5: commit**

```bash
git add backend/app/agent/notify_hub_client.py backend/tests/test_agent_notify_hub_client.py
git commit -m "feat(agent): approve_request POST + httpx MockTransport tests"
```

---

## Task 3: wait_result() — long-poll loop

**Files:**
- Modify: `backend/app/agent/notify_hub_client.py`
- Modify: `backend/tests/test_agent_notify_hub_client.py`

- [ ] **Step 1: 寫 failing tests (一次 / 多 round / overall timeout)**

加到 test 檔結尾:

```python
from app.agent.notify_hub_client import wait_result


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
        overall_timeout_seconds=1,   # 馬上 timeout (per-call 也 cap 到 1s)
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
```

- [ ] **Step 2: 跑 test 看到 fail**

```bash
cd backend && ./.venv/bin/pytest tests/test_agent_notify_hub_client.py::test_wait_result_first_call_approved -v
```

預期: `ImportError: cannot import name 'wait_result'`

- [ ] **Step 3: 寫實作**

加進 `backend/app/agent/notify_hub_client.py`:

```python
import time


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
```

- [ ] **Step 4: 跑 test 看到 pass**

```bash
cd backend && ./.venv/bin/pytest tests/test_agent_notify_hub_client.py -v
```

預期: 10 passed

- [ ] **Step 5: commit**

```bash
git add backend/app/agent/notify_hub_client.py backend/tests/test_agent_notify_hub_client.py
git commit -m "feat(agent): wait_result long-poll loop"
```

---

## Task 4: _fallback_to_proposals() — degraded path 檔案寫入

**Files:**
- Modify: `backend/app/agent/notify_hub_client.py`
- Modify: `backend/tests/test_agent_notify_hub_client.py`

- [ ] **Step 1: 寫 failing tests (format / slug / collision)**

加到 test 檔結尾:

```python
from pathlib import Path

from app.agent.notify_hub_client import _fallback_to_proposals


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
```

- [ ] **Step 2: 跑 test 看到 fail**

```bash
cd backend && ./.venv/bin/pytest tests/test_agent_notify_hub_client.py::test_fallback_writes_file_with_frontmatter -v
```

預期: `ImportError`

- [ ] **Step 3: 寫實作**

加進 `backend/app/agent/notify_hub_client.py`:

```python
import hashlib
import re
from pathlib import Path
from datetime import datetime, timezone, timedelta


TAIPEI_TZ = timezone(timedelta(hours=8))


def _slugify(s: str, max_len: int = 50) -> str:
    s = s.lower()
    s = re.sub(r"[^a-z0-9一-鿿]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s[:max_len] or "untitled"


def _fallback_to_proposals(
    items: list[dict],
    title: str,
    date: str,
    request_id: str | None = None,
    proposals_dir: Path | str = Path("docs/proposals"),
) -> Path:
    """Hub 失效時落盤一份 proposal markdown。
    Return: 寫入的 file path (相對或絕對, 依 proposals_dir)。
    """
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
```

- [ ] **Step 4: 跑 test 看到 pass**

```bash
cd backend && ./.venv/bin/pytest tests/test_agent_notify_hub_client.py -v
```

預期: 14 passed

- [ ] **Step 5: commit**

```bash
git add backend/app/agent/notify_hub_client.py backend/tests/test_agent_notify_hub_client.py
git commit -m "feat(agent): _fallback_to_proposals with slug + collision handling"
```

---

## Task 5: approve_and_wait() — 高層 wrap + fallback dispatch

**Files:**
- Modify: `backend/app/agent/notify_hub_client.py`
- Modify: `backend/tests/test_agent_notify_hub_client.py`

- [ ] **Step 1: 寫 failing tests (happy / POST fail fallback / wait fail fallback / timeout)**

加到 test 檔結尾:

```python
from app.agent.notify_hub_client import approve_and_wait


def test_approve_and_wait_happy(monkeypatch, tmp_path):
    _env(monkeypatch)
    state = {"posted": False}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            state["posted"] = True
            return httpx.Response(201, json={
                "request_id": "abc",
                "status": "pending",
                "created_at": "2026-05-11T03:00:00Z",
                "expires_at": "2026-05-11T03:20:00Z",
                "push_state": "pushed",
            })
        # wait
        return httpx.Response(200, json={
            "request_id": "abc", "status": "approved",
            "decided_at": "2026-05-11T03:05:00Z",
            "per_item": [{"id": "1", "decision": "approved", "reject_reason": None}],
        })

    result = approve_and_wait(
        project="alphaforge",
        title="t",
        items=[{"id": "1", "type": "t3", "summary": "s"}],
        timeout_seconds=60,
        proposals_dir=tmp_path,
        _transport=_mock_transport(handler),
    )
    assert state["posted"]
    assert result["status"] == "approved"


def test_approve_and_wait_post_fail_fallback(monkeypatch, tmp_path):
    _env(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    items = [{"id": "1", "type": "t3", "summary": "s", "detail": "d"}]
    result = approve_and_wait(
        project="alphaforge",
        title="2026-05-11 night",
        items=items,
        timeout_seconds=60,
        proposals_dir=tmp_path,
        _transport=_mock_transport(handler),
    )
    assert result["status"] == "degraded"
    proposal = Path(result["proposal_path"])
    assert proposal.exists()
    content = proposal.read_text(encoding="utf-8")
    assert "request_id: null" in content
    assert "Item 1: t3 — s" in content


def test_approve_and_wait_wait_fail_fallback_with_request_id(monkeypatch, tmp_path):
    _env(monkeypatch)
    state = {"phase": "post"}

    def handler(request: httpx.Request) -> httpx.Response:
        if state["phase"] == "post":
            state["phase"] = "wait"
            return httpx.Response(201, json={
                "request_id": "abc-123",
                "status": "pending",
                "created_at": "2026-05-11T03:00:00Z",
                "expires_at": "2026-05-11T03:20:00Z",
                "push_state": "pushed",
            })
        raise httpx.ConnectError("down during wait")

    result = approve_and_wait(
        project="alphaforge",
        title="t",
        items=[{"id": "1", "type": "t3", "summary": "s"}],
        timeout_seconds=60,
        proposals_dir=tmp_path,
        _transport=_mock_transport(handler),
    )
    assert result["status"] == "degraded"
    assert "request_id: abc-123" in Path(result["proposal_path"]).read_text(encoding="utf-8")


def test_approve_and_wait_overall_timeout(monkeypatch, tmp_path):
    _env(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(201, json={
                "request_id": "abc",
                "status": "pending",
                "created_at": "2026-05-11T03:00:00Z",
                "expires_at": "2026-05-11T03:20:00Z",
                "push_state": "pushed",
            })
        return httpx.Response(200, json={
            "request_id": "abc", "status": "pending", "per_item": [],
        })

    result = approve_and_wait(
        project="alphaforge", title="t",
        items=[{"id": "1", "type": "t3", "summary": "s"}],
        timeout_seconds=1,
        proposals_dir=tmp_path,
        _transport=_mock_transport(handler),
    )
    assert result["status"] == "timeout"
    assert result["request_id"] == "abc"
```

- [ ] **Step 2: 跑 test 看到 fail**

```bash
cd backend && ./.venv/bin/pytest tests/test_agent_notify_hub_client.py::test_approve_and_wait_happy -v
```

預期: `ImportError`

- [ ] **Step 3: 寫實作**

加進 `backend/app/agent/notify_hub_client.py`:

```python
def approve_and_wait(
    project: str,
    title: str,
    items: list[dict],
    timeout_seconds: int = 1200,
    idempotency_key: str | None = None,
    metadata: dict | None = None,
    proposals_dir: Path | str = Path("docs/proposals"),
    _transport: httpx.BaseTransport | None = None,
) -> dict:
    """Sync mode: POST + long-poll wait, hub 失效自動 fallback to docs/proposals/。

    Return shape:
      {"status": "approved" | "rejected", "decided_at": "...", "per_item": [...]}
      {"status": "timeout", "request_id": "..."}
      {"status": "degraded", "proposal_path": "docs/proposals/..."}

    `proposals_dir` 給測試 inject tmp_path; production 預設 docs/proposals/。
    `_transport` 給測試 inject MockTransport。
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
```

- [ ] **Step 4: 跑 test 看到 pass**

```bash
cd backend && ./.venv/bin/pytest tests/test_agent_notify_hub_client.py -v
```

預期: 18 passed

- [ ] **Step 5: commit**

```bash
git add backend/app/agent/notify_hub_client.py backend/tests/test_agent_notify_hub_client.py
git commit -m "feat(agent): approve_and_wait high-level API + fallback dispatch"
```

---

## Task 6: tick_night.md Stage 6 改寫

**Files:**
- Modify: `backend/app/agent/prompts/tick_night.md` (line 56-61)

- [ ] **Step 1: 開啟現有檔, 確認舊內容 (line 56-61)**

```bash
sed -n '56,61p' backend/app/agent/prompts/tick_night.md
```

預期 (placeholder 版):

```
### Stage 6: Approval (若 notify-hub 已上線)
累積 pending proposals → 呼叫 `notify_hub.approve_request(...)`, 策略:
- T3 action (本 tick 需落地) → sync (timeout 1200 sec)
- Memory / frontend / budget → async

**Hub 失效或未實作**: 所有 proposal 落盤 `docs/proposals/<slug>.md`, 寄 `[CRITICAL]` 通知使用者用 git mv 備援。
```

- [ ] **Step 2: 用 Edit tool 改寫 Stage 6 段**

替換 line 56-61 為以下內容 (Edit old_string = 上方 Step 1 預期內容, new_string = 下方):

````markdown
### Stage 6: Approval (notify-hub 整合, Phase 2)

累積本 tick 的 pending proposals (Stage 5 各題的 T3 action / memory-add / time-extension / frontend-proposal), 用以下 Bash 跑 (assemble `items_json` 是上一步累積的清單):

```bash
cd backend && ./.venv/bin/python -c "
import json, sys, hashlib, datetime
sys.path.insert(0, '.')
from app.agent.notify_hub_client import approve_and_wait

items = json.loads(r'''<JSON_ARRAY_OF_ITEMS_FROM_STAGE_5>''')
title = f'{datetime.date.today().isoformat()} night tick — {len(items)} 項待批准'
idem = f'{datetime.date.today().isoformat()}-night-' + hashlib.sha256(title.encode()).hexdigest()[:8]

result = approve_and_wait(
    project='alphaforge',
    title=title,
    items=items,
    timeout_seconds=1200,
    idempotency_key=idem,
)
print(json.dumps(result, ensure_ascii=False))
"
```

依 stdout 的 `status` 欄位 dispatch:

- `approved` → 執行各 item (T3 commit + smoke_test / memory-add 寫檔 / 其餘 type 對應動作); 日報記 `## Approval` 段含 per_item.decision
- `rejected` → skip 對應 item; 日報註記 per_item 的 `reject_reason`
- `timeout` → 寫日報 `## Approval timeout (request_id=<id>) — 隔天人工處理`, T3 全 skip
- `degraded` →
  1. 用 `mcp__claude_ai_Gmail__send` tool 寄 `[AlphaForge][CRITICAL] notify-hub 失效, 落盤 <proposal_path>` 給自己
  2. 日報註記 `## Hub 失效 fallback (proposal_path=<path>)`
  3. T3 全 skip (T2 in-backlog 仍可做)

**Hub 失效或未實作**: helper 內自動 fallback 落盤 `docs/proposals/<slug>.md`, agent 看 `status='degraded'` 自己寄 Gmail。
````

- [ ] **Step 3: 驗證 prompt 還能跑 agent_run --dry-run**

```bash
cd backend && ./.venv/bin/python -m scripts.agent_run --tick=night --dry-run | head -80
```

預期: 印 prompt 含新的 Stage 6 段, 看到 `notify_hub_client` import 字樣。

- [ ] **Step 4: commit**

```bash
git add backend/app/agent/prompts/tick_night.md
git commit -m "feat(prompt): night tick Stage 6 — concrete notify_hub_client call"
```

---

## Task 7: backend/.env.example + e2e script

**Files:**
- Create: `backend/.env.example` (若不存在), 或 Modify (若存在)
- Create: `backend/scripts/notify_hub_e2e.py`
- Create: `docs/proposals/.gitkeep`

- [ ] **Step 1: 檢查 .env.example 現況**

```bash
ls -la backend/.env.example 2>&1 | head -3
```

- [ ] **Step 2: 寫 .env.example**

如果不存在, 新建:

```bash
cat > backend/.env.example << 'EOF'
# notify-hub integration (Phase 2)
NOTIFY_HUB_URL=https://notify.example.com/notify-hub
NOTIFY_HUB_TOKEN=af_xxxx
EOF
```

如果存在, 用 Edit tool 把上述兩行 append 到檔尾 (確認沒重複)。

- [ ] **Step 3: 寫 e2e script**

寫到 `backend/scripts/notify_hub_e2e.py`:

```python
"""End-to-end smoke test against real NAS notify-hub.

需要 backend/.env 設好 NOTIFY_HUB_URL / NOTIFY_HUB_TOKEN。

Usage (從 backend/ 目錄):
    ./.venv/bin/python -m scripts.notify_hub_e2e

預期: 你手機 Telegram 收到一則 "Phase 2 e2e test" 與兩個按鈕, 按一個,
script 印 status=approved / rejected。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def main() -> int:
    repo_backend = Path(__file__).resolve().parents[1]
    _load_env_file(repo_backend / ".env")
    sys.path.insert(0, str(repo_backend))

    from app.agent.notify_hub_client import approve_and_wait

    items = [
        {"id": "1", "type": "test", "summary": "Phase 2 e2e — 按我同意", "detail": "本訊號為測試, 不會落地任何動作。"},
        {"id": "2", "type": "test", "summary": "Phase 2 e2e — 按我拒絕", "detail": "本訊號為測試。"},
    ]
    title = "Phase 2 e2e test"
    print(f"approve_and_wait title={title!r} ...")
    result = approve_and_wait(
        project="alphaforge",
        title=title,
        items=items,
        timeout_seconds=180,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] in ("approved", "rejected") else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 建 docs/proposals/ 目錄 (若不存在)**

```bash
mkdir -p docs/proposals && touch docs/proposals/.gitkeep
```

- [ ] **Step 5: commit (env.example + script + dir)**

```bash
git add backend/.env.example backend/scripts/notify_hub_e2e.py docs/proposals/.gitkeep
git commit -m "feat(agent): backend/.env.example, e2e script, docs/proposals/ dir"
```

---

## Task 8: E2E 手動驗收 (真實 NAS notify-hub)

**Files:**
- Create: `docs/reports/YYYY-MM-DD-phase2-e2e.md` (e2e 結果記錄)

**前置條件**:
- `backend/.env` 已填 `NOTIFY_HUB_URL=https://junesnow39.synology.me/notify-hub` 與 `NOTIFY_HUB_TOKEN=<af_token>`
- notify-hub v0.1.0 在 NAS 跑著 (healthz 200)
- Telegram bot 已 setWebhook + 你手機/桌面 Telegram 開著

- [ ] **Step 1: 先確認 notify-hub healthz**

```bash
curl https://junesnow39.synology.me/notify-hub/healthz
```

預期: `{"db":"ok","telegram":"ok",...}`

- [ ] **Step 2: 跑 e2e script**

```bash
cd backend && ./.venv/bin/python -m scripts.notify_hub_e2e
```

預期 stdout:
```
approve_and_wait title='Phase 2 e2e test' ...
```
(script 卡住 long-poll, 等你按按鈕)

- [ ] **Step 3: Telegram 端按按鈕**

你手機 / 桌面 Telegram 收到 `[alphaforge] Phase 2 e2e test` 與 [全部同意] / [全部拒絕] / [逐項決定] 按鈕。**按 [全部同意]**。

- [ ] **Step 4: 確認 script 收到 approved**

回 terminal, script 應該幾秒內 print:

```json
{
  "status": "approved",
  "decided_at": "...",
  "per_item": [
    {"id": "1", "decision": "approved", "reject_reason": null},
    {"id": "2", "decision": "approved", "reject_reason": null}
  ]
}
```

exit code 0。

- [ ] **Step 5: 失敗模式測試 (可選)**

故意把 `NOTIFY_HUB_URL` 改成 unreachable (`https://invalid.example.com/nh`), 跑 e2e:

```bash
NOTIFY_HUB_URL=https://invalid.example.com/nh cd backend && ./.venv/bin/python -m scripts.notify_hub_e2e
```

預期: 印 `{"status": "degraded", "proposal_path": "docs/proposals/..."}`, exit code 1, 檔案落盤。

清理: `rm docs/proposals/<那份 .md>` (測試產生的)。

- [ ] **Step 6: 寫 e2e 報告**

```bash
DATE=$(date +%Y-%m-%d)
cat > docs/reports/$DATE-phase2-e2e.md << 'EOF'
###### tags: `日報`,`Phase 2`,`e2e`

# Phase 2 e2e 驗收

`文件版本: 2026-05-11a`

## 結果

- happy path: ✅ status=approved
- degraded path: ✅ status=degraded, 落盤 docs/proposals/<slug>.md
- e2e 跑通

## notify-hub healthz

(貼 step 1 結果)

## script stdout

(貼 step 2-4 結果)

## 觀察

- (任何意外行為)

END: ok
EOF
```

填入實際結果後 commit:

```bash
git add docs/reports/$DATE-phase2-e2e.md
git commit -m "report: phase 2 e2e 驗收通過"
```

---

## Task 9: memory + 收尾

**Files:**
- Modify: `/Users/chihhaolai/.claude/projects/-Users-chihhaolai-Documents-GitHub-AlphaForge/memory/project_next_steps.md`
- Modify: `/Users/chihhaolai/.claude/projects/-Users-chihhaolai-Documents-GitHub-AlphaForge/memory/MEMORY.md`

- [ ] **Step 1: 更新 project_next_steps.md (Phase 2 完成)**

用 Edit tool 在 `## 2026-05-09~10 — notify-hub v0.1.0 完整上線 (webhook SSL 已修)` 上方 (按時間倒序) 新增段落:

```markdown
## 2026-05-11 — AlphaForge Phase 2 上線 (agent ↔ notify-hub 整合)

**Status**:
- ✅ `backend/app/agent/notify_hub_client.py` (approve_and_wait + 低階 approve_request / wait_result + _fallback_to_proposals); 18 unit tests pass
- ✅ `tick_night.md` Stage 6 改寫為具體 `python -c "from app.agent.notify_hub_client import ..."` Bash 呼叫
- ✅ `backend/.env.example` 加 NOTIFY_HUB_URL / NOTIFY_HUB_TOKEN
- ✅ e2e 驗收 (status=approved + degraded path 雙路驗證), 詳 `docs/reports/2026-05-11-phase2-e2e.md`
- Spec: `docs/superpowers/specs/2026-05-11-alphaforge-phase2-notify-hub-integration-design.md`
- Plan: `docs/superpowers/plans/2026-05-11-alphaforge-phase2-notify-hub-integration.md`

**Out of scope (Phase 3 候選)**:
- async mode (memory-add 不 block agent)
- /task command (Telegram → agent worker daemon)
- launchd cron 啟用 (Phase 1 plist 已寫, user 自己 `./scripts/agent_install_launchd.sh`)

**下一步**:
- launchd 啟用 + 半夜 03:00 真的跑出第一個 night tick 觀察
- 或進 AlphaForge 主線 (5d IC 0.049 提升 / 20d 歷史 backfill / trading-day bug)
```

- [ ] **Step 2: 更新 MEMORY.md 索引 description**

把 `project_next_steps.md` 索引行 description 改成:

```
- [project_next_steps.md](project_next_steps.md) — 2026-05-11 AlphaForge Phase 2 上線, agent ↔ notify-hub 整合 e2e 過; notify-hub v0.1.0 也完整上線
```

- [ ] **Step 3: 跑全套 backend regression**

```bash
cd backend && ./.venv/bin/python -m pytest -q
```

預期: 全部 pass (Phase 1 88 tests + Phase 2 ~18 new tests, 約 106 pass)。

- [ ] **Step 4: 收尾 commit**

memory 變更不在 git repo (在 ~/.claude/), 不 commit。所有 backend / docs 變更在前面 task 已 commit 完。

跑 `git log --oneline | head -15` 確認所有 Phase 2 commits 在 main, 把 commit 範圍寫到 e2e 報告。

```bash
git log --oneline | head -15
```

預期看到 ~9 個 Phase 2 commit + Task 8 的 e2e 報告 commit。

---

## Self-Review Checklist (寫完 plan 後跑一次)

- [x] **Spec coverage**: spec §1.1 in-scope 5 項 → Task 1-7 覆蓋; §6 testing 三層 → Task 1-5 unit, Task 5 integration 合併, Task 8 e2e
- [x] **Placeholder scan**: 沒看到 TBD/TODO; `<JSON_ARRAY_OF_ITEMS_FROM_STAGE_5>` 是 prompt template 不是 plan placeholder
- [x] **Type consistency**: `approve_request` / `wait_result` / `approve_and_wait` 在 Task 2/3/5 signature 一致; `_fallback_to_proposals(items, title, date, request_id=None, proposals_dir=...)` 用法在 Task 4/5 一致
- [x] **Order**: Task 1-5 純 backend code TDD, Task 6 prompt, Task 7 env+script, Task 8 e2e, Task 9 memory — 沒前後依賴問題

## 風險與緩解

- **risk**: NAS notify-hub e2e 階段 webhook 失效 (例如 DSM GUI 動了 reverse proxy → SNI block 被蓋). **緩解**: e2e 步驟前先 curl healthz; 若 webhook 看 getWebhookInfo 有 last_error, 跑 `ssh chihhaolai@10.0.4.3 'sudo sh /tmp/swap-reverseproxy.sh && sudo nginx -s reload'` reapply。
- **risk**: `backend/.env` 被誤 commit. **緩解**: 確認 `backend/.gitignore` 含 `.env` (應該已含, 但 plan 跑前先 `git check-ignore backend/.env` 驗一次)。
- **risk**: 同名 idempotency_key 衝突 (兩個 tick 同日跑 → notify-hub 視同重送). **緩解**: idempotency_key 含 `tick_type` (night vs evening), title_hash 有 8 chars entropy 夠避免衝突。

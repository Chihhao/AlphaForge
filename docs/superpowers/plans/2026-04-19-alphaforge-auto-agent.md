###### tags: `專案`,`AlphaForge`,`自動化`,`計畫`

# AlphaForge Auto Agent — Implementation Plan (Phase 1: Infrastructure)

`文件版本: 2026-04-19a`

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立 AlphaForge auto agent 的 infrastructure 基礎 (Python helpers + tick prompts + launchd 排程 + 現場還原 / 日報產生器), 讓 agent 在 notify-hub 上線前可用 fallback (git mv approved/) 模式跑 dry-run。

**Architecture:** 所有 agent 行為靠 `claude -p <prompt>` 觸發, prompt 讀 `backend/app/agent/prompts/tick_*.md`, helper 位於 `backend/app/agent/`, launchd 負責排程 18:30 / 03:00, 不依賴 notify-hub 的功能先用 fallback 實作。

**Tech Stack:** Python 3, pytest, macOS launchd, FastAPI (既有), Docker (既有), Claude Code CLI headless mode。

**Spec reference:** `docs/superpowers/specs/2026-04-19-alphaforge-auto-agent-design.md`

**範圍 (本 plan 不含)**:
- notify-hub 整合 (依賴外部 spec, 另一 plan)
- 真正接 LLM 執行 alpha 研究決策 (本 plan 產物可跑 prompt 骨架, 但需 notify-hub 上線才啟動完整 pipeline)
- 前端改動 (spec T3 規則)

---

## File Structure

### 新建
```
backend/app/agent/
├── __init__.py
├── deploy_lock.py           # deploy-lock.json 狀態機
├── path_tier.py             # 依檔案路徑判 Tier
├── smoke_test.py            # API health check
├── site_restore.py          # 現場還原 checklist
├── alpha_ledger.py          # 近 N 日 IC / wr 查詢
├── report_builder.py        # 日報骨架產生器
└── prompts/
    ├── tick_evening.md      # 18:30 tick prompt
    └── tick_night.md        # 03:00 tick prompt

backend/scripts/
└── agent_run.py             # CLI entry: python -m scripts.agent_run --tick=evening|night

backend/tests/
├── test_agent_deploy_lock.py
├── test_agent_path_tier.py
├── test_agent_smoke_test.py
├── test_agent_site_restore.py
├── test_agent_alpha_ledger.py
└── test_agent_report_builder.py

scripts/
├── agent_run_evening.sh     # launchd wrapper
└── agent_run_night.sh

launchd/
├── com.alphaforge.agent.evening.plist
└── com.alphaforge.agent.night.plist

docs/
├── reports/.gitkeep
├── reports/interrupted/.gitkeep
├── proposals/.gitkeep
├── proposals/approved/.gitkeep
├── proposals/rejected/.gitkeep
├── proposals/executed/.gitkeep
├── proposals/stale/.gitkeep
├── proposals/mockups/.gitkeep
├── inbox/.gitkeep
├── inbox/processed/.gitkeep
└── state/.gitkeep
```

### 職責界定
- **`deploy_lock.py`**: 只管 `docs/state/deploy-lock.json` 的讀寫 + 狀態機 (`absent → in_progress → success → released`)。
- **`path_tier.py`**: 輸入檔案路徑, 回傳 Tier (T0-T3)。純 function, 路徑 pattern 硬寫在 spec §3 的 table。
- **`smoke_test.py`**: HTTP GET 3 個 endpoint, 回 `(ok: bool, detail: str)`。不處理 retry。
- **`site_restore.py`**: Stage 0 checklist 邏輯整合 (git status / deploy-lock / report END / memory index), 回 `SiteReport` dataclass。
- **`alpha_ledger.py`**: 讀 DB 算近 N 日 `strategy_miner_picks` 的 IC / wr, 供 alpha ledger 段使用。
- **`report_builder.py`**: 產生日報 markdown 骨架 (含強制 alpha ledger + 可逆清單段)。
- **`agent_run.py`**: CLI entry, 讀 prompt + 執行 Stage 0 site_restore + 印出 prompt 到 stdout (給 `claude -p` pipe)。
- **Launchd plist**: 跑 wrapper shell。
- **Wrapper shell**: `cd` 到 repo + 呼叫 `claude -p "$(python -m scripts.agent_run --tick=night)"` + log 到 `~/Library/Logs/AlphaForgeAgent/`。

---

## Phase 0: 目錄與模組 skeleton

### Task 0.1: 建立所有目錄 + `.gitkeep` + 空模組

**Files:**
- Create: `docs/reports/.gitkeep`, `docs/reports/interrupted/.gitkeep`, `docs/proposals/.gitkeep`, `docs/proposals/approved/.gitkeep`, `docs/proposals/rejected/.gitkeep`, `docs/proposals/executed/.gitkeep`, `docs/proposals/stale/.gitkeep`, `docs/proposals/mockups/.gitkeep`, `docs/inbox/.gitkeep`, `docs/inbox/processed/.gitkeep`, `docs/state/.gitkeep`
- Create: `backend/app/agent/__init__.py` (空檔)
- Create: `backend/app/agent/prompts/` (空目錄, 加 `.gitkeep`)
- Create: `launchd/.gitkeep`

- [ ] **Step 1: 建目錄與 .gitkeep**

```bash
cd /Users/chihhaolai/Documents/GitHub/AlphaForge
for d in docs/reports docs/reports/interrupted \
         docs/proposals docs/proposals/approved docs/proposals/rejected \
         docs/proposals/executed docs/proposals/stale docs/proposals/mockups \
         docs/inbox docs/inbox/processed docs/state \
         backend/app/agent backend/app/agent/prompts launchd; do
  mkdir -p "$d"
  touch "$d/.gitkeep"
done
echo "" > backend/app/agent/__init__.py
```

- [ ] **Step 2: Commit**

```bash
git add docs/reports docs/proposals docs/inbox docs/state \
        backend/app/agent launchd
git commit -m "agent(infra): scaffold directories for auto agent

- docs/reports|proposals|inbox|state
- backend/app/agent module skeleton
- launchd directory for plists

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Phase 1: Python Helpers (TDD)

### Task 1.1: `deploy_lock.py` — deploy-lock 狀態機

**Files:**
- Create: `backend/app/agent/deploy_lock.py`
- Create: `backend/tests/test_agent_deploy_lock.py`

- [ ] **Step 1: Write failing test**

Create `backend/tests/test_agent_deploy_lock.py`:
```python
import json
from pathlib import Path
import pytest
from backend.app.agent.deploy_lock import (
    DeployLock, LockStatus, load, begin, advance, release, absent,
)


def test_absent_when_file_missing(tmp_path: Path):
    lock_file = tmp_path / "deploy-lock.json"
    assert absent(lock_file) is True
    assert load(lock_file) is None


def test_begin_writes_in_progress(tmp_path: Path):
    lock_file = tmp_path / "deploy-lock.json"
    lock = begin(
        lock_file,
        tick="0300",
        previous_commit_sha="abc",
        previous_backend_image="alphaforge-backend:20260419",
        new_commit_sha="def",
    )
    assert lock.status == LockStatus.IN_PROGRESS
    loaded = load(lock_file)
    assert loaded.status == LockStatus.IN_PROGRESS
    assert loaded.new_commit_sha == "def"


def test_advance_in_progress_to_success(tmp_path: Path):
    lock_file = tmp_path / "deploy-lock.json"
    begin(lock_file, tick="0300", previous_commit_sha="a",
          previous_backend_image="img", new_commit_sha="b")
    advanced = advance(lock_file, LockStatus.SUCCESS)
    assert advanced.status == LockStatus.SUCCESS


def test_release_after_success(tmp_path: Path):
    lock_file = tmp_path / "deploy-lock.json"
    begin(lock_file, tick="0300", previous_commit_sha="a",
          previous_backend_image="img", new_commit_sha="b")
    advance(lock_file, LockStatus.SUCCESS)
    released = release(lock_file)
    assert released.status == LockStatus.RELEASED


def test_advance_rejects_invalid_transition(tmp_path: Path):
    lock_file = tmp_path / "deploy-lock.json"
    begin(lock_file, tick="0300", previous_commit_sha="a",
          previous_backend_image="img", new_commit_sha="b")
    with pytest.raises(ValueError, match="invalid transition"):
        advance(lock_file, LockStatus.RELEASED)  # must go through SUCCESS
```

- [ ] **Step 2: Run test to confirm FAIL**

```bash
cd /Users/chihhaolai/Documents/GitHub/AlphaForge
./backend/.venv/bin/python -m pytest backend/tests/test_agent_deploy_lock.py -v
```
Expected: `ModuleNotFoundError: No module named 'backend.app.agent.deploy_lock'`

- [ ] **Step 3: Implement `deploy_lock.py`**

Create `backend/app/agent/deploy_lock.py`:
```python
from __future__ import annotations
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from enum import Enum
from pathlib import Path
from typing import Optional

TAIPEI_TZ = timezone(timedelta(hours=8))


class LockStatus(str, Enum):
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    RELEASED = "released"


@dataclass
class DeployLock:
    timestamp: str
    tick: str
    previous_commit_sha: str
    previous_backend_image: str
    new_commit_sha: str
    status: LockStatus

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "DeployLock":
        return cls(
            timestamp=d["timestamp"],
            tick=d["tick"],
            previous_commit_sha=d["previous_commit_sha"],
            previous_backend_image=d["previous_backend_image"],
            new_commit_sha=d["new_commit_sha"],
            status=LockStatus(d["status"]),
        )


def absent(lock_file: Path) -> bool:
    return not lock_file.exists()


def load(lock_file: Path) -> Optional[DeployLock]:
    if absent(lock_file):
        return None
    with lock_file.open("r") as f:
        return DeployLock.from_dict(json.load(f))


def _write(lock_file: Path, lock: DeployLock) -> None:
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    with lock_file.open("w") as f:
        json.dump(lock.to_dict(), f, indent=2)


def begin(lock_file: Path, *, tick: str, previous_commit_sha: str,
          previous_backend_image: str, new_commit_sha: str) -> DeployLock:
    lock = DeployLock(
        timestamp=datetime.now(TAIPEI_TZ).isoformat(),
        tick=tick,
        previous_commit_sha=previous_commit_sha,
        previous_backend_image=previous_backend_image,
        new_commit_sha=new_commit_sha,
        status=LockStatus.IN_PROGRESS,
    )
    _write(lock_file, lock)
    return lock


_VALID_TRANSITIONS = {
    LockStatus.IN_PROGRESS: {LockStatus.SUCCESS},
    LockStatus.SUCCESS: {LockStatus.RELEASED},
}


def advance(lock_file: Path, to: LockStatus) -> DeployLock:
    lock = load(lock_file)
    if lock is None:
        raise ValueError("no lock file to advance")
    if to not in _VALID_TRANSITIONS.get(lock.status, set()):
        raise ValueError(f"invalid transition {lock.status.value} -> {to.value}")
    lock.status = to
    lock.timestamp = datetime.now(TAIPEI_TZ).isoformat()
    _write(lock_file, lock)
    return lock


def release(lock_file: Path) -> DeployLock:
    return advance(lock_file, LockStatus.RELEASED)
```

- [ ] **Step 4: Run test to verify PASS**

```bash
./backend/.venv/bin/python -m pytest backend/tests/test_agent_deploy_lock.py -v
```
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/deploy_lock.py backend/tests/test_agent_deploy_lock.py
git commit -m "agent(infra): deploy-lock state machine

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 1.2: `path_tier.py` — 路徑 Tier 判定

**Files:**
- Create: `backend/app/agent/path_tier.py`
- Create: `backend/tests/test_agent_path_tier.py`

- [ ] **Step 1: Write failing test**

Create `backend/tests/test_agent_path_tier.py`:
```python
import pytest
from backend.app.agent.path_tier import classify, Tier


@pytest.mark.parametrize("path,expected", [
    ("backend/app/services/alpha_miner_service.py", Tier.T2),
    ("backend/app/api/endpoints/picks.py", Tier.T2),
    ("backend/app/models/stock.py", Tier.T2),
    ("backend/scripts/research_decay.py", Tier.T1),
    ("backend/scripts/diag_something.py", Tier.T1),
    ("backend/scripts/backfill_prices.py", Tier.T2),  # existing prod script
    ("docs/reports/2026-04-19-0300.md", Tier.T1),
    ("docs/state/deploy-lock.json", Tier.T3),  # state 屬 T3 硬擋
    ("frontend/pages/index.tsx", Tier.T3),
    ("backend/app/core/scheduler.py", Tier.T3),
    ("backend/alembic/versions/abc123_xxx.py", Tier.T3),
    ("backend/app/core/database.py", Tier.T3),
    ("docker-compose.yml", Tier.T3),
    ("Dockerfile", Tier.T3),
    ("deploy.sh", Tier.T3),
    ("backend/requirements.txt", Tier.T3),
    (".claude/settings.json", Tier.T3),
    ("CLAUDE.md", Tier.T3),
])
def test_classify(path, expected):
    assert classify(path) == expected


def test_unknown_path_defaults_to_t3():
    assert classify("some/random/path.txt") == Tier.T3
```

- [ ] **Step 2: Run test to confirm FAIL**

```bash
./backend/.venv/bin/python -m pytest backend/tests/test_agent_path_tier.py -v
```
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `path_tier.py`**

Create `backend/app/agent/path_tier.py`:
```python
from __future__ import annotations
import re
from enum import IntEnum


class Tier(IntEnum):
    T0 = 0   # read-only, 不改檔
    T1 = 1   # research scripts + docs
    T2 = 2   # production code with preconditions
    T3 = 3   # blocked, proposal only


_T3_PATTERNS = [
    re.compile(r"^frontend/"),
    re.compile(r"^backend/app/core/scheduler\.py$"),
    re.compile(r"^backend/app/core/database\.py$"),
    re.compile(r"^backend/alembic/"),
    re.compile(r"^docker-compose.*\.ya?ml$"),
    re.compile(r"^Dockerfile"),
    re.compile(r"^deploy\.sh$"),
    re.compile(r"^start_dev\.sh$"),
    re.compile(r"^backend/requirements\.txt$"),
    re.compile(r"^\.claude/"),
    re.compile(r"^CLAUDE\.md$"),
    re.compile(r"^docs/state/"),
]

_T1_PATTERNS = [
    re.compile(r"^backend/scripts/research_"),
    re.compile(r"^backend/scripts/diag_"),
    re.compile(r"^docs/(?!state/)"),  # docs/ 除 docs/state
]

_T2_PATTERNS = [
    re.compile(r"^backend/app/services/"),
    re.compile(r"^backend/app/api/endpoints/"),
    re.compile(r"^backend/app/models/"),
    re.compile(r"^backend/app/schemas/"),
    re.compile(r"^backend/app/logic/"),
    re.compile(r"^backend/app/core/indicators\.py$"),
    re.compile(r"^backend/app/agent/"),   # agent 模組自己
    re.compile(r"^backend/scripts/"),     # 其他既有 scripts (backfill etc.)
    re.compile(r"^backend/tests/"),
]


def classify(path: str) -> Tier:
    for p in _T3_PATTERNS:
        if p.match(path):
            return Tier.T3
    for p in _T1_PATTERNS:
        if p.match(path):
            return Tier.T1
    for p in _T2_PATTERNS:
        if p.match(path):
            return Tier.T2
    return Tier.T3  # unknown → 硬擋
```

- [ ] **Step 4: Run test to verify PASS**

```bash
./backend/.venv/bin/python -m pytest backend/tests/test_agent_path_tier.py -v
```
Expected: 18 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/path_tier.py backend/tests/test_agent_path_tier.py
git commit -m "agent(infra): path→Tier classifier

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 1.3: `smoke_test.py` — API health check

**Files:**
- Create: `backend/app/agent/smoke_test.py`
- Create: `backend/tests/test_agent_smoke_test.py`

- [ ] **Step 1: Write failing test**

Create `backend/tests/test_agent_smoke_test.py`:
```python
from unittest.mock import patch, MagicMock
from backend.app.agent.smoke_test import run_smoke, SmokeResult


def _fake_response(status: int, body: dict | None = None):
    m = MagicMock()
    m.status_code = status
    m.json.return_value = body or {}
    return m


def test_smoke_all_green():
    with patch("backend.app.agent.smoke_test.httpx.get") as g:
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
    with patch("backend.app.agent.smoke_test.httpx.get", side_effect=side_effect):
        result = run_smoke(base_url="http://localhost:8000")
    assert result.ok is False
    assert any("picks/today" in f for f in result.failures)


def test_smoke_network_error_is_failure():
    import httpx
    with patch("backend.app.agent.smoke_test.httpx.get",
               side_effect=httpx.ConnectError("boom")):
        result = run_smoke(base_url="http://localhost:8000")
    assert result.ok is False
    assert len(result.failures) == 3
```

- [ ] **Step 2: Run test to confirm FAIL**

```bash
./backend/.venv/bin/python -m pytest backend/tests/test_agent_smoke_test.py -v
```
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `smoke_test.py`**

Create `backend/app/agent/smoke_test.py`:
```python
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
```

- [ ] **Step 4: Run test to verify PASS**

```bash
./backend/.venv/bin/python -m pytest backend/tests/test_agent_smoke_test.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/smoke_test.py backend/tests/test_agent_smoke_test.py
git commit -m "agent(infra): smoke test for backend API health

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 1.4: `site_restore.py` — 現場還原 checklist

**Files:**
- Create: `backend/app/agent/site_restore.py`
- Create: `backend/tests/test_agent_site_restore.py`

- [ ] **Step 1: Write failing test**

Create `backend/tests/test_agent_site_restore.py`:
```python
import subprocess
from pathlib import Path
from unittest.mock import patch
from backend.app.agent.site_restore import run_checklist, SiteReport


def _git_init(tmp_path: Path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    (tmp_path / "x.txt").write_text("x")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True)


def test_clean_repo_no_lock_no_report(tmp_path: Path):
    _git_init(tmp_path)
    report = run_checklist(repo_root=tmp_path)
    assert isinstance(report, SiteReport)
    assert report.git_dirty is False
    assert report.stale_lock is False
    assert report.critical is False


def test_dirty_repo_flags_critical(tmp_path: Path):
    _git_init(tmp_path)
    (tmp_path / "dirty.txt").write_text("uncommitted")
    report = run_checklist(repo_root=tmp_path)
    assert report.git_dirty is True
    assert report.critical is True


def test_stale_in_progress_lock_flags_critical(tmp_path: Path):
    _git_init(tmp_path)
    from backend.app.agent.deploy_lock import begin
    import time
    lock_file = tmp_path / "docs/state/deploy-lock.json"
    begin(lock_file, tick="0300", previous_commit_sha="a",
          previous_backend_image="img", new_commit_sha="b")
    # 假裝 30 分鐘前開始
    with patch("backend.app.agent.site_restore._now_minus_minutes", return_value=31):
        report = run_checklist(repo_root=tmp_path)
    assert report.stale_lock is True
    assert report.critical is True
```

- [ ] **Step 2: Run test to confirm FAIL**

```bash
./backend/.venv/bin/python -m pytest backend/tests/test_agent_site_restore.py -v
```
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `site_restore.py`**

Create `backend/app/agent/site_restore.py`:
```python
from __future__ import annotations
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List
from backend.app.agent.deploy_lock import load as load_lock, LockStatus

TAIPEI_TZ = timezone(timedelta(hours=8))
STALE_THRESHOLD_MIN = 30


@dataclass
class SiteReport:
    git_dirty: bool = False
    stale_lock: bool = False
    missing_end_marker: bool = False
    critical: bool = False
    findings: List[str] = field(default_factory=list)


def _git_status(repo_root: Path) -> str:
    r = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_root, capture_output=True, text=True, check=True,
    )
    return r.stdout.strip()


def _now_minus_minutes(iso_timestamp: str) -> float:
    ts = datetime.fromisoformat(iso_timestamp)
    now = datetime.now(TAIPEI_TZ)
    return (now - ts).total_seconds() / 60


def run_checklist(repo_root: Path) -> SiteReport:
    report = SiteReport()

    # git status
    dirty = _git_status(repo_root)
    if dirty:
        report.git_dirty = True
        report.critical = True
        report.findings.append(f"git status unclean:\n{dirty}")

    # deploy-lock 過時 in_progress
    lock_file = repo_root / "docs" / "state" / "deploy-lock.json"
    lock = load_lock(lock_file)
    if lock is not None and lock.status == LockStatus.IN_PROGRESS:
        age_min = _now_minus_minutes(lock.timestamp)
        if age_min > STALE_THRESHOLD_MIN:
            report.stale_lock = True
            report.critical = True
            report.findings.append(
                f"deploy-lock in_progress {age_min:.1f} min, possibly stale"
            )

    # 最近 report 是否有 END 標記
    reports_dir = repo_root / "docs" / "reports"
    if reports_dir.exists():
        md_files = sorted(reports_dir.glob("*.md"), reverse=True)
        if md_files:
            latest = md_files[0].read_text()
            if "END:" not in latest:
                report.missing_end_marker = True
                report.critical = True
                report.findings.append(f"{md_files[0].name} 缺 END 標記, 前次 tick 可能被砍")

    return report
```

- [ ] **Step 4: Run test to verify PASS**

```bash
./backend/.venv/bin/python -m pytest backend/tests/test_agent_site_restore.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/site_restore.py backend/tests/test_agent_site_restore.py
git commit -m "agent(infra): site restore checklist

- git status 檢查
- deploy-lock 過時 in_progress 偵測
- 最近 report END 標記檢查

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 1.5: `alpha_ledger.py` — 近 N 日 IC / wr 查詢

**Files:**
- Create: `backend/app/agent/alpha_ledger.py`
- Create: `backend/tests/test_agent_alpha_ledger.py`

**Note:** 此 helper 讀既有 `strategy_miner_picks` 表。DB 連線沿用 `backend/app/db/session.py` (既有)。

- [ ] **Step 1: Read existing DB session helper**

```bash
grep -n "def get_db\|SessionLocal\|async_session" /Users/chihhaolai/Documents/GitHub/AlphaForge/backend/app/db/session.py
```
Expected: 看到 `SessionLocal` / `get_db` 等 API, 記下正確 import 路徑。

- [ ] **Step 2: Write failing test**

Create `backend/tests/test_agent_alpha_ledger.py`:
```python
from datetime import date, timedelta
from unittest.mock import MagicMock, patch
from backend.app.agent.alpha_ledger import LedgerEntry, summarise


def test_summarise_with_closed_picks():
    fake_rows = [
        # (direction, time_dimension, return_pct, concluded_reason)
        ("long", "5d", 0.03, "tp"),
        ("long", "5d", -0.02, "sl"),
        ("long", "5d", 0.01, "time_limit"),
        ("long", "10d", 0.05, "tp"),
        ("long", "20d", 0.08, "tp"),
    ]
    fake_session = MagicMock()
    fake_session.execute.return_value.all.return_value = fake_rows

    with patch("backend.app.agent.alpha_ledger.SessionLocal", return_value=fake_session):
        result = summarise(days=7)

    assert isinstance(result, dict)
    assert "5d" in result
    assert result["5d"].n == 3
    assert result["5d"].wr == pytest.approx(2/3, abs=0.01) or result["5d"].wr == pytest.approx(1/3, abs=0.01)


def test_summarise_empty_returns_zeros():
    fake_session = MagicMock()
    fake_session.execute.return_value.all.return_value = []
    with patch("backend.app.agent.alpha_ledger.SessionLocal", return_value=fake_session):
        result = summarise(days=7)
    # 允許回空 dict 或各維度 n=0
    for dim in ("5d", "10d", "20d"):
        if dim in result:
            assert result[dim].n == 0
```

**Note**: 加 `import pytest` 在檔首。

- [ ] **Step 3: Run test to confirm FAIL**

```bash
./backend/.venv/bin/python -m pytest backend/tests/test_agent_alpha_ledger.py -v
```
Expected: `ModuleNotFoundError`.

- [ ] **Step 4: Implement `alpha_ledger.py`**

Create `backend/app/agent/alpha_ledger.py`:
```python
from __future__ import annotations
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict
from sqlalchemy import text
from backend.app.db.session import SessionLocal


@dataclass
class LedgerEntry:
    dimension: str          # "5d" | "10d" | "20d"
    n: int
    wr: float               # win rate (% 報酬 > 0)
    avg_return: float       # 平均報酬 (e.g. 0.025 表 +2.5%)


def _rows_to_entries(rows) -> Dict[str, LedgerEntry]:
    from collections import defaultdict
    agg: Dict[str, list] = defaultdict(list)
    for direction, dim, ret_pct, reason in rows:
        if reason is None or ret_pct is None:
            continue
        agg[dim].append(ret_pct)
    out: Dict[str, LedgerEntry] = {}
    for dim, returns in agg.items():
        n = len(returns)
        if n == 0:
            out[dim] = LedgerEntry(dim, 0, 0.0, 0.0)
            continue
        wins = sum(1 for r in returns if r > 0)
        wr = wins / n
        avg = sum(returns) / n
        out[dim] = LedgerEntry(dim, n, wr, avg)
    return out


def summarise(days: int = 7) -> Dict[str, LedgerEntry]:
    """讀近 `days` 內結案 picks, 依 time_dimension 匯總 wr / avg_return。"""
    cutoff = date.today() - timedelta(days=days)
    session = SessionLocal()
    try:
        rows = session.execute(text("""
            SELECT direction, time_dimension, return_pct, concluded_reason
            FROM strategy_miner_picks
            WHERE concluded_at IS NOT NULL
              AND concluded_at >= :cutoff
        """), {"cutoff": cutoff}).all()
        return _rows_to_entries(rows)
    finally:
        session.close()
```

- [ ] **Step 5: Run test to verify PASS**

```bash
./backend/.venv/bin/python -m pytest backend/tests/test_agent_alpha_ledger.py -v
```
Expected: 2 passed (第一個 test 的 wr 斷言預期 2/3: tp (0.03) + time_limit (0.01) 都 > 0, sl (-0.02) 為負, 故 wr = 2/3)。

- [ ] **Step 6: Commit**

```bash
git add backend/app/agent/alpha_ledger.py backend/tests/test_agent_alpha_ledger.py
git commit -m "agent(infra): alpha ledger summary (IC/wr by dimension)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 1.6: `report_builder.py` — 日報骨架產生器

**Files:**
- Create: `backend/app/agent/report_builder.py`
- Create: `backend/tests/test_agent_report_builder.py`

- [ ] **Step 1: Write failing test**

Create `backend/tests/test_agent_report_builder.py`:
```python
from datetime import date
from backend.app.agent.report_builder import build_evening_skeleton, build_night_skeleton


def test_evening_skeleton_has_mandatory_sections():
    md = build_evening_skeleton(report_date=date(2026, 4, 20))
    assert "# 2026-04-20 Evening Tick (18:30)" in md
    assert "## 產線體檢" in md
    assert "## Alpha ledger" in md
    assert "## 可逆清單" in md
    assert "END:" in md  # 尾端 END 標記


def test_night_skeleton_has_mandatory_sections():
    md = build_night_skeleton(report_date=date(2026, 4, 20))
    assert "# 2026-04-20 Night Tick (03:00)" in md
    assert "## 候選題 + Gate 2 checklist" in md
    assert "## 執行摘要" in md
    assert "## Alpha ledger" in md
    assert "## 可逆清單" in md
    assert "END:" in md
```

- [ ] **Step 2: Run test to confirm FAIL**

```bash
./backend/.venv/bin/python -m pytest backend/tests/test_agent_report_builder.py -v
```
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `report_builder.py`**

Create `backend/app/agent/report_builder.py`:
```python
from __future__ import annotations
from datetime import date


def build_evening_skeleton(report_date: date) -> str:
    d = report_date.strftime("%Y-%m-%d")
    return f"""###### tags: `AlphaForge`,`agent-report`,`evening`

# {d} Evening Tick (18:30)

`文件版本: {d}a`

## 產線體檢
- [ ] scheduler jobs 15:30 / 16:30 / 17:00 / 17:20 / 17:30 / 18:10 綠燈
- [ ] feature row count + null%
- [ ] fundamentals 覆蓋率
- [ ] 17:30 模型重訓 IC / loss
- [ ] 昨日 picks 結案 (tp / sl / time_limit)
- [ ] 近 7 日 picks 勝率退化
- [ ] GET /picks/today 健康

## 異常分流
(若無異常寫「無」, 若有寫入 docs/inbox/alert-*.md 並於此列連結)

## Alpha ledger
- 本 tick IC / wr / avg_top 變化: 未測 (T0 體檢不跑研究)
- 新發現: -
- 否證: -
- 下一步候選: -

## 可逆清單
(T0 tick 不 commit production, 應為空)

END: ok
"""


def build_night_skeleton(report_date: date) -> str:
    d = report_date.strftime("%Y-%m-%d")
    return f"""###### tags: `AlphaForge`,`agent-report`,`night`

# {d} Night Tick (03:00)

`文件版本: {d}a`

## 現場還原結果
(引用 site_restore checklist)

## 候選題 + Gate 2 checklist
### 題 1: <主題>
- [ ] Alpha-first
- [ ] 有 benchmark
- [ ] 含 long-short
- [ ] 先診斷根因
- [ ] 不偽造數據
- [ ] Partial IC 非充分
- [ ] 100% 結果找偏差
- [ ] 資料正確性優先
→ 判定: PASS/FAIL, Tier: T?

### 棄選清單
(列 Gate 2 fail 的題, 附理由)

## 執行摘要
- 選題: <主題>
- Tier: T?
- 動作: <commit SHA 清單, 跑的 script, deploy 結果>

## Alpha ledger
- 本 tick IC / wr / avg_top 變化: <數字>
- 新發現: <一句>
- 否證: <一句>
- 下一步候選: <一行>

## 可逆清單
- commit <sha>: <說明>
  rollback: git revert <sha>
- deploy <ts> backend:<sha>
  rollback: docker tag alphaforge-backend:<previous> alphaforge-backend:latest && ./deploy.sh 3

## Pending approvals (若有)
(列 notify-hub 已發但未回的 proposal; hub 未實作時寫入 docs/proposals/ 等 git mv)

END: ok | deployed | aborted
"""
```

- [ ] **Step 4: Run test to verify PASS**

```bash
./backend/.venv/bin/python -m pytest backend/tests/test_agent_report_builder.py -v
```
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/report_builder.py backend/tests/test_agent_report_builder.py
git commit -m "agent(infra): report skeleton builder (evening + night)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Phase 2: Agent CLI Entry

### Task 2.1: `agent_run.py` CLI + site_restore 整合

**Files:**
- Create: `backend/scripts/agent_run.py`
- Create: `backend/tests/test_agent_run_cli.py`

- [ ] **Step 1: Write failing test**

Create `backend/tests/test_agent_run_cli.py`:
```python
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_cli_evening_prints_prompt():
    r = subprocess.run(
        [sys.executable, "-m", "backend.scripts.agent_run", "--tick=evening", "--dry-run"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    assert "Evening" in r.stdout or "evening" in r.stdout
    assert "site_restore" in r.stdout.lower()


def test_cli_night_prints_prompt():
    r = subprocess.run(
        [sys.executable, "-m", "backend.scripts.agent_run", "--tick=night", "--dry-run"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    assert "Night" in r.stdout or "night" in r.stdout


def test_cli_unknown_tick_fails():
    r = subprocess.run(
        [sys.executable, "-m", "backend.scripts.agent_run", "--tick=noon", "--dry-run"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert r.returncode != 0
```

- [ ] **Step 2: Run test to confirm FAIL**

```bash
./backend/.venv/bin/python -m pytest backend/tests/test_agent_run_cli.py -v
```
Expected: `No module named backend.scripts.agent_run`.

- [ ] **Step 3: Ensure `backend/scripts/__init__.py` exists**

```bash
ls backend/scripts/__init__.py 2>/dev/null || touch backend/scripts/__init__.py
```

- [ ] **Step 4: Implement `agent_run.py`**

Create `backend/scripts/agent_run.py`:
```python
"""
Agent CLI entry. 被 launchd wrapper 呼叫, 輸出完整 tick prompt 到 stdout,
由上游 pipe 給 `claude -p` 執行。

Usage:
    python -m backend.scripts.agent_run --tick=evening
    python -m backend.scripts.agent_run --tick=night
    python -m backend.scripts.agent_run --tick=night --dry-run  # 不執行 site_restore, 只印 prompt 骨架
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PROMPT_DIR = REPO_ROOT / "backend" / "app" / "agent" / "prompts"

VALID_TICKS = {"evening", "night"}


def _load_prompt(tick: str) -> str:
    fn = PROMPT_DIR / f"tick_{tick}.md"
    if not fn.exists():
        return f"# {tick.capitalize()} Tick prompt (placeholder, tick_{tick}.md not yet created)"
    return fn.read_text()


def _render_site_restore_section(dry_run: bool) -> str:
    if dry_run:
        return "## site_restore (dry-run, skipped)\n"
    from backend.app.agent.site_restore import run_checklist
    report = run_checklist(repo_root=REPO_ROOT)
    lines = ["## site_restore 結果"]
    lines.append(f"- git_dirty: {report.git_dirty}")
    lines.append(f"- stale_lock: {report.stale_lock}")
    lines.append(f"- missing_end_marker: {report.missing_end_marker}")
    lines.append(f"- critical: {report.critical}")
    if report.findings:
        lines.append("### findings")
        for f in report.findings:
            lines.append(f"- {f}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tick", required=True, help="evening | night")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    if args.tick not in VALID_TICKS:
        print(f"unknown tick '{args.tick}', expected {VALID_TICKS}", file=sys.stderr)
        return 2

    sections = [
        _load_prompt(args.tick),
        _render_site_restore_section(dry_run=args.dry_run),
    ]
    print("\n\n".join(sections))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run test to verify PASS**

```bash
./backend/.venv/bin/python -m pytest backend/tests/test_agent_run_cli.py -v
```
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/scripts/__init__.py backend/scripts/agent_run.py backend/tests/test_agent_run_cli.py
git commit -m "agent(infra): CLI entry agent_run.py

- --tick=evening|night loads tick prompt
- --dry-run skips site_restore for testing
- prints full prompt to stdout for upstream claude -p pipe

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Phase 3: Tick Prompts

### Task 3.1: Evening tick prompt

**Files:**
- Create: `backend/app/agent/prompts/tick_evening.md`

- [ ] **Step 1: 建立 prompt**

Create `backend/app/agent/prompts/tick_evening.md`:
```markdown
# AlphaForge Evening Tick (18:30) — Prompt

你是 AlphaForge 的自動 agent。本 tick 為 **T0 體檢型**, **只讀不改**。

## 工作上下文
- 時間: 台灣時間 18:30
- 資料狀態: 17:30 模型重訓完、18:10 訊號儲存完, 但 21:00 融券尚未補
- 授權上限: T0 (除了 `docs/reports/**` 與 `docs/inbox/**` 外不得寫入任何檔案)
- Spec: `docs/superpowers/specs/2026-04-19-alphaforge-auto-agent-design.md`

## Gate 1: 必讀
1. `/Users/chihhaolai/.claude/projects/-Users-chihhaolai-Documents-GitHub-AlphaForge/memory/MEMORY.md` 全部 feedback
2. `memory/project_next_steps.md`
3. `docs/reports/` 近 3 個 md
4. 下方「site_restore 結果」段 (已由 runner 附上)

## 任務清單 (依序)
1. 跑產線體檢 7 項 (spec §2 Evening tick Stage 2):
   - scheduler job log 全綠 (15:30 / 16:30 / 17:00 / 17:20 / 17:30 / 18:10)
   - 今日 feature 表 row count + null%
   - 今日 fundamentals 覆蓋率
   - 17:30 模型重訓 IC / loss 合理性
   - 昨日 picks 結案分佈 (tp / sl / time_limit)
   - 近 7 日 picks 勝率是否退化
   - GET `http://localhost:8000/strategy-miner/picks/today` 200 OK
2. 使用 `backend.app.agent.report_builder.build_evening_skeleton(date.today())` 產生骨架, 填入實際結果
3. 若有異常, 寫 `docs/inbox/alert-YYYY-MM-DD-<slug>.md` 塞給 03:00 tick
4. Commit report + (若有) alert inbox:
   `git commit -m "agent(1830): report - daily health check"`
5. 發 Gmail:
   - 正常: `[AlphaForge] YYYY-MM-DD 18:30 完成` (INFO)
   - 異常非關鍵: `[AlphaForge][WARN] 18:30 發現 N 項異常`
   - 關鍵異常 (scheduler 紅 / fundamentals 缺 / API 500): `[AlphaForge][CRITICAL] ...`

## 禁忌
- 禁改 `backend/app/**` 任何檔案
- 禁 deploy
- 禁動 memory 檔 (要提議記 inbox 或 proposal)

## 結束條件
- Report 寫完且含 `END: ok` 標記
- Gmail 已寄
- git working tree 乾淨 (除新增的 report / inbox)
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/agent/prompts/tick_evening.md
git commit -m "agent(infra): evening tick prompt

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 3.2: Night tick prompt

**Files:**
- Create: `backend/app/agent/prompts/tick_night.md`

- [ ] **Step 1: 建立 prompt**

Create `backend/app/agent/prompts/tick_night.md`:
```markdown
# AlphaForge Night Tick (03:00) — Prompt

你是 AlphaForge 的自動 agent。本 tick 為**主力 tick**, 授權 T0-T2。**找 alpha 是唯一目標**。

## 工作上下文
- 時間: 台灣時間 03:00
- 資料狀態: 21:00 融券補抓已完成, 全量資料到位
- 授權上限: T2 (T3 僅能寫 proposal)
- 時長上限: 120 分鐘 (超時需提 `docs/proposals/YYYY-MM-DD-budget-*.md`)
- Token 預算: 剩 < 20% 進入收尾模式, < 10% 立即 abort
- Spec: `docs/superpowers/specs/2026-04-19-alphaforge-auto-agent-design.md`

## Gate 1: 必讀
1. `/Users/chihhaolai/.claude/projects/-Users-chihhaolai-Documents-GitHub-AlphaForge/memory/MEMORY.md` 全部 feedback
2. `memory/project_next_steps.md`
3. `docs/reports/` 近 3 個 md
4. 今日 18:30 report (若存在)
5. `docs/inbox/alert-*.md` 與 `docs/inbox/*.md` (去 `processed/` 後剩下的)
6. `git log --oneline -n 20`
7. 下方「site_restore 結果」段

## 任務流程 (Stage-based)

### Stage 2: 選題 (優先序)
A) `docs/inbox/alert-*.md` (18:30 自產異常)
B) `docs/inbox/*.md` (使用者塞題)
C) `docs/state/deploy-lock.json` 若為殘局 (`in_progress` > 30min 或 `success` 未 `released`) → 先處理
D) `memory/project_next_steps.md` backlog (P2/P3)
E) Agent 自主新因子研究 → 只能落 T1 (research script), 不進 production

### Stage 3: Gate 2 — feedback checklist
對每個候選題, 逐項檢查 (列在日報):
- [ ] Alpha-first (能否提升 5d / 10d / 20d IC / wr / avg_top?)
- [ ] 有 benchmark 對照
- [ ] 含 long-short validation
- [ ] 先診斷根因才動手
- [ ] 不偽造數據
- [ ] Partial IC 非充分條件
- [ ] 100% 結果先找偏差
- [ ] 資料正確性優先

**任一 fail → 棄選該題, 改下一候選。Refactor-only 題每週 ≤ 1 次。**

### Stage 4: Tier 判定 (使用 `backend.app.agent.path_tier.classify`)
- T0 / T1: 直接做
- T2: 需題目已在 `project_next_steps.md` 或有昨日 approved proposal
- T3: 只寫 proposal (`docs/proposals/YYYY-MM-DD-t3-<slug>.md`)

### Stage 5: 執行
- 一題一 commit
- 改 production → 跑 `./backend/.venv/bin/python -m pytest backend/tests/<相關模組>`
- Deploy: 前先 `backend.app.agent.deploy_lock.begin(...)`, deploy 完呼 `smoke_test.run_smoke("http://localhost:8000")`
- Smoke 紅 → `git reset --hard <tick_start_sha>` + docker tag rollback + `[CRITICAL]` email
- Smoke 綠 → `deploy_lock.advance(... SUCCESS)`

### Stage 6: Approval (若 notify-hub 已上線)
累積 pending proposals → 呼叫 `notify_hub.approve_request(...)`, 策略:
- T3 action (本 tick 需落地) → sync (timeout 1200 sec)
- Memory / frontend / budget → async

**Hub 失效或未實作**: 所有 proposal 落盤 `docs/proposals/<slug>.md`, 寄 `[CRITICAL]` 通知使用者用 git mv 備援。

### Stage 7: 收尾
- 用 `report_builder.build_night_skeleton(date.today())` 產生日報骨架
- 填入 Alpha ledger (呼叫 `alpha_ledger.summarise(days=7)`)
- 填入可逆清單 (commit SHA + docker image tag)
- `deploy_lock.release(...)`
- Commit all `docs/` changes
- 發 Gmail 摘要

## 禁忌 (硬擋)
- 禁改 `frontend/**`, `backend/app/core/scheduler.py`, `backend/app/core/database.py`, `backend/alembic/**`, `docker-compose*.yml`, `Dockerfile*`, `deploy.sh`, `start_dev.sh`, `backend/requirements.txt`, `.claude/**`, `CLAUDE.md`
- 禁改 memory 檔 (要寫 `docs/proposals/YYYY-MM-DD-memory-*.md`)
- 禁 `git push --force`
- 禁開新 branch (main-only)
- 每週 refactor-only 題 ≤ 1 次

## Alpha ledger (日報強制段)
```
## Alpha ledger
- 本 tick IC / wr / avg_top 變化: <數字 or 未測>
- 新發現: <一句>
- 否證: <一句>
- 下一步候選: <一行>
```

## 結束條件
- Report 寫完且含 `END: ok | deployed | aborted` 標記
- Git working tree 乾淨
- Gmail 已寄
- `deploy_lock` 為 `released` 或 `absent`
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/agent/prompts/tick_night.md
git commit -m "agent(infra): night tick prompt

Core prompt for the main 03:00 tick:
- Stage-based execution (選題 → Gate 2 → Tier → 執行 → approval → 收尾)
- Alpha-first hard rule + mandatory alpha ledger
- Safety rules + hub-unavailable fallback

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Phase 4: Launchd Infrastructure

### Task 4.1: Launchd wrapper shell + plist

**Files:**
- Create: `scripts/agent_run_evening.sh`
- Create: `scripts/agent_run_night.sh`
- Create: `launchd/com.alphaforge.agent.evening.plist`
- Create: `launchd/com.alphaforge.agent.night.plist`
- Create: `scripts/agent_install_launchd.sh` (install/uninstall helper)

- [ ] **Step 1: 建立 evening wrapper**

Create `scripts/agent_run_evening.sh`:
```bash
#!/bin/bash
# AlphaForge agent evening tick wrapper (18:30)
set -euo pipefail

REPO="/Users/chihhaolai/Documents/GitHub/AlphaForge"
LOG_DIR="$HOME/Library/Logs/AlphaForgeAgent"
mkdir -p "$LOG_DIR"
TS=$(date +"%Y-%m-%d_%H%M")
LOG="$LOG_DIR/evening-$TS.log"

cd "$REPO"

{
  echo "=== evening tick start $TS ==="

  PROMPT=$("$REPO/backend/.venv/bin/python" -m backend.scripts.agent_run --tick=evening)

  if [[ -z "$PROMPT" ]]; then
    echo "ERROR: empty prompt from agent_run"
    exit 1
  fi

  # 未整合 claude -p 前, 只印 prompt 做 dry-run 驗證
  if [[ "${AGENT_DRY_RUN:-0}" == "1" ]]; then
    echo "$PROMPT"
  else
    # TODO (phase2): pipe 到 claude -p, 待 notify-hub 上線後啟用
    echo "[phase1] prompt-only mode, not invoking claude -p"
    echo "$PROMPT"
  fi

  echo "=== evening tick end ==="
} >> "$LOG" 2>&1
```

- [ ] **Step 2: 建立 night wrapper (複製改 tick 名)**

Create `scripts/agent_run_night.sh`:
```bash
#!/bin/bash
# AlphaForge agent night tick wrapper (03:00)
set -euo pipefail

REPO="/Users/chihhaolai/Documents/GitHub/AlphaForge"
LOG_DIR="$HOME/Library/Logs/AlphaForgeAgent"
mkdir -p "$LOG_DIR"
TS=$(date +"%Y-%m-%d_%H%M")
LOG="$LOG_DIR/night-$TS.log"

cd "$REPO"

{
  echo "=== night tick start $TS ==="

  PROMPT=$("$REPO/backend/.venv/bin/python" -m backend.scripts.agent_run --tick=night)

  if [[ -z "$PROMPT" ]]; then
    echo "ERROR: empty prompt from agent_run"
    exit 1
  fi

  if [[ "${AGENT_DRY_RUN:-0}" == "1" ]]; then
    echo "$PROMPT"
  else
    echo "[phase1] prompt-only mode, not invoking claude -p"
    echo "$PROMPT"
  fi

  echo "=== night tick end ==="
} >> "$LOG" 2>&1
```

- [ ] **Step 3: 賦予執行權**

```bash
chmod +x scripts/agent_run_evening.sh scripts/agent_run_night.sh
```

- [ ] **Step 4: 建立 launchd plist (evening)**

Create `launchd/com.alphaforge.agent.evening.plist`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.alphaforge.agent.evening</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>/Users/chihhaolai/Documents/GitHub/AlphaForge/scripts/agent_run_evening.sh</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key><integer>18</integer>
    <key>Minute</key><integer>30</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>/Users/chihhaolai/Library/Logs/AlphaForgeAgent/evening-launchd.out</string>
  <key>StandardErrorPath</key>
  <string>/Users/chihhaolai/Library/Logs/AlphaForgeAgent/evening-launchd.err</string>
  <key>TimeoutInterval</key>
  <integer>3600</integer>
</dict>
</plist>
```

- [ ] **Step 5: 建立 launchd plist (night)**

Create `launchd/com.alphaforge.agent.night.plist`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.alphaforge.agent.night</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>/Users/chihhaolai/Documents/GitHub/AlphaForge/scripts/agent_run_night.sh</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key><integer>3</integer>
    <key>Minute</key><integer>0</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>/Users/chihhaolai/Library/Logs/AlphaForgeAgent/night-launchd.out</string>
  <key>StandardErrorPath</key>
  <string>/Users/chihhaolai/Library/Logs/AlphaForgeAgent/night-launchd.err</string>
  <key>TimeoutInterval</key>
  <integer>7200</integer>
</dict>
</plist>
```

- [ ] **Step 6: 建立 install helper**

Create `scripts/agent_install_launchd.sh`:
```bash
#!/bin/bash
# 安裝 / 卸載 AlphaForge agent launchd plists
set -euo pipefail

CMD="${1:-install}"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"
SRC="/Users/chihhaolai/Documents/GitHub/AlphaForge/launchd"
PLISTS=("com.alphaforge.agent.evening.plist" "com.alphaforge.agent.night.plist")

case "$CMD" in
  install)
    mkdir -p "$LAUNCH_AGENTS"
    for p in "${PLISTS[@]}"; do
      cp "$SRC/$p" "$LAUNCH_AGENTS/$p"
      launchctl unload "$LAUNCH_AGENTS/$p" 2>/dev/null || true
      launchctl load "$LAUNCH_AGENTS/$p"
      echo "installed $p"
    done
    ;;
  uninstall)
    for p in "${PLISTS[@]}"; do
      launchctl unload "$LAUNCH_AGENTS/$p" 2>/dev/null || true
      rm -f "$LAUNCH_AGENTS/$p"
      echo "removed $p"
    done
    ;;
  status)
    launchctl list | grep alphaforge.agent || echo "no alphaforge.agent job loaded"
    ;;
  *)
    echo "usage: $0 {install|uninstall|status}"; exit 1 ;;
esac
```

```bash
chmod +x scripts/agent_install_launchd.sh
```

- [ ] **Step 7: 手動 smoke-test wrapper dry-run**

```bash
cd /Users/chihhaolai/Documents/GitHub/AlphaForge
AGENT_DRY_RUN=1 bash scripts/agent_run_evening.sh
ls -lt ~/Library/Logs/AlphaForgeAgent/ | head -5
tail -30 ~/Library/Logs/AlphaForgeAgent/evening-*.log
```
Expected: 看到 `=== evening tick start ... ===` 後接 prompt 內容, 再 `=== evening tick end ===`。無錯誤。

- [ ] **Step 8: Commit all launchd files**

```bash
git add scripts/agent_run_evening.sh scripts/agent_run_night.sh \
        scripts/agent_install_launchd.sh \
        launchd/com.alphaforge.agent.evening.plist \
        launchd/com.alphaforge.agent.night.plist
git commit -m "agent(infra): launchd plists + wrapper shells + install helper

- 18:30 evening (60min timeout)
- 03:00 night (120min timeout)
- phase1 only prints prompt, not yet invoking claude -p
- install/uninstall/status via scripts/agent_install_launchd.sh

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Phase 5: Day 0 Dry-run 驗證

### Task 5.1: 整合驗證 + 文件化 install 步驟

**Files:**
- Create: `docs/agent/INSTALL.md`

- [ ] **Step 1: 跑 full test suite**

```bash
cd /Users/chihhaolai/Documents/GitHub/AlphaForge
./backend/.venv/bin/python -m pytest backend/tests/test_agent_*.py -v
```
Expected: 全綠, 15+ tests passed。

- [ ] **Step 2: Dry-run 兩個 tick**

```bash
./backend/.venv/bin/python -m backend.scripts.agent_run --tick=evening > /tmp/evening.md
./backend/.venv/bin/python -m backend.scripts.agent_run --tick=night > /tmp/night.md
wc -l /tmp/evening.md /tmp/night.md
grep "site_restore" /tmp/evening.md
grep "Alpha ledger" /tmp/night.md || true  # night prompt 內本身沒 alpha ledger, 該段在 report skeleton
```
Expected: evening.md 約 50-80 行, night.md 約 80-120 行, `site_restore 結果` 存在。

- [ ] **Step 3: 實測 launchd 觸發 (選擇性)**

```bash
bash scripts/agent_install_launchd.sh install
bash scripts/agent_install_launchd.sh status
# 手動觸發 (不等 18:30):
launchctl start com.alphaforge.agent.evening
sleep 3
tail -40 ~/Library/Logs/AlphaForgeAgent/evening-*.log
```
Expected: log 有 `=== evening tick start ===` + prompt 內容 + end。

完成後暫時卸載, 等 Phase 2 (notify-hub 整合) 才真正上線:
```bash
bash scripts/agent_install_launchd.sh uninstall
```

- [ ] **Step 4: 寫 INSTALL.md**

Create `docs/agent/INSTALL.md`:
```markdown
###### tags: `AlphaForge`,`agent`,`安裝`

# AlphaForge Auto Agent — Install Guide

`文件版本: 2026-04-19a`

## 前置

- macOS
- `backend/.venv` 已建立 + requirements.txt 安裝完
- 倉庫路徑為 `/Users/chihhaolai/Documents/GitHub/AlphaForge`

## 安裝 launchd

```bash
cd /Users/chihhaolai/Documents/GitHub/AlphaForge
bash scripts/agent_install_launchd.sh install
bash scripts/agent_install_launchd.sh status
```

## 手動觸發 (測試)

```bash
launchctl start com.alphaforge.agent.evening
launchctl start com.alphaforge.agent.night
tail -f ~/Library/Logs/AlphaForgeAgent/evening-*.log
```

## 卸載

```bash
bash scripts/agent_install_launchd.sh uninstall
```

## Phase 1 範圍限制

目前 wrapper **只印 prompt, 不真的呼叫 `claude -p`**。要啟用完整 agent 需等:

1. notify-hub spec + 實作完成 (外部依賴)
2. Wrapper script 改 `AGENT_DRY_RUN=1` 為實際 `claude -p "$PROMPT"` pipe

兩者完成前, 建議:
- 保留 launchd 安裝但**不要真的啟用時段自動跑** (uninstall 後等 phase 2)
- 僅用 `launchctl start` 手動觸發驗證 log / prompt 格式

## 日誌位置

```
~/Library/Logs/AlphaForgeAgent/
├── evening-YYYY-MM-DD_HHMM.log   # wrapper 輸出
├── night-YYYY-MM-DD_HHMM.log
├── evening-launchd.out            # launchd 自身 stdout
└── evening-launchd.err            # launchd 自身 stderr
```
```

- [ ] **Step 5: Commit**

```bash
git add docs/agent/INSTALL.md
git commit -m "agent(infra): install guide (phase 1)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## 自我驗收清單 (Plan 完成定義)

- [ ] Phase 0: 目錄樹已 commit
- [ ] Phase 1: 6 個 Python helper + 對應 tests 全部通過
- [ ] Phase 2: `agent_run.py` CLI 可用
- [ ] Phase 3: 兩份 tick prompt 已存在且由 `agent_run --tick=...` 成功載入
- [ ] Phase 4: launchd plist 與 wrapper 可用 `scripts/agent_install_launchd.sh` 安裝 / 卸載
- [ ] Phase 5: `pytest backend/tests/test_agent_*.py` 全綠, dry-run prompt 正常產出, INSTALL.md 可依步驟走完

本 plan 完成後仍**不啟用 production 自動跑**, 因為:
- notify-hub 尚未實作 → approval 管道缺
- wrapper 為 phase 1 `prompt-only mode`, 未 pipe 到 `claude -p`

兩項前置解鎖後, 改 `agent_run_evening.sh` / `agent_run_night.sh` 把 `echo "[phase1]..."` 換成 `echo "$PROMPT" | claude -p --permission-mode <mode>` 即可真正上線。該變更是另一個 plan 的事。

---

## Related Specs / Plans

- **Spec**: `docs/superpowers/specs/2026-04-19-alphaforge-auto-agent-design.md`
- **Block by** (待寫): `docs/superpowers/specs/YYYY-MM-DD-notify-hub-design.md`
- **Next plan** (待寫): AlphaForge agent phase 2 — notify-hub 整合 + `claude -p` pipe 啟用

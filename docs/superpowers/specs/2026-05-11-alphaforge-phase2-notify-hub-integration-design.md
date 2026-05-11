###### tags: `專案`,`AlphaForge`,`自動化`,`規格`,`Phase 2`

# AlphaForge Phase 2 — notify-hub 整合 設計規格

`文件版本: 2026-05-11a`

## 0. 目標 (唯一)

Phase 1 (`docs/superpowers/specs/2026-04-19-alphaforge-auto-agent-design.md`, 4/19 設計) 已交付 6 個 agent helpers + 兩 tick prompts + launchd wrappers, 但 Stage 6 approval 路徑仍是「若 notify-hub 已上線」placeholder, 沒有實作。

Phase 2 把這個 placeholder 兌現:

- agent 在 evening / night tick 跑到 Stage 6 時, 把累積的 pending proposals (T3 action / memory-add / time-extension / frontend-proposal 等) 透過 notify-hub 主動推到 user 的 Telegram, sync long-poll 等 user 按 [全部同意] / [全部拒絕] / [逐項決定], 拿到結果繼續執行或結尾
- hub 失效時 fallback 落盤 `docs/proposals/YYYY-MM-DD-<slug>.md`, agent 用既有 Gmail MCP 寄 `[CRITICAL]` 通知, user 走 `git mv approved/` 備援

**Acceptance** (完成定義): e2e 跑通一次「agent (Mac 端跑 tick) → 真實 NAS notify-hub → Telegram → user 按按鈕 → agent 收到 status=approved + 模擬執行一個 T3 action」, 且整套 unit / integration test pass。

## 1. Scope

### 1.1 In scope

- 新增 `backend/app/agent/notify_hub_client.py` Python module:
  - `approve_and_wait()` 高層 API (prompt 主要呼叫)
  - `approve_request()` / `wait_result()` 低階 API (測試 + 將來 async 預留)
  - `_fallback_to_proposals()` 內部 helper
  - `HubDegradedError` / `ConfigError` exception
- 改 `backend/app/agent/prompts/tick_night.md` Stage 6 (placeholder → 具體 Bash 呼叫); **evening tick 是 T0 體檢型, 無 Stage 6, 不動**
- 加 `backend/.env.example`: `NOTIFY_HUB_URL` / `NOTIFY_HUB_TOKEN` (user 自填 `.env`, `.gitignore` 已擋)
- Test: unit (mock httpx) + integration (mock server) + e2e script (`backend/scripts/notify_hub_e2e.py` 手動跑 NAS)

### 1.2 Out of scope (留 Phase 3 或後續)

- **async mode**: spec §4.3 提的 mode 參數延後; 本 phase 所有 approval 走 sync (long-poll 1200s)
- **`/task` command**: Telegram → agent 任務派發; 需 agent 從 cron 模式改 daemon long-poll worker, 跟 Phase 1 launchd 排程結構衝突
- **launchd cron 啟用**: Phase 1 plist + wrapper 已寫, user 自決 `./scripts/agent_install_launchd.sh` 啟用; 不在本 phase 工作清單
- **Gmail `[CRITICAL]` backend wrapper**: agent prompt 用既有 `mcp__claude_ai_Gmail__*` tool 寄, 不寫 backend code
- **proposal approve/reject CLI**: 落盤 proposals 的人工處理用 `git mv` 即可, 不寫專用 CLI

## 2. 高階架構

```
┌─────────────────────────────────────────────┐
│ AlphaForge Agent (claude -p, 跑 tick)        │
│                                              │
│  Stage 6: 累積 pending proposals             │
│      │                                       │
│      │ Bash tool 跑:                         │
│      │  python -c "from app.agent           │
│      │   .notify_hub_client import          │
│      │   approve_and_wait; ..."             │
│      ▼                                       │
│  ┌─────────────────────────────────┐        │
│  │ notify_hub_client (新增)         │        │
│  │  - approve_and_wait() [高層]     │        │
│  │  - approve_request() / wait_result()  │
│  │  - _fallback_to_proposals()      │        │
│  └─────────┬───────────────────────┘        │
│            │                                 │
└────────────┼─────────────────────────────────┘
             │ HTTPS + Bearer auth
             ▼
   notify-hub @ NAS (v0.1.0, 已上線)
             │
             ▼
        Telegram bot
             │
             ▼ user 按按鈕 → webhook → DB 更新
   wait_result long-poll 收到 result
             │
             ▼
   agent dispatch by status: approved / rejected / timeout / degraded
```

**核心一句**: agent 在 Stage 6 把 pending proposals 透過 `notify_hub_client` 推到 NAS notify-hub 等 user 按, hub 失效則退回 proposals/ 落盤 + Gmail `[CRITICAL]`。

## 3. Component spec

### 3.1 `notify_hub_client.py` API

```python
# Public API
def approve_and_wait(
    project: str,
    title: str,
    items: list[dict],
    timeout_seconds: int = 1200,
    idempotency_key: str | None = None,
    metadata: dict | None = None,
) -> dict:
    """Sync: POST + long-poll wait, hub 失效自動 fallback。
    Return:
      {"status": "approved" | "rejected", "decided_at": "...", "per_item": [...]}
      {"status": "timeout", "request_id": "..."}
      {"status": "degraded", "proposal_path": "docs/proposals/..."}
    """

def approve_request(
    project: str, title: str, items: list[dict],
    timeout_seconds: int = 1200,
    idempotency_key: str | None = None, metadata: dict | None = None,
) -> str:
    """POST only, return request_id。Hub fail raise HubDegradedError。"""

def wait_result(
    request_id: str,
    overall_timeout_seconds: int = 1200,
) -> dict:
    """Long-poll loop, 內部多次 GET /<id>/wait?timeout=55 直到 status != pending or
    cumulative time >= overall_timeout。Hub fail raise HubDegradedError。
    Timeout (overall) return {"status": "timeout", "request_id": ...}。"""

class HubDegradedError(Exception):
    """notify-hub call failed (network / HTTP / auth)。"""

class ConfigError(Exception):
    """環境變數 missing / invalid。"""

# Internal
def _fallback_to_proposals(items, title, date, request_id=None) -> Path: ...
```

`approve_and_wait()` 是 prompt 主要 entry, 自動處理 hub 失效 fallback。低階兩函式給 unit test 與將來 async 用。

### 3.2 Items 格式 (對齊 notify-hub `ApprovalItemIn`)

```python
[
  {"id": "1", "type": "t3-action", "summary": "改 quality_filter MA60→MA30", "detail": "因 03-27 ckpt wr=72.5% 被擋..."},
  {"id": "2", "type": "memory-add", "summary": "...", "detail": "..."},
]
```

- `id`: str (notify-hub schema 強制), 通常 `"1"`, `"2"`, `"3"`
- `type`: str, 任意, 人類閱讀用 (`t3-action` / `memory-add` / `time-extension` / `frontend-proposal`)
- `summary`: str, 短描述, 出現在 Telegram inline list
- `detail`: str | None, 長文, 可選

### 3.3 Fallback proposal file format (`docs/proposals/YYYY-MM-DD-<slug>.md`)

```markdown
---
status: pending
created_at: 2026-05-11 03:14
slug: <slug>
reason: notify-hub unreachable; agent fallback (HubDegradedError)
request_id: null   # 若 POST 已成功只是 wait fail, 帶 request_id 供日後對照
---

# <title>

## Item 1: <type> — <summary>

<detail>

## Item 2: ...

---
備援: 看完用 `git mv docs/proposals/<this>.md docs/proposals/approved/` 表態。
```

- Slug 規則: `<title slugified to [a-z0-9-]>` 限 50 chars; 若同日 collision 加 `-<hash[:4]>`
- frontmatter `request_id`: POST 成功但 wait 失敗時帶值, 純 POST 就失敗時為 null

### 3.4 環境變數

| 變數 | 必填 | 範例 |
|---|---|---|
| `NOTIFY_HUB_URL` | ✅ | `https://notify.example.com/notify-hub` |
| `NOTIFY_HUB_TOKEN` | ✅ | `af_xxxx` (對應 notify-hub `alphaforge` consumer) |

Missing 任一 → `ConfigError`, agent 立刻停 + Gmail `[CRITICAL]`。

`backend/.env.example` 加上 (空值, user 自填 `.env`; `.gitignore` 已擋)。

### 3.5 HTTP client

- 用 httpx (Phase 1 smoke_test 已用; backend/requirements.txt 已含; 不新增依賴)
- 每次 call 新 client (沒 long-lived session, agent 跑 ad-hoc)
- POST `/v1/approvals`: 30s timeout 包整個 HTTP
- GET `/v1/approvals/<id>/wait?timeout=55`: 60s timeout per call (55s server wait + 5s margin), 多次 call 累計到 `overall_timeout_seconds` (預設 1200s, 約 22 round)
- Headers: `Authorization: Bearer ${NOTIFY_HUB_TOKEN}`, `Idempotency-Key: <if provided>`, `Content-Type: application/json`

## 4. Data flow

### 4.1 Happy path (sync approval)

```
agent Stage 6
  → approve_and_wait(project='alphaforge', title='...', items=[...])
    → approve_request: POST /v1/approvals → 201 + request_id
    → wait_result: loop GET /<id>/wait?timeout=55 直到 status != pending
  → notify-hub 推 Telegram → user 按 [全部同意]
  → webhook 更新 DB → wait 收到 status='approved' + per_item
  → helper return {"status": "approved", "decided_at": ..., "per_item": [...]}
→ agent dispatch:
    approved → 執行各 item (T3 commit / memory-add 寫檔 / ...)
    rejected → skip + 日報註記含 reject_reason (per_item.reject_reason)
```

### 4.2 Degraded path (hub failure)

```
agent → approve_and_wait(...)
  → approve_request: POST throw (httpx.ConnectError | 5xx | 401 | timeout)
  → except → _fallback_to_proposals(items, title, date)
    → 寫 docs/proposals/2026-05-11-<slug>.md (frontmatter status=pending)
  → helper return {"status": "degraded", "proposal_path": "docs/proposals/..."}
→ agent 收 status='degraded':
    1. 用 mcp__claude_ai_Gmail__send tool 寄 [AlphaForge][CRITICAL] notify-hub 失效, X 項落盤
       (subject: [AlphaForge][CRITICAL] YYYY-MM-DD <tick_type> tick - notify-hub 失效)
    2. 日報註記 `## Hub 失效 fallback` 段
    3. 本 tick T3 全 skip (T2 in-backlog 仍可做)
```

### 4.3 Timeout path (user 沒按)

```
wait loop 跑滿 overall_timeout (1200s) 仍 status='pending'
  → helper return {"status": "timeout", "request_id": "..."}
→ agent:
    1. 日報註記 `## Approval timeout — request_id=... — 隔天人工處理`
    2. 本 tick T3 跳過
```

跟 'rejected' 的差別: timeout 留 request_id 在日報, user 可隔天用 Telegram 補按或查 notify-hub `/v1/approvals/<id>`; rejected 是明確拒絕。

## 5. Error handling

### 5.1 Exception 類

```python
class HubDegradedError(Exception):
    """notify-hub call failed (network / HTTP / auth).
    一律觸發 fallback, 不 retry (Phase 1 cron 隔天再試)。"""

class ConfigError(Exception):
    """環境變數 missing / invalid. Ops bug, agent 該停。"""
```

- `approve_request()` / `wait_result()` HTTP error → `HubDegradedError`
- 401 (auth fail) 視同 degraded (不區分 token 過期 vs network 不通, 因為 agent 半夜跑沒能力分辨)
- `approve_and_wait()` 內 try/except 包兩個低階呼叫 → fallback

### 5.2 Exit code 與 stdout 約定

- helper module 永遠 exit 0 (Python 沒 catch 才會 exit non-zero); 業務狀態都在 return dict
- agent prompt 用 `python -c '... print(json.dumps(approve_and_wait(...)))'` 取 stdout 解析
- 唯一 exit 非零情況: `ConfigError` (uncaught raise → exit 1), agent 該察覺停 tick

### 5.3 Idempotency

- `approve_and_wait(idempotency_key=...)` 把值帶到 `Idempotency-Key` header
- 推薦規則 (prompt 內示範): `idempotency_key = f"{tick_date}-{tick_type}-{title_hash[:8]}"`
  - 例: `2026-05-11-night-a1b2c3d4`
  - `title_hash` 用 `hashlib.sha256(title.encode()).hexdigest()`
- 同 key 重送, notify-hub 回原 approval 而非新建 — 跨 tick retry 安全 (agent crash 半路, 下 tick 重跑 Stage 6 不會重推 Telegram)

### 5.4 Logging

- 用 Python stdlib `logging.getLogger("notify_hub_client")`
- INFO: POST 發送 / wait round / 收到 status
- ERROR: HubDegradedError trigger + fallback 路徑
- log 純 stdout, 不寫 `docs/state/`; launchd wrapper 端 redirect 到 `~/.alphaforge/agent-tick-<date>-<tick>.log`

## 6. Testing

### 6.1 Unit (mock httpx, 用 respx)

- `test_approve_request_201_returns_id` — POST 201 → str request_id
- `test_approve_request_connect_error_raises` — `httpx.ConnectError` → `HubDegradedError`
- `test_approve_request_401_raises` → `HubDegradedError`
- `test_wait_result_first_call_approved` — 一次就拿到 approved
- `test_wait_result_multi_round_until_approved` — 前 2 round pending, 第 3 round approved
- `test_wait_result_overall_timeout` — 持續 pending 到 overall_timeout → `status='timeout'`
- `test_approve_and_wait_happy` — POST + wait 接續
- `test_approve_and_wait_post_fail_fallback` — POST fail → fallback file written + return degraded
- `test_approve_and_wait_wait_fail_fallback` — POST OK 但 wait fail → fallback with request_id
- `test_fallback_proposal_format` — file 內 frontmatter + items 段落正確
- `test_config_missing_raises` — env var 不存在 → `ConfigError`

### 6.2 Integration (mock server)

- 起一個假 fastapi server 假裝 notify-hub: `/v1/approvals` 收 POST 後內部切 status, `/wait` round 之後回 approved
- 驗 full happy path + happy 後 idempotency 重送回原 approval
- 驗 fallback path: server 500 → fallback file + degraded return

### 6.3 E2E (手動, real NAS notify-hub)

- script: `backend/scripts/notify_hub_e2e.py`
- env: 從 `backend/.env` load
- 流程: 跟 notify-hub repo `tests/smoke/smoke_test.py` 同 pattern 但用 `app.agent.notify_hub_client` 而不是 raw httpx
  - `approve_and_wait('alphaforge', 'Phase 2 e2e test', items=[...test items...], timeout_seconds=180)`
  - 印出結果
- 預期: 你手機 Telegram 收到推, 按按鈕, script 印 `status=approved`
- pass 標準: 全程無 error, 完成 §0 Acceptance

### 6.4 覆蓋率目標

- `notify_hub_client.py` line coverage > 90%
- 整合測試 cover happy + degraded 兩主路徑
- e2e 至少手動跑一次, 結果寫 `docs/reports/2026-MM-DD-phase2-e2e.md`

## 7. Implementation Plan 預覽 (給 writing-plans skill 參考)

預估 7-9 tasks, TDD 順序:

1. `notify_hub_client.py` 骨架 + `ConfigError` + env 讀取
2. `approve_request()` POST + unit tests (mock httpx)
3. `wait_result()` long-poll loop + unit tests
4. `_fallback_to_proposals()` + unit tests (file format)
5. `approve_and_wait()` wrap + unit tests
6. integration test (mock server) full flow
7. tick prompt Stage 6 改寫 (evening + night), `.env.example` 加環境變數
8. e2e script + 手動跑 NAS notify-hub 驗收
9. 日報 phase2-e2e.md + memory update (`project_next_steps.md` → "Phase 2 上線, agent approval 整合")

每 task 自帶 TDD red-green-refactor + 一個 commit。

## 8. 影響面

### 8.1 跟 Phase 1 的關係

- Phase 1 helpers (`deploy_lock` / `path_tier` / `smoke_test` / `site_restore` / `alpha_ledger` / `report_builder`) 完全不動
- 兩 tick prompts 只動 Stage 6 段; 其他 Stage (Gate 1 必讀, Stage 2-5, Stage 7 收尾) 不動
- `agent_run.py` 不動 (它只負責印 prompt, helper 由 prompt 內 Bash tool 呼叫)
- Phase 1 launchd plist / wrapper 不動

### 8.2 跟 notify-hub 的關係

- notify-hub v0.1.0 已上線 (NAS, 5/10 webhook SSL 修好), Phase 2 完全 read-side, 不改 notify-hub code
- 用 notify-hub consumer name `alphaforge` (consumer token 已配, 寫在 NAS `.env` 的 `NOTIFY_HUB_CONSUMER_TOKENS=alphaforge:af_...`)
- consumer token 同步寫入 AlphaForge `backend/.env` 的 `NOTIFY_HUB_TOKEN` (兩端 token 字串相同)

### 8.3 跟 memory feedback 對齊

- **alpha-first**: 整合是手段, agent 推出 alpha 才是目標; helper 範圍刻意縮到最小
- **YAGNI**: sync only, 不寫 async; approval only, 不寫 /task; helper 內 fallback 自動但不 retry (cron 隔天再試)
- **跟 Phase 1 pattern 一致**: Python module + Bash 呼叫
- **不偽造 / 結果可驗證**: e2e 真戰 NAS, 不靠 mock 結束

---

## 附錄 A: Stage 6 prompt 改寫 sketch

(現有 `tick_night.md` line 56-61 從 placeholder 改為以下具體呼叫):

````markdown
### Stage 6: Approval (notify-hub 整合)

累積本 tick 的 pending proposals (來自 Stage 5 各題的 T3 action / memory-add / time-extension), 用以下 Bash 跑:

```bash
cd backend && ./.venv/bin/python -c "
import json, sys
sys.path.insert(0, '.')
from app.agent.notify_hub_client import approve_and_wait
result = approve_and_wait(
    project='alphaforge',
    title='2026-MM-DD night tick — N 項待批准',
    items=[
        {'id': '1', 'type': 't3-action', 'summary': '...', 'detail': '...'},
    ],
    timeout_seconds=1200,
    idempotency_key='YYYY-MM-DD-night-<title_hash[:8]>',
)
print(json.dumps(result, ensure_ascii=False))
"
```

依 stdout 的 `status` 欄位 dispatch:

- `approved` → 執行各 item (T3 commit + smoke_test / memory-add 寫檔)
- `rejected` → skip 對應 item; 日報註記 per_item 的 reject_reason
- `timeout` → 寫日報 `## Approval timeout (request_id=...)`, 留人工
- `degraded` →
  1. 用 `mcp__claude_ai_Gmail__send` tool 寄 `[AlphaForge][CRITICAL] notify-hub 失效, 落盤 <proposal_path>` 給自己
  2. 日報註記 `## Hub 失效 fallback`
  3. T3 全 skip
````

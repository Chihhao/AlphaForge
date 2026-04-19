###### tags: `專案`,`AlphaForge`,`自動化`,`規格`

# AlphaForge 自動研究 / 開發 Agent — 設計規格

`文件版本: 2026-04-19a`

## 0. 目標 (唯一)

讓 Claude Code 以**全自動 agent** 形態每日推進 AlphaForge 的 **alpha 發現與維護**。所有設計決策以「是否提升 5d / 10d / 20d 維度的 IC / wr / avg_top」為最終判準。

流程、工具、通訊管道皆為手段，不得本末倒置。

---

## 1. 高階架構

```
┌───────────────────────────────────────────────────────────┐
│ macOS launchd (使用者 Mac)                                  │
│  ├── com.alphaforge.agent.evening.plist   (每日 18:30)      │
│  └── com.alphaforge.agent.night.plist     (每日 03:00)      │
└──────────────────────┬────────────────────────────────────┘
                       │ 觸發 claude -p "<tick prompt>"
                       ▼
┌───────────────────────────────────────────────────────────┐
│ Claude Code headless session (one-shot)                     │
│  Stage 0 現場還原 → Stage 1 載入 context → Stage 2 選題     │
│  Stage 3 執行 → Stage 4 測試 → Stage 5 approval             │
│  Stage 6 commit/deploy → Stage 7 收尾                       │
└────────────┬──────────────────────────────────────────────┘
             │                           │                    │
             ▼                           ▼                    ▼
   Backend (commit + deploy)   Docs (reports / inbox /    notify-hub
                                proposals / state)         (LINE, Gmail)
```

### 兩個 tick 對照

| | 18:30 體檢 tick | 03:00 主力 tick |
|---|---|---|
| Tier 上限 | T0 (只讀) | T2 (T3 僅能提 proposal) |
| 可 commit 區 | `docs/` only | 全 repo (除 T3 硬擋區) |
| 可 deploy | ❌ | ✅ backend |
| 時長上限 | 60 min | 120 min (超時需 approve) |
| 典型產出 | 體檢報告 + alert inbox | alpha 推進 + commit + deploy |

### 時機選擇理由

- 避開使用者工作時段 08:30–17:30
- 避開 Claude token 加倍時段 21:00–03:00 (03:00 剛過邊緣, 留 5.5 小時緩衝到 08:30)
- 18:30 位於 18:10 訊號儲存之後、21:00 融券補抓之前, 不撞 scheduler

---

## 2. Tick Lifecycle

### 18:30 Evening tick (體檢型, T0)

```
Stage 0: 現場還原 checklist (見 §4.1)
Stage 1: 載入 MEMORY.md + next_steps + 近 3 日 reports + git log -20
Stage 2: 產線體檢清單
  a. scheduler job logs: 15:30 / 16:30 / 17:00 / 17:20 / 17:30 / 18:10
  b. 今日 feature 表 row count + null%
  c. 今日 fundamentals 覆蓋率
  d. 17:30 模型重訓 IC / loss 合理性
  e. 昨日 picks 結案情況 (tp / sl / time_limit)
  f. 近 7 日 picks 勝率退化檢查
  g. GET /picks/today 健康檢查
Stage 3: 異常分流
  - 無 → 寫 docs/reports/YYYY-MM-DD-1830.md + Gmail [INFO]
  - 有 → 寫 docs/inbox/alert-YYYY-MM-DD-<slug>.md + [WARN]
  - a/c/g 紅燈 → [CRITICAL]
Stage 4: END 標記
```

**限制**: 不改 production, 不 commit 任何 `backend/app/` 變更, 不 deploy。

### 03:00 Night tick (主力, T0-T2)

```
Stage 0: 現場還原 checklist
Stage 1: 載入 context + 特別讀 18:30 日報 + docs/inbox/alert-*.md
Stage 2: 優先序決策
  A) inbox/alert-*.md (18:30 自產)
  B) inbox/*.md (使用者手塞)
  C) docs/state/deploy-lock.json 殘局
  D) project_next_steps.md backlog
  E) agent 自主提案 (只寫 proposal, 不執行)
Stage 3: 候選題 3-5 個 + Gate 2 feedback checklist (§3)
Stage 4: Tier 判定 (§3)
Stage 5: 執行 (改 code / 跑 script / pytest / smoke test)
Stage 6: approval 互動 (§4.3)
Stage 7: commit 粒度 = 一題一 commit → deploy-lock → deploy → smoke
         → lock=success → 寫 report → 發 Gmail → lock=released
```

---

## 3. 七層 Gate (安全護欄)

### Gate 1 — 啟動必讀

每 tick 強制載入:
- `/Users/chihhaolai/.claude/projects/-Users-chihhaolai-Documents-GitHub-AlphaForge/memory/MEMORY.md` 全部 feedback
- `memory/project_next_steps.md`
- 近 3 天 `docs/reports/*.md`
- `git log --oneline -n 20`
- 03:00 tick 另讀 18:30 report 與 `docs/inbox/alert-*.md`

### Gate 2 — 候選題 feedback checklist

每個候選題必須在日報列出以下 checklist 結果:

| 檢核項 | 來源 memory |
|---|---|
| Alpha-first | `feedback_alpha_first.md` |
| 有 benchmark 對照 | `feedback_data_validation.md` |
| 含 long-short validation | `feedback_longshort_validation.md` |
| 先診斷根因 | `feedback_diagnose_before_model.md` |
| 不偽造數據 | `feedback_no_fake_data.md` |
| Partial IC 非充分 | `feedback_partial_ic_not_sufficient.md` |
| 100% 結果找偏差 | `feedback_100pct_impossible.md` |
| 資料正確性優先 | `feedback_data_correctness_first.md` |

任一 fail → 棄選該題, 寫入日報「棄選清單」。

### Gate 3 — Tier 分級 (依檔案路徑硬判定)

| Tier | 允許路徑 | 前置條件 |
|---|---|---|
| **T0** | 讀任何檔案 | 無 |
| **T1** | `backend/scripts/research_*.py`, `backend/scripts/diag_*.py`, `docs/**` (除 `docs/state/`) | Gate 2 全過 |
| **T2** | `backend/app/services/*`, `backend/app/api/endpoints/*`, `backend/app/models/*`, `backend/app/schemas/*`, `backend/app/core/indicators.py` 等計算模組 | Gate 2 全過 AND 題目已在 `project_next_steps.md` OR 昨日有 approved proposal |
| **T3** | 下方硬擋區, 僅能寫 proposal | 永遠需人工 approve |

**每週 refactor 上限 = 1 次**, 且必須搭配 alpha 題。

### Gate 4 — 執行期檢查

- 改 production → 必跑 `pytest tests/` 相關模組, 紅燈即 `git reset --hard <tick_start_sha>`
- 一題一 commit, commit message 格式: `agent(<tick>): <type> - <短描述>` 例 `agent(0300): research - walk-forward decay curve v1`
- Deploy 前必寫 `docs/state/deploy-lock.json`
- Deploy 後必跑 smoke test: API `/health`, `/picks/today`, `/market/system-events`
- 失敗 → 自動 rollback docker image + `[CRITICAL]` email

### Gate 5 — 可逆窗口

每份日報最前面必列「今日可逆清單」:
```
## 可逆清單
- commit def456: agent(0300): feat - add walkforward decay log
  rollback: git revert def456
- deploy 2026-04-20T03:45 backend:def456
  rollback: docker tag alphaforge-backend:20260419 alphaforge-backend:latest && ./deploy.sh 3
```

### Gate 6 — 硬上限 + 預算自覺

- launchd `TimeoutInterval = 7200` sec (120 min), SIGKILL
- Agent prompt 硬規則:
  - Token 剩 < 20% → 進入收尾模式, 不開新 T2
  - Token 剩 < 10% → 立即 abort, 最後動作必為 `git commit` + 簡短 Gmail
- 連續 3 tick 落在同一 T2 題 → 下一 tick 強制降 T0 冷卻

### Gate 7 — 禁忌清單 (硬擋, 無例外)

T3 硬擋區, agent 絕不可自動改, 只能寫 proposal:

| 路徑 | 原因 |
|---|---|
| `frontend/**` | 前端只出 HTML mockup (`docs/proposals/frontend/mockups/*.html`, 用 ui-ux-pro-max skill) |
| `backend/app/core/scheduler.py` | 動了產線節奏崩 |
| `backend/alembic/versions/*` | 不可逆 schema |
| `backend/app/core/database.py` | 連錯 DB 全爆 |
| `docker-compose*.yml`, `Dockerfile*` | 部署架構 |
| `deploy.sh`, `start_dev.sh` | 部署腳本 |
| `backend/requirements.txt` | 依賴更新 (影響其他 service) |
| `.claude/**`, `CLAUDE.md` | harness 與專案指引 |
| `~/.claude/memory/MEMORY.md` 索引 | Memory 索引 |
| `~/.claude/memory/feedback_*.md` | 行為規則 |
| `~/.claude/CLAUDE.md` | 全域指引 |

Memory 變更 (新增 / 編輯 / 刪除任何 memory 檔) → 申請制 (§4.3)。
時長 > 120 min → 申請制。

**硬擋語意釐清**: 「硬擋」= 未 approve 前 agent 不可自動改。一旦對應 proposal 被 approve, 視為授權 agent 於當前或下一 tick 執行 proposal 明列的動作 (範圍不得擴張)。`deploy.sh` / `docker-compose*.yml` / `.claude/**` / `CLAUDE.md` / `frontend/**` 例外, 即使 approve 後 agent 仍不可自動改, 需使用者手動操作 (僅允許 agent 產出修改建議)。

---

## 4. 支撐機制

### 4.1 現場還原 checklist (每 tick Stage 0)

```
[ ] git status 乾淨?
    否 → git stash → docs/reports/interrupted/YYYY-MM-DD-<sha>.md → [CRITICAL]
[ ] 最新 commit 有對應 deploy 紀錄?
    否 → 查 docs/state/deploy-lock.json
        status=in_progress 且 > 30 min → smoke test
          紅燈 → rollback previous_backend_image
          綠燈 → lock=success
[ ] 最近一份 report 有 END 標記?
    否 → [CRITICAL] "上次 tick 被砍"
[ ] MEMORY.md 索引對比 git blame 未被 agent 動?
    有動 → [CRITICAL]
```

### 4.2 Token / session 中斷處理

四階段 + checkpoint:

```
Stage 1 (5-10%): 讀 memory / reports / 選題
Stage 2-3 (70%): 執行 + 測試
Stage 4 (20%): commit + deploy + 日報 + email
```

**中斷 policy = P1 保守**:
- Stage 2 中 token 驟降 < 10% → 立即 `git stash` 所有未 commit + `[CRITICAL]` 下 tick 由使用者決定 restore / discard
- Deploy-lock 在 `in_progress` 狀態 > 30 min 無更新 → 下 tick 自動 smoke + rollback

### 4.3 Approval 透過 notify-hub (依賴外部 spec)

**AlphaForge spec 只定義 interface, 實作見 notify-hub spec (待寫)**:

```python
# Agent tick Stage 5
request_id = notify_hub.approve_request(
    project="alphaforge",
    title="2026-04-20 0300 tick 3 項待批准",
    items=[
      {"id": 1, "type": "t3-action", "summary": "...", "detail": "..."},
      {"id": 2, "type": "memory-add", "summary": "...", "detail": "..."},
      {"id": 3, "type": "time-extension", "summary": "120→180 min", "detail": "..."},
    ],
    timeout_seconds=1200,
    mode="sync" | "async",
)
result = notify_hub.wait_result(request_id)      # sync
# or
result = notify_hub.get_result(request_id)       # async, 下 tick 讀
```

**預設 mode 策略**:
- T3 action (本 tick 需落地) → sync
- Memory-add, frontend proposal, time-extension (非急) → async

**Token (`NOTIFY_HUB_TOKEN`)** 存於 `backend/.env`, 不進 git。

### 4.4 Hub 失效 degradation

```
hub call 失敗 →
  1. 所有 pending proposals 落盤 docs/proposals/<slug>.md (pending)
  2. Gmail [CRITICAL] 通知
  3. 使用者走 git mv approved/ 備援流程
  4. 本 tick 所有需 approve 事項跳過 (T2 in-backlog 仍可做)
```

### 4.5 Inbox (使用者塞題)

`docs/inbox/` 檔案式:

```markdown
---
type: user-task
priority: p0 | p1 | p2
tier_guess: T1 | T2 | T3
---
# <主旨>
## 背景
## 期望結果
## 線索
```

Agent 處理後搬 `docs/inbox/processed/`, 在日報註記入口。

未來 notify-hub 可選擇實作「LINE 訊息 → inbox 檔」(hub spec 的 feature), 不影響本 spec。

### 4.6 Gmail 分級 (注意區分與 notify-hub 的職責)

Gmail MCP 處理**單向通知**, 無需回覆:

| 主旨 | 觸發 |
|---|---|
| `[AlphaForge] YYYY-MM-DD tick 完成` | 正常 |
| `[AlphaForge][INFO] Approval timeout, pending` | sync 等超時 |
| `[AlphaForge][WARN] Token 近 20% 進收尾模式` | - |
| `[AlphaForge][CRITICAL] Deploy 半成, 已 rollback` | - |
| `[AlphaForge][CRITICAL] 工作區髒, 已 stash` | - |
| `[AlphaForge][CRITICAL] 上次 tick 被砍` | - |
| `[AlphaForge][CRITICAL] notify-hub 失效` | - |

Approval 請求**不走 Gmail 雙向**, 統一走 notify-hub LINE 管道。

---

## 5. 目錄結構

```
AlphaForge/
├── docs/
│   ├── reports/                    # 日報
│   │   └── interrupted/            # 中斷殘局報告
│   ├── proposals/                  # 待 approve
│   │   ├── approved/
│   │   ├── rejected/
│   │   ├── executed/
│   │   ├── stale/                  # > 30 天自動搬
│   │   └── mockups/                # 前端 HTML mockup
│   ├── inbox/
│   │   └── processed/
│   └── state/
│       └── deploy-lock.json
├── backend/
│   ├── scripts/
│   │   ├── research_*.py           # T1 自由新增
│   │   └── diag_*.py               # T1 自由新增
│   └── app/                        # T2 條件式修改 (見 Gate 3)
└── ~/.claude/memory/               # 唯讀, 寫入走 memory proposal
```

**Commit message 格式**:
```
agent(<tick>): <type> - <短描述>

<body: checklist 引用, alpha ledger 摘要, linked report>
```

`<type>` ∈ `research | feat | fix | diag | refactor | report | proposal`

---

## 6. Alpha-first 硬規則

### 選題規則

每題必須回答: **「能否提升 5d / 10d / 20d 的 IC / wr / avg_top?」**
- 能 → 優先處理, 可走 T2
- 不能 (如純 refactor / UI 優化 / code cleanup) → T1 only, 每週 ≤ 1 次

### 日報 alpha ledger (強制結尾段)

```markdown
## Alpha ledger
- 本 tick IC / wr / avg_top 變化: <數字 or "未測">
- 新發現: <一句>
- 否證: <一句>
- 下一步候選: <一行>
```

### 候選題優先序 (03:00 tick Stage 2)

1. 產線資料健康 (沒資料 = 沒 alpha)
2. 既有 alpha 退化監測 (walk-forward decay, rolling IC, regime)
3. backlog alpha-bearing 題 (P2-P3)
4. 自主新因子研究 (只落 T1, 研究驗證後提 proposal 才進 production)
5. Refactor (≤ 1 次 / 週, 搭 alpha 題)

---

## 7. Known limitations / Open items

| # | 項目 | 影響 | 行動 |
|---|---|---|---|
| 1 | Mac 必須 18:30 / 03:00 開機連網 | 漏 tick = 少一天 | 接受 (9a = B 漏就漏) |
| 2 | notify-hub 未實作 | Approval 管道缺 | **本 spec 上線前置 block**, 下次 brainstorm notify-hub spec |
| 3 | `claude -p` headless 模式下 notify-hub client 行為 | 需實測 | Day 0 驗證 |
| 4 | Gmail MCP OAuth scope 設定 | 通知管道 | Day 0 驗證 |
| 5 | Token 預算上限實際值 | 預算規劃 | 2 週實測後校準 |
| 6 | Deploy 自動 rollback 仰賴 docker image tag 慣例 | rollback 成敗 | `./deploy.sh` 配合微調 |
| 7 | 前端改動一律 T3 (HTML mockup) | UI 改動速度慢 | 設計取捨, 接受 |

---

## 8. Day 0 / 實測計畫

### Day 0 (上線前)
- [ ] notify-hub 已 deploy 可用 (ping / approve_request / wait_result 連通)
- [ ] `claude -p "echo hello"` + Gmail MCP send 成功
- [ ] launchd plist 跑 dummy prompt → 寫入 `docs/reports/test-*.md` + Gmail 送達
- [ ] `./deploy.sh 3` 手動跑一遍驗證 rollback 流程

### Week 1 (Full mode 直接上)
- 連續 7 天觀察日報
- 若 3 天內 >= 2 次 `[CRITICAL]` → 降回 T1 冷卻一週, debug 原因
- Token 預算實測、記錄每 tick 實耗

### Week 2+
- 依 Week 1 資料調整 Gate 6 token 閾值
- Backlog 若消化完, agent 進入「自主因子研究」模式 (T1 only)

---

## 9. 成功判準

本 agent 上線成功的判準是:

1. **每週至少推進 1 個 backlog 項目**或**發現 1 個新 alpha 候選**
2. **零 production 中斷** (deploy 失敗必 rollback, 不外洩到 UI)
3. **日報讓使用者一早打開 email 就能決策下一步**, 不用自己挖 code / log
4. **Memory 隨時間累積新 feedback** (透過 approval 申請制)

若 3 個月後這四項任一常態性失敗, agent 設計需重新檢討。

---

## 10. 依賴與後續 spec

- **notify-hub spec** (待寫, 下次 brainstorm): LINE Messaging API 整合 + 通用 HTTP interface + multi-consumer token
- **AlphaForge agent plan** (本 spec approve 後寫): launchd plist, tick prompt 模板, 日報模板, Gate 實作細節

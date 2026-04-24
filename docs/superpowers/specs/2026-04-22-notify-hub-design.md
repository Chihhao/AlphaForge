###### tags: `專案`,`notify-hub`,`規格`,`AlphaForge`

# notify-hub — 設計規格

`文件版本: 2026-04-24a`

> **v2 修訂 (2026-04-24):**
> - §3.3 `approvals.expires_at` 改 nullable; 靜音時段建立的 approval 先不設, flush 推出後才啟動倒數 (避免 quiet hours × timeout 撞車)
> - §4.7 `/healthz` telegram 狀態值擴充為 `ok / degraded / unknown / skipped`; 由 runtime push 行為與每小時 probe 更新, 不再只依賴 startup 那一瞬間
> - §7.2 明確列為必做項 (push retry 每小時掃 push_failed), 不是 optional
> - §7.4 timeout sweeper 明確排除 `expires_at IS NULL` 的 approval

## 0. 目的

提供一個 **self-hosted、多 consumer 共用**的通知與 approval 管道，讓任何 headless 自動化腳本 (例如 AlphaForge agent) 能透過 HTTP 與人類使用者在 Telegram 上互動，包含:

- 單向通知 (push)
- 雙向 approval 請求 (含 inline keyboard 按鈕 + 可選文字理由)
- 使用者主動下任務 (`/task` 指令) 觸發 agent

notify-hub 本身是**獨立開源專案** (`~/Documents/GitHub/notify-hub`)，AlphaForge 僅是第一個 consumer。設計以「其他人 fork 後可自行部署到自己的 NAS / VPS，配自己的 Telegram bot」為前提。

## 1. 範圍定義

### 1.1 In scope

- HTTP API 供 consumer 建立 / 查詢 approval 與 job
- Telegram Bot API 整合 (webhook + sendMessage + inline keyboard + 編輯原訊息)
- PostgreSQL 儲存 (approval 生命週期、decisions、agent jobs)
- 使用者白名單、consumer token 認證
- 靜音時段 (quiet hours)，期間壓住通知不 push
- `/task` 命令收件轉成 agent job
- 健康檢查 + 基本可觀測性

### 1.2 Out of scope (明確不在本 spec)

- AlphaForge agent daemon 本身的實作 (屬於 Phase 2 plan)
- `claude -p` pipe / launchd 替換 (屬於 AlphaForge 工作)
- Non-Telegram channel (LINE / Slack / Discord) — 可未來擴展但不在 v1
- 多使用者協作 / 權限角色 (每個部署實例是單一 owner 模型)
- Billing / 多租戶 SaaS

## 2. 高階架構

```
┌──────────────┐          (1)POST           ┌─────────────────┐
│  AlphaForge  │───── approval / job ──────▶│                 │
│    agent     │                            │   notify-hub    │
│  (Mac 常駐)  │       (4)GET wait          │  (NAS, 常駐)    │
│              │◀── 30s long-poll ─────────▶│                 │
│              │                            │   ┌──────────┐  │
└──────────────┘                            │   │ Postgres │  │
                                            │   └──────────┘  │
                                            └────┬────────────┘
                                                 │
                                       (2)sendMessage
                                                 ▼
                                         ┌─────────────┐
                                         │ Telegram API│
                                         └──────┬──────┘
                                                │
                                         (3)callback / message
                                                │
                                                ▼
                                           📱 使用者手機
```

### 2.1 四條資料流

| # | 方向 | 說明 |
|---|---|---|
| 1 | agent → hub | POST `/v1/approvals` 或 `/v1/jobs` |
| 2 | hub → Telegram → 手機 | sendMessage + inline keyboard |
| 3 | 手機 → Telegram → hub | webhook (callback_query / message) |
| 4 | agent ↔ hub | GET `/v1/approvals/<id>/wait` 或 `/v1/jobs/next`，30 秒 long-polling |

### 2.2 Hub 內部職責

1. 提供 HTTP API 給 consumer
2. 跟 Telegram 對話 (sendMessage / webhook / editMessage)
3. 儲存 approval / job / decision 生命週期狀態
4. 執行靜音時段排程 (quiet hours scheduler)
5. Consumer token / webhook secret / chat_id 白名單三層 auth

## 3. 資料模型

採用 NAS 上 PostgreSQL 獨立 database (`notify_hub`)。共 6 張表 + 1 張可選 audit log。

### 3.1 `consumers`

| 欄位 | 型別 | 說明 |
|---|---|---|
| `id` | serial PK | |
| `name` | varchar unique | 例: `alphaforge`、`rebirth-road` |
| `token_hash` | varchar | SHA-256 (consumer API token) |
| `description` | text nullable | |
| `created_at` | timestamptz | |
| `disabled_at` | timestamptz nullable | 停用時記錄時間 |

### 3.2 `subscribers`

| 欄位 | 型別 | 說明 |
|---|---|---|
| `id` | serial PK | |
| `chat_id` | bigint unique | Telegram chat_id，白名單用 |
| `display_name` | varchar | 便於管理，例 `Eric Lai` |
| `created_at` | timestamptz | |

v1 預期僅 1 筆 (部署者本人)。多 subscriber 時的廣播策略留到未來。

### 3.3 `approvals`

| 欄位 | 型別 | 說明 |
|---|---|---|
| `id` | uuid PK | `request_id`，對外可見 |
| `consumer_id` | int FK | |
| `project` | varchar | consumer 自填的專案名 (含於訊息 prefix) |
| `title` | varchar | 訊息標題 |
| `status` | enum | `pending / approved / rejected / mixed / timeout` |
| `idempotency_key` | varchar nullable | consumer 帶入，去重用 |
| `timeout_seconds` | int | 預設 1200 |
| `created_at` | timestamptz | |
| `expires_at` | timestamptz nullable | 白天 = `created_at + timeout_seconds`; 靜音時段建立時 = `NULL`, 等 `quiet_hours_flush` 推出後才設為 `pushed_at + timeout_seconds` |
| `decided_at` | timestamptz nullable | 最後一項被批完時間 |
| `telegram_chat_id` | bigint nullable | 推播的 chat_id |
| `telegram_message_id` | bigint nullable | 原訊息 id，編輯用 |
| `push_state` | enum | `scheduled / pushed / push_failed / suppressed_quiet_hours` |
| `last_push_error` | text nullable | |
| `metadata` | jsonb | consumer 可塞任何追溯資料 |

**索引**: `(consumer_id, status)`, `(status, expires_at)`, `(consumer_id, idempotency_key)` unique partial where idempotency_key is not null。

### 3.4 `approval_items`

| 欄位 | 型別 | 說明 |
|---|---|---|
| `id` | serial PK | |
| `approval_id` | uuid FK | |
| `item_id` | varchar | consumer 指定的 id (常為 `1`/`2`/`3` 或 slug) |
| `type` | varchar | consumer 自訂 (`t3-action`、`memory-add` 等)，僅供人類閱讀 |
| `summary` | varchar | 訊息中顯示的一行摘要 |
| `detail` | text nullable | 長描述，逐項批面板展開用 |
| `position` | int | 排序用 |

### 3.5 `decisions`

| 欄位 | 型別 | 說明 |
|---|---|---|
| `id` | serial PK | |
| `approval_id` | uuid FK | |
| `item_id` | varchar nullable | null 代表 "all" (全同意 / 全拒絕)，否則對應具體 item |
| `decision` | enum | `approved / rejected / timeout` |
| `decided_by_chat_id` | bigint | |
| `reject_reason` | text nullable | |
| `decided_at` | timestamptz | |

`approvals.status` 是 `decisions` 彙總的衍生欄位，由 hub 在寫入 decision 時同步更新。

### 3.6 `agent_jobs`

| 欄位 | 型別 | 說明 |
|---|---|---|
| `id` | uuid PK | |
| `consumer_id` | int FK | 對應 `/v1/jobs/next?agent=xxx` 的 agent 名 |
| `source` | enum | `telegram_task / consumer_api` |
| `prompt` | text | 給 agent 的任務描述 |
| `status` | enum | `pending / claimed / completed / failed / expired` |
| `claimed_by` | varchar nullable | daemon 的 instance id (方便 debug) |
| `claimed_at` | timestamptz nullable | |
| `completed_at` | timestamptz nullable | |
| `result_summary` | text nullable | daemon 回報的結果摘要 |
| `result_path` | varchar nullable | 例如 `docs/reports/task-042-...md` |
| `notify_chat_id` | bigint nullable | 完成後要 push 給誰 |
| `created_at` | timestamptz | |
| `expires_at` | timestamptz | 預設 `created_at + 7 days`，過期自動標 `expired` |

### 3.7 Retention / 清理

- `approvals` + `approval_items` + `decisions`: 完成 7 天後狀態改 `archived`，**不刪**，保留歷史供 audit
- `agent_jobs`: 完成 30 天後刪除 (除 `failed` 狀態保留 90 天)
- 每日 04:00 (避開 03:00 AlphaForge night tick) 跑一次清理 cron

## 4. HTTP API 規格

所有 API 前綴 `/v1/`，JSON in/out。Auth 統一透過 `Authorization: Bearer <consumer_token>` header。

### 4.1 `POST /v1/approvals`

建立 approval 請求。

```http
POST /v1/approvals HTTP/1.1
Authorization: Bearer <consumer_token>
Idempotency-Key: <optional uuid>
Content-Type: application/json

{
  "project": "alphaforge",
  "title": "2026-04-22 0300 tick 3 項待批",
  "items": [
    {"id": "1", "type": "t3-action", "summary": "改 deploy.sh 加 rollback hook", "detail": "..."},
    {"id": "2", "type": "memory-add", "summary": "新增 feedback_deploy_rollback.md", "detail": "..."},
    {"id": "3", "type": "time-extension", "summary": "120→180 分鐘"}
  ],
  "timeout_seconds": 1200,
  "metadata": {"tick": "night", "tick_start_sha": "abc123"}
}
```

**Response 201**:

```json
{
  "request_id": "req_01hz...",
  "status": "pending",
  "created_at": "2026-04-22T03:05:12+08:00",
  "expires_at": "2026-04-22T03:25:12+08:00",
  "push_state": "scheduled"
}
```

### 4.2 `GET /v1/approvals/<id>/wait`

Long-polling 等結果。

```http
GET /v1/approvals/<id>/wait?timeout=30 HTTP/1.1
Authorization: Bearer <consumer_token>
```

- `timeout` query 單位秒，有效範圍 `[1, 55]` (上限 55 低於 nginx 預設的 60 秒 proxy_read_timeout，避免被切)
- 超過 55 的值 hub 自動 cap 為 55 (不回 400，讓 consumer 可以直接塞 `1200` 也能正常工作)
- hub 最多撐 `timeout` 秒，期間狀態任一變動就立即回；期滿仍 pending 亦回 `{status: "pending"}`，由 consumer 決定是否重撥

**Response 200**:

```json
{
  "request_id": "req_01hz...",
  "status": "approved",
  "decided_at": "2026-04-22T07:08:45+08:00",
  "per_item": [
    {"id": "1", "decision": "approved"},
    {"id": "2", "decision": "approved"},
    {"id": "3", "decision": "rejected", "reject_reason": "這不急，明天再延"}
  ]
}
```

### 4.3 `GET /v1/approvals/<id>`

不等，直接讀目前狀態。適合跨 tick 讀上次 async 請求的結果。

### 4.4 `POST /v1/jobs`

建立 agent job (手動喚醒用)。此 endpoint 也供 Telegram `/task` 命令內部使用。

```http
POST /v1/jobs HTTP/1.1
Authorization: Bearer <consumer_token>
Content-Type: application/json

{
  "agent": "alphaforge",
  "prompt": "幫我看 2330 最近 10 天有沒有缺口",
  "notify_chat_id": 8410224536
}
```

`agent` 欄位語意 == `consumers.name`。v1 一個 consumer 對應一個 agent daemon (同名)，未來若有單 consumer 多 daemon 的需求再擴。

**Response 201**: `{ "job_id": "job_01hz...", "status": "pending" }`

### 4.5 `GET /v1/jobs/next`

Daemon long-poll 領 job。

```http
GET /v1/jobs/next?agent=alphaforge&timeout=30 HTTP/1.1
Authorization: Bearer <consumer_token>
```

**Response 200** (有 job):

```json
{
  "job_id": "job_01hz...",
  "prompt": "幫我看 2330 最近 10 天有沒有缺口",
  "notify_chat_id": 8410224536,
  "created_at": "..."
}
```

抓取時 hub 以 `SELECT ... FOR UPDATE SKIP LOCKED` + 更新 `status=claimed, claimed_by=<instance_id>` 保證單次派送。

**Response 204** (期內沒 job): 空 body。

### 4.6 `POST /v1/jobs/<id>/complete`

Daemon 完成後回報。

```json
{
  "status": "completed",
  "result_summary": "2026-04-15 向上跳空缺口 1083→1095，其餘 9 天無",
  "result_path": "docs/reports/task-042-2330-gap.md"
}
```

Hub 若 `notify_chat_id` 有值，觸發 Telegram push 告知使用者「任務完成 + summary」。

### 4.7 `GET /healthz`

```json
{"db": "ok", "telegram": "ok", "queue_size": 3, "version": "0.1.0"}
```

`telegram` 值:
- `ok`: 最近一次 push 或 `getMe` probe 成功
- `degraded`: 近一次 push 或 probe 失敗 (錯誤存於 `TG_STATUS.last_error` in-memory, 不在此 response 暴露)
- `unknown`: 尚未有任何 push / probe 結果 (罕見, 啟動後短暫狀態)
- `skipped`: 測試用, 啟動時不做 Telegram 健康檢查

`db` 或 `telegram=degraded` 時回 503。Consumer 應在 tick 開頭先打一次; 若 503, 走 AlphaForge spec §4.4 的 `docs/proposals/` fallback。

`telegram` 狀態不是靜態快照: push 成功 → `ok`, push 失敗 → `degraded`; 此外每小時 `push_retry` job (見 §7.2) 會主動 `getMe` 更新 cache, 避免沒流量時狀態永遠停滯。

### 4.8 `POST /tg/webhook`

Telegram 推進來的 webhook 入口。驗 `X-Telegram-Bot-Api-Secret-Token` header，不符則 403。

Hub 收到後依 update 類型分派:
- `callback_query`: 查 chat_id 是否在 subscribers 白名單 → 解析 `callback_data` → 寫入 decision → 編輯原訊息 → answerCallbackQuery
- `message` + text 開頭 `/task`: 轉入 job 建立流程
- `message` + 其他 (通常是 reject reason 補述): 若 user 當前有 reject pending，存入對應 decision 的 reject_reason
- `message` 不符合以上兩類 (例如 user 隨手打招呼): log 並忽略，可選擇回一則「這個 bot 只處理 /task 命令與 approval 回覆」說明訊息 (v1 暫不回覆，減少干擾)

### 4.9 錯誤碼

| Code | 意義 |
|---|---|
| 400 | 請求格式錯；body 帶 `{error, field}` |
| 401 | token 無效 |
| 403 | webhook secret 不符 / chat_id 不在白名單 |
| 404 | request_id / job_id 不存在 |
| 409 | Idempotency-Key 衝突但 body 不同 |
| 429 | rate limit (若日後啟用) |
| 503 | DB 或 Telegram 目前不可用 |

## 5. Telegram 互動協定

### 5.1 Approval 訊息格式

HTML `parse_mode`:

```
🔔 <b>[AlphaForge] 0300 tick 3 項待批</b>

<b>項目 1</b> <code>t3-action</code>
改 deploy.sh 加 rollback hook

<b>項目 2</b> <code>memory-add</code>
新增 feedback_deploy_rollback.md

<b>項目 3</b> <code>time-extension</code>
延長執行時間 120 → 180 分鐘
```

Inline keyboard (第一層):

```
[✅ 全部同意]  [❌ 全部拒絕]
[👀 逐項批]
```

### 5.2 `callback_data` 結構

格式: `v1:<action>:<approval_id_short>:<item_id?>`

- `v1:approve_all:req_01hz...`
- `v1:reject_all:req_01hz...`
- `v1:per_item:req_01hz...` (切換逐項面板)
- `v1:item_approve:req_01hz...:3`
- `v1:item_reject:req_01hz...:3`
- `v1:back:req_01hz...` (從逐項面板返回「全部批」按鈕組；已落地的個別 decisions **保留不清除**，只影響未決項目的下一步選擇)

`callback_data` 上限 64 bytes，uuid 取前 8 碼即可符合容量。

### 5.3 逐項面板

按下「👀 逐項批」後，hub 透過 `editMessageText` + `editMessageReplyMarkup` 把訊息改寫為：

```
🔔 [AlphaForge] 0300 tick（逐項批）

1. 改 deploy.sh 加 rollback hook  [✅] [❌]
2. 新增 feedback_deploy_rollback.md  [✅] [❌]
3. 延長工時 120→180 分鐘  [✅] [❌]
```

每按一項，對應列更新為 `1. 改 deploy.sh  ✓ 同意`，按鈕列消失 (透過 editMessageReplyMarkup)。三項都有 decision 後自動結案。

### 5.4 Reject reason 收集

使用者按下任一 `item_reject` 或 `reject_all`，hub 立即透過 `sendMessage` 加 `ForceReply` 送出:

```
拒絕了項目 3（time-extension）。
回一句話我存成理由，或打「skip」跳過。
```

Hub 在 `decisions` 留下 `reject_reason = null`、等 user 下一則 message。
- 若下一則是文字 → 寫入 `reject_reason`
- 若是 `skip` → 不寫入，標記已跳過
- 若 5 分鐘沒回 → 視同 skip

### 5.5 結案訊息

原訊息最終會被編輯成 (按鈕全部移除):

```
🔔 [AlphaForge] 0300 tick ✓ 已批准全部
決定於 2026-04-22 07:08
```

或 mixed:

```
🔔 [AlphaForge] 0300 tick ⚠ 部分批准 (2/3 通過)
決定於 2026-04-22 07:08
項目 3 被退回: 這不急，明天再延
```

### 5.6 靜音時段 (quiet hours)

- 部署時透過 env var `QUIET_HOURS_START=22:00` `QUIET_HOURS_END=07:00` `QUIET_HOURS_TZ=Asia/Taipei` 設定
- 區間跨午夜：hub 計算時以 "今日 22:00 至翌日 07:00" 判定
- 靜音內建立 approval → `push_state=suppressed_quiet_hours`，**不呼叫 sendMessage**
- hub 內建排程器每日 07:00 (quiet end) 掃 `push_state=suppressed_quiet_hours` 且仍 pending 的 approval，**打包成一則訊息**一次送出:

```
🔔 早安！昨晚累積了 3 件事要批
(AlphaForge 0300 tick)

...items...

[✅ 全部同意] [❌ 全部拒絕] [👀 逐項批]
```

若兩個以上 consumer 都有 suppressed approval，依 consumer 分組發成多則早安訊息 (避免混在一起難讀)。

單一 consumer 的早安訊息若 items 過多導致超過 Telegram 4096 字元上限，hub 自動切分為多則連續訊息 (第 1 則帶 inline keyboard，後續為純資訊延伸；按鈕仍控制全部 items)。

- 白天 (非靜音時段) 建立的 approval → 立刻 push，不受影響

### 5.7 `/task` 命令

使用者在 bot 對話傳:

```
/task 幫我看 2330 最近 10 天有沒有缺口
```

Hub 行為:
1. 驗 `message.from.id` 在 subscribers 白名單
2. 解析命令 (v1 預設 agent=alphaforge；未來可 `/task --agent=rebirth ...`)
3. 寫入 `agent_jobs`，source=`telegram_task`，notify_chat_id=`message.chat.id`
4. 回覆:

```
✓ 收到任務 #<job_id 末 6 碼>
agent 拉到後會動手，做完再通知你
```

5. 當 agent 呼叫 `/v1/jobs/<id>/complete` 時，hub 根據 `notify_chat_id` 推播結果訊息

### 5.8 Telegram Rate Limit

Telegram Bot API 限制 30 msg/sec (全 bot)、1 msg/sec per chat。實作上用 p-queue 或簡單 token bucket 排程，避免被暫時封鎖。

## 6. 認證與安全

三層 auth:

### 6.1 Consumer 對 Hub

- Consumer 帶 `Authorization: Bearer <token>`
- 每個 consumer 一把 token，部署時以 env var 注入 (`NOTIFY_HUB_CONSUMER_TOKENS=alphaforge:af_xxx,rebirth:rb_yyy`)
- hub 啟動時解析、寫入 `consumers` 表 (token 存 hash)
- Token rotate: 更新 env → restart hub

### 6.2 Telegram 對 Hub

- BotFather 設定 webhook 時帶 `secret_token`
- Telegram 每次 POST `/tg/webhook` 會在 `X-Telegram-Bot-Api-Secret-Token` header 帶回這個 secret
- hub 驗不符直接 403，避免偽造 POST

### 6.3 Chat / User 白名單

- 只有 `subscribers` 表內的 `chat_id` 的 callback / message 才生效
- 非白名單的 callback_query: `answerCallbackQuery` 回「您沒有權限」並 log 事件
- 非白名單的 `/task` message: 回「未授權」並忽略

## 7. 錯誤處理 / Fallback

### 7.1 Consumer 側 (AlphaForge agent)

遵循 AlphaForge spec §4.4:
- hub 回 5xx 或 connection refused → 所有 pending proposals 落盤 `docs/proposals/<slug>.md`
- 發 Gmail `[CRITICAL]`
- User 走 `git mv` 到 `approved/` 的手動備援流程

Hub 在 spec 層**不需要額外做什麼**，只需確保: (a) 錯誤時給清楚 5xx 狀態碼，(b) 健康檢查 `/healthz` 能即時反映問題。

### 7.2 Hub 內部重試

- Telegram push 失敗: 指數退避 (1s, 5s, 30s)，5 分鐘內重試；仍失敗則 `push_state=push_failed`，記錄 `last_push_error`
- **每小時跑一次 `push_retry` 排程** (plan Task 19.5): 掃 `push_state=push_failed AND status=pending` 重送; 同一排程也主動打 `getMe` 刷新 `TG_STATUS` cache (即使當下沒 failed approval 要重送)
- 重送成功若該 approval 原本在靜音時段建立 (`expires_at IS NULL`), 一併啟動倒數
- **不主動發 Gmail 通知 Telegram 長期失效** (詳見 §10 決策)

### 7.3 Idempotency

Consumer 送 `Idempotency-Key: <uuid>`，hub 以 (consumer_id, idempotency_key) unique 查詢:
- 命中且 body 一致 → 回 200 + 原 request_id
- 命中但 body 不同 → 回 409
- 未命中 → 正常建立，201 + 新 request_id

Key 保留 7 天後連同 approval 一起 archive。

### 7.4 Timeout 自動結案

背景 worker 每 30 秒掃一次 `approvals` 表:
- `status=pending AND expires_at IS NOT NULL AND expires_at < now()` → 全部未決項目寫入 `decisions` 狀態 `timeout`，approval 狀態改 `timeout`
- **`expires_at IS NULL` 的 approval 代表仍在靜音時段 queue 等 flush, 尚未開始倒數, sweeper 必須跳過** (避免半夜建立的 approval 被 sweeper 強制掃掉, 使用者早上醒來看不到)
- 編輯原 Telegram 訊息加註「⏱ 20 分鐘已到，未批覆自動結束」
- Consumer long-poll 下次撥打會立刻拿到 `status=timeout`

## 8. 部署與設定

### 8.1 Repo 結構 (預計)

```
notify-hub/
├── README.md
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml          # FastAPI + asyncpg + httpx + aiogram (or python-telegram-bot)
├── src/
│   └── notify_hub/
│       ├── main.py
│       ├── api/
│       ├── telegram/
│       ├── db/
│       ├── scheduler/      # quiet hours 排程 + 清理 cron
│       └── models.py
├── migrations/             # alembic
└── tests/
    ├── unit/
    ├── integration/
    └── smoke/
```

### 8.2 環境變數

| Var | 用途 |
|---|---|
| `DATABASE_URL` | PostgreSQL 連線字串 |
| `TELEGRAM_BOT_TOKEN` | BotFather 給的 token |
| `TELEGRAM_WEBHOOK_SECRET` | 隨機字串，設定 webhook 時帶入 |
| `PUBLIC_BASE_URL` | 如 `https://your.domain/notify-hub`，組 webhook URL 用 |
| `NOTIFY_HUB_CONSUMER_TOKENS` | `alphaforge:af_xxx,rebirth:rb_yyy` |
| `ALLOWED_CHAT_IDS` | `8410224536` (多筆用逗號) |
| `QUIET_HOURS_START` | `22:00` |
| `QUIET_HOURS_END` | `07:00` |
| `QUIET_HOURS_TZ` | `Asia/Taipei` |
| `LOG_LEVEL` | `INFO` |

### 8.3 nginx-router 配置 (使用者現有)

新增 location 轉發到 hub container:

```
location /notify-hub/ {
    proxy_pass http://notify-hub:8080/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_read_timeout 90s;   # 夠撐 55s long-polling
}
```

### 8.4 Telegram webhook 設定

部署完成後一次性 curl:

```bash
curl -X POST "https://api.telegram.org/bot<TOKEN>/setWebhook" \
     -d "url=https://your.domain/notify-hub/tg/webhook" \
     -d "secret_token=<TELEGRAM_WEBHOOK_SECRET>" \
     -d "allowed_updates=[\"message\",\"callback_query\"]"
```

## 9. 測試策略

### 9.1 三層

| 層 | 範圍 | 備註 |
|---|---|---|
| Unit | 純函式 (狀態機、callback_data parser、quiet hours 判定) | pytest |
| Integration | FastAPI TestClient + 真 PostgreSQL + mock Telegram | testcontainers-postgres 或 CI service |
| Smoke | 真 Telegram bot (測試用第二把 token) + 真 subscriber | 手動觸發 |

### 9.2 必測 scenarios

1. Happy path (approval 建立 → push → callback_query → wait 拿到結果)
2. Quiet hours 壓住 (22:00 進來 → push_state=suppressed → 07:00 排程送出)
3. Idempotency-Key 重送不重建 + body 衝突回 409
4. Auth: 無 token → 401、錯 token → 401
5. Webhook secret 不符 → 403
6. 非白名單 chat 的 callback → 回「無權限」且 decision 不落地
7. 逐項批 (3 item: y/n/y) → status=mixed
8. Reject reason flow (ForceReply + 5 分鐘超時跳過)
9. `/task` 命令 → agent_jobs 建立 → `/v1/jobs/next` 領走 → `/complete` 回報 → push notify_chat_id
10. Timeout 自動結案 + 編輯 Telegram 訊息
11. Hub 重啟後能恢復未決 approval (狀態存 DB，無 in-memory)

### 9.3 Coverage 目標

80%。測試 prioritise 狀態機 + auth + Telegram webhook dispatch。

## 10. 開放決議與已知限制

| # | 項目 | 現狀 |
|---|---|---|
| 1 | v1 僅支援 Telegram | 未來擴 LINE / Slack 需抽 channel adapter |
| 2 | 單一 subscriber 模型 | v1 預期 1 筆；多 subscriber 的群發 / 指定策略待需求 |
| 3 | Telegram 持續失效時不發 Gmail 後援 | §10 決議 β：實務上罕見，且多半同時 Gmail 也寄不出去；不做 |
| 4 | `/task` 無 agent 選擇 | v1 僅 alphaforge；未來多 agent 時擴成 `/task --agent=xxx` |
| 5 | Hub 本身高可用 | 單機 docker 起，掛了靠 consumer fallback (AlphaForge spec §4.4)；v1 接受 |
| 6 | Rate limit / 反濫用 | v1 不做；單一使用者流量可忽略 |
| 7 | Audit log | 可選 `events` 表，v1 初版不做，靠 app log |
| 8 | 多 consumer 的 subscriber routing | v1 全 consumer 共用同一份 subscribers；未來可按 consumer 分組 |

## 11. Day 0 / 上線計畫

### 11.1 開始前置 (AlphaForge 這邊)

- [ ] notify-hub repo 建立 (`~/Documents/GitHub/notify-hub`)
- [ ] Telegram 生產 bot 申請 (與 POC 的 `@alphaforge_notify_bot` 分開，避免 token 外洩歷史)
- [ ] NAS nginx-router 新增 location
- [ ] NAS PostgreSQL 新增 `notify_hub` database

### 11.2 v0.1.0 MVP 驗收項

- [ ] `POST /v1/approvals` + `GET /v1/approvals/<id>/wait` + Telegram push + inline keyboard 全通
- [ ] 逐項批、reject reason、timeout 自動結案
- [ ] Quiet hours 壓住 + 早上排程送出
- [ ] `/task` 命令 + `/v1/jobs` 三個 endpoint (`POST` / `GET next` / `POST complete`) 端到端可用；**agent daemon 本身**屬於 AlphaForge Phase 2 plan 的工作，不在 hub v0.1.0 MVP
- [ ] `/healthz` 真實反映 DB / Telegram 狀態
- [ ] `smoke_test.py` 端對端跑完 (手動)，含真 Telegram bot 推播 + callback 收回

### 11.3 v0.2 可選強化 (不 block AlphaForge Phase 2)

- Audit log events 表
- Admin dashboard (Next.js or Grafana)
- Prometheus metrics export
- LINE adapter

## 12. 對 AlphaForge 的介接點 (供下一份 plan 參考)

- Phase 2 plan 需改動 `backend/app/agent/`:
  - 新增 `notify_hub_client.py` (薄 HTTP wrapper，重試 + Idempotency-Key 自動產生)
  - `agent_run.py` 於現有 Stage 5 位置呼叫 `notify_hub_client.approve(...)` + long-polling wait loop
  - 新增 Mac 常駐 daemon `backend/app/agent/daemon.py`，輪詢 `/v1/jobs/next` + 內部排程替代 launchd cron
- 舊有 launchd plist 降級為「啟動 daemon」而非「直接跑 tick」
- 保留 AlphaForge spec §4.4 的 `docs/proposals/` fallback 不變

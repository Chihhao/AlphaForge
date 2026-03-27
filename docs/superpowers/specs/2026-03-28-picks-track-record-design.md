# 歷史推薦成績單（Picks Track Record）設計文件

**日期**：2026-03-28
**狀態**：已確認，待實作

## 背景

AlphaForge 的核心價值主張是「推薦股票會漲」。目前 Strategy Miner 的歷史績效資料（勝率、報酬）雖然存在，但使用者只能看到彙總數字（如「勝率 76.5%」），無法看到「哪些股票被推薦過、後來怎麼了」。缺乏透明度會讓新手難以建立信任感。

**目標**：在 strategy 頁面推薦清單上方，新增一個可展開的歷史成績表，讓使用者在跟單前先了解系統過去的準確度。

## 方案選擇

採用**新後端端點**方案（不改動 schema）。理由：
- 目前已出場 picks 約 20 筆，即時計算完全夠用
- 邏輯可直接複用現有 `live-performance` 程式碼
- 不需要 migration，風險最低

## 後端設計

### 新端點

```
GET /strategy-miner/picks/concluded?limit=20&offset=0
```

### 計算邏輯

1. 查詢所有 `strategy_miner_picks`，同 `stock_id` 保留最早一筆（避免連續推薦重複計算）
2. 對每筆 pick 計算 `days_held`（推薦日至今的交易日數）
3. 用最新收盤價計算 `float_pct`
4. 判斷出場狀態：
   - `take_profit`：`current >= entry * (1 + take_profit_pct)`
   - `stop_loss`：`current <= entry * (1 - stop_loss_pct)`
   - `time_limit`：`hold_days_max <= days_held <= hold_days_max + 7`
   - `settled`：`days_held > hold_days_max + 7`
5. 只回傳已出場（非持有中）的 picks
6. 按 `pick_date` 降序排列，支援 `limit` / `offset` 分頁

### 回傳欄位

| 欄位 | 型別 | 說明 |
|------|------|------|
| `pick_date` | string | 推薦日（YYYY-MM-DD） |
| `stock_id` | string | 股票代號 |
| `stock_name` | string | 股票名稱 |
| `entry_price` | float | 入場價（推薦日收盤價） |
| `exit_reason` | string | `take_profit` / `stop_loss` / `time_limit` / `settled` |
| `return_pct` | float | 報酬 %（float_pct，近似值） |
| `days_held` | int | 持有天數 |
| `time_dimension` | string | `5d` / `10d` / `30d` |
| `buy_reasons` | list[str] | 買入理由（展開時顯示） |
| `take_profit_pct` | float | 停利目標（展開時顯示） |
| `stop_loss_pct` | float | 停損目標（展開時顯示） |
| `hold_days_max` | int | 持有天數上限（展開時顯示） |
| `total` | int | 符合條件的總筆數（用於分頁） |

### Schema

新增 `ConcludedPickItem` 與 `ConcludedPicksResponse` 兩個 Pydantic schema。

## 前端設計

### 位置

`strategy.tsx`，插入在「今日賣出提醒」與「明日建議買入」區塊之間。

### 新元件

`frontend/components/PicksTrackRecord.tsx`（獨立元件，不超過 200 行）

### 收合狀態（預設）

```
📊 歷史推薦成績  [展開 ▼]
已出場 17 筆 · 勝率 76.5% · 均報酬 +2.4%
```

彙總數字從現有 `/picks/live-performance` 取得。

### 展開狀態

每列精簡顯示（表格形式）：

| 推薦日 | 股票 | 結果 | 報酬 |
|--------|------|------|------|
| 03-05 | 立萬利 | 停利 ✅ | +12.0% |
| 02-28 | 致茂 | 到期 ✅ | +3.2% |
| 02-25 | ○○○ | 停損 ❌ | -8.0% |

點擊任一列展開細節：
```
入場價 120 · 持有 18 天 · 10d 維度
停利目標 +12% / 停損 -8% / 最多 20 天
買入理由：[近期 5 個策略共振] [RSI 超賣反彈]
```

底部：「顯示更多」按鈕，每次載入 20 筆（offset 累加）。

### 顏色語意

| 出場原因 | 報酬 | 顏色 |
|----------|------|------|
| `take_profit` | 正 | `emerald` |
| `stop_loss` | 負 | `rose` |
| `time_limit` / `settled` | 正 | `emerald` |
| `time_limit` / `settled` | 負 | `zinc-400`（中性灰） |

### API 呼叫

- 初次渲染：`/picks/live-performance`（彙總數字）
- 展開時：`/picks/concluded?limit=20&offset=0`（懶載入）
- 顯示更多：`offset += 20`

## 不在本次範圍內

- 每日排程自動寫入出場結果（schema 擴充）
- 個股頁連結回歷史成績
- 篩選 / 排序功能

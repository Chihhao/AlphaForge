# Strategy Miner 藍圖

## 定位

Alpha Miner 負責**選股**（哪些因子組合能預測報酬），Strategy Miner 負責**交易規則**（選到的股票，何時進場、何時出場、歷史上表現如何）。

兩者分工：

```
Alpha Miner（因子有效性）
        ↓
Strategy Miner（訊號 → 可執行交易建議）
        ↓
每日 17:00 自動產生「明日推薦清單」
        ↓
用戶看到：買入點、停利點、停損點、歷史逐筆交易記錄
```

---

## 每日推薦產生流程

### Step 1：篩選高品質策略

- 從 Alpha Miner 所有顯著策略中，取 **IC 前 20%**（約 14 個）
- 只用這批策略參與投票，排除 IC 低的雜訊

### Step 2：加權投票選股

- 每個入選策略對「今日有訊號的股票」投票
- 票重 = 該策略的 IC 值（IC 越高，話語權越大）
- 累積加權得票數超過門檻（至少 4 個策略同時看好）才進入候選

### Step 3：排名與上限

- 依加權得票數降序排列
- 取前 **10 檔**輸出

### Step 4：計算進出場建議

- **買入點**：明日開盤價（收盤後掛隔日開盤限價）
- **停利 / 停損**：由歷史回測自動決定（見下節）

---

## 停利停損參數尋優

### 設計原則

參數空間刻意設計得粗，避免過擬合：

| 參數 | 候選值 |
|------|--------|
| 停利 | 5% / 8% / 12% |
| 停損 | 3% / 5% / 8% |
| 持有上限 | 10 天 / 20 天 |

共 3 × 3 × 2 = **18 種組合**

### 尋優方法

1. **訓練集**：近 2 年資料的前 4/6（約 14 個月）→ 找每種組合的 Sharpe Ratio
2. **測試集**：近 2 年資料的後 2/6（約 8 個月）→ 驗證
3. 選出**訓練集 Sharpe 前三，且測試集表現最穩定**的組合作為最終參數
4. 每個 Alpha Miner 策略獨立尋優（不同策略可能有不同最佳參數）

### 出場邏輯（優先順序）

1. 收盤價觸及停利 → 隔日開盤出場
2. 收盤價觸及停損 → 隔日開盤出場
3. 持有天數達上限 → 隔日開盤出場

---

## 歷史績效格式

### 逐筆交易記錄

每檔股票展示近 2 年的完整交易歷程：

```
策略：RSI + 外資5日買超  股票：台積電 (2330)

2024/03/01  買入  780  →  2024/03/11  賣出  842   +7.9%  ✅
2024/04/15  買入  830  →  2024/04/19  賣出  789   -4.9%  ❌（停損）
2024/06/03  買入  900  →  2024/06/13  賣出  963   +7.0%  ✅
...
近 2 年共 18 筆交易
勝率：61%（11 勝 7 負）
平均報酬：+2.8%
平均持有：8.3 天
最大單筆虧損：-4.9%
```

### 彙總績效指標

| 指標 | 說明 |
|------|------|
| 勝率 | 獲利筆數 / 總筆數 |
| 平均報酬 | 所有筆交易報酬的算術平均 |
| 平均持有天數 | |
| 最大單筆虧損 | 風險控制參考 |
| Sharpe Ratio | 報酬 / 標準差（測試集） |

---

## 技術實作

### 新增資料表

```sql
-- 每日推薦清單
CREATE TABLE strategy_miner_picks (
    id              SERIAL PRIMARY KEY,
    pick_date       DATE NOT NULL,          -- 推薦日期（盤後計算日）
    stock_id        VARCHAR(10) NOT NULL,
    strategy_ids    TEXT[],                 -- 觸發的 Alpha Miner 策略 ID 列表
    weighted_score  FLOAT,                  -- 加權得票數
    entry_price     FLOAT,                  -- 買入參考價（前日收盤）
    take_profit_pct FLOAT,                  -- 停利 %
    stop_loss_pct   FLOAT,                  -- 停損 %
    hold_days_max   INT,                    -- 持有天數上限
    created_at      TIMESTAMP DEFAULT NOW()
);

-- 歷史回測交易記錄
CREATE TABLE strategy_miner_trades (
    id              SERIAL PRIMARY KEY,
    stock_id        VARCHAR(10) NOT NULL,
    strategy_id     VARCHAR(100),           -- 對應的 Alpha Miner 策略
    entry_date      DATE NOT NULL,
    entry_price     FLOAT,
    exit_date       DATE,
    exit_price      FLOAT,
    exit_reason     VARCHAR(20),            -- 'take_profit' | 'stop_loss' | 'time_limit'
    return_pct      FLOAT,
    hold_days       INT
);
```

### 新增服務

`backend/app/services/strategy_miner_service.py`

- `run_daily()` — 每日 17:05 執行（排程接在 Alpha Miner 之後）
- `backtest_strategy(strategy_id, params)` — 對單一策略跑歷史回測
- `optimize_params(strategy_id)` — 尋優停利停損組合
- `get_today_picks()` — 回傳今日推薦清單（含進出場建議）
- `get_trade_history(stock_id, strategy_id)` — 回傳逐筆交易記錄

### 新增 API

```
GET  /strategy-miner/picks/today          今日推薦清單
GET  /strategy-miner/picks/history        過去 N 天的推薦記錄
GET  /strategy-miner/trades/{stock_id}    某股票的歷史交易記錄
GET  /strategy-miner/performance          整體績效統計
```

### 排程更新

```
17:00  → sync_daily_chip_data()
17:05  → FeatureService.compute_daily()
17:10  → AlphaMinerService retrain（若為每日重訓日）
17:15  → StrategyMinerService.run_daily()   ← 新增
```

---

## 前端呈現（策略頁面改版）

### 主要區塊

1. **今日推薦**（最顯眼）
   - 最多 10 張股票卡
   - 每張：股票名稱、買入點、停利點、停損點、支撐策略數

2. **歷史績效**（點擊展開）
   - 逐筆交易表格
   - 勝率 / 平均報酬 / Sharpe

3. **Alpha Miner 策略庫**（縮小呈現，移到底部）
   - 保留現有的策略列表，但降低視覺權重

---

## 風險提示

- **停利停損以收盤價觸發，次日開盤執行**：實際成交價可能有價差
- **近 2 年回測範圍**：不代表未來績效，市場結構改變時參數需重新尋優
- **每日重算**：推薦清單每日更新，昨日推薦不一定今日仍有效
- **非投資建議**：本系統為量化學習工具，實際交易風險自負

---

## 實作優先順序

| Phase | 內容 | 預計工作量 |
|-------|------|-----------|
| Phase A | 歷史回測引擎 + 參數尋優 | 中 |
| Phase B | 每日推薦清單 API + 排程 | 小 |
| Phase C | 前端策略頁面改版 | 中 |
| Phase D | 逐筆交易記錄展示 | 小 |

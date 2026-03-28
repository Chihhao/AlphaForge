# Strategy Miner 勝率提升 + 放空訊號設計

## 背景

### 現況問題

以「隔日開盤價進場」（用戶實際能買到的價格）回測，各維度勝率如下：

| 維度 | 訊號勝率 | 買 0050 勝率 | Alpha |
|---|---|---|---|
| 5d | 45.0% | 69.5% | -24.5% |
| 10d | 58.8% | 68.5% | -9.7% |
| 30d | 69.9% | 81.3% | -11.4% |

**勝率全部低於直接買 0050。** 但平均報酬方面，10d (+4.84%) 和 30d (+15.76%) 勝過 0050，代表系統選到的股票漲幅較大，問題出在推薦太多、門檻太低，把弱訊號也推了出去。

放空驗證顯示：未被推薦的股票在 10d/30d 維度的放空勝率達 57%+，系統確實能區分漲跌。

### 目標

1. 做多推薦勝率 > 買 0050 同期勝率
2. 放空訊號在牛市中放空勝率 > 50%
3. 保留 5d / 10d / 30d 三個維度

## 設計

### 分兩階段

- **第一階段（A+C）**：門檻過濾 + 放空訊號，快速見效
- **第二階段（B）**：Alpha Miner 模型改良，提升訊號品質

### 第一階段：門檻過濾 + 放空訊號

#### 1. 放空訊號產生（Alpha Miner 層）

在現有 Alpha Miner 架構中新增反向訊號邏輯：

- **做多訊號（現有）**：多個策略同時看多（RSI 超賣回升、KD 黃金交叉、MACD 多頭排列等）
- **放空訊號（新增）**：多個策略同時看空（RSI 超買回落、KD 死亡交叉、MACD 空頭排列等）

看空策略定義方式：將現有看多指標條件反轉。例如：
- RSI 超賣 (< 30) → RSI 超買 (> 70)
- KD 黃金交叉 → KD 死亡交叉
- 均線多頭排列 → 均線空頭排列
- MACD 柱狀體由負轉正 → 由正轉負

放空訊號進入同一套 Strategy Miner 流程（回測、參數優化、每日推薦），但回測邏輯反轉（股價下跌 = 獲利）。

#### 2. 訊號強度過濾器（Strategy Miner 層）

現有問題：只要被 Alpha Miner 觸發就進推薦，沒有品質把關。

新增兩道門檻：

- **觸發策略數門檻**：只推薦觸發策略數 >= 該維度前 30% 的訊號（動態門檻，隨策略數量自動調整）
- **歷史勝率門檻**：該維度的最優參數回測勝率 >= 50%，低於此門檻的維度整個跳過

推薦數量限制：
- 做多上限 5 檔
- 放空上限 5 檔
- 未達門檻就推更少，**不湊數**

#### 3. 推薦列表合併

`strategy_miner_picks` 新增 `direction` 欄位：
- `long`：做多推薦
- `short`：放空推薦

前端顯示在同一列表，用顏色區分：
- 綠色 = 做多
- 紅色 = 放空

放空的 TP/SL 邏輯反轉：
- 做多：股價漲到 entry × (1 + TP) = 停利，跌到 entry × (1 - SL) = 停損
- 放空：股價跌到 entry × (1 - TP) = 停利，漲到 entry × (1 + SL) = 停損

### 第二階段：Alpha Miner 模型改良

#### 4. 進場價修正

回測時的 `entry_price` 從「訊號當天收盤價」改為「隔日開盤價」。這是最關鍵的修正，讓回測結果貼近用戶實際操作。

影響範圍：
- `strategy_miner_service.py` 的 `_simulate_entries()` 函式
- 回測結果（勝率、平均報酬）會下降，但更真實
- 需要 `stock_prices` 表的 `open` 欄位（已有）

#### 5. 策略淘汰機制

淘汰歷史勝率持續低於 45% 的策略（以隔日開盤價回測後的勝率為準）。

週期：每週日 run_all 時評估，連續 4 週低於門檻的策略標記為 inactive，不參與訊號產生。

#### 6. 重訓與驗證

進場價修正 + 策略淘汰後，重新執行 `run_all` 重訓所有維度的最優參數。重訓後用 `validate_vs_benchmark.py` 驗證勝率是否改善。

## 資料表變更

### alpha_signal_history

新增欄位：
- `direction` (String(5), default='long')：訊號方向，`long` 或 `short`

唯一約束更新：`(signal_date, stock_id, time_dimension)` → `(signal_date, stock_id, time_dimension, direction)`

### strategy_miner_picks

新增欄位：
- `direction` (String(5), default='long')：推薦方向

### strategy_backtest_params

`strategy_id` 擴充：
- 現有：`5d`, `10d`, `30d`
- 新增：`5d_short`, `10d_short`, `30d_short`

### strategy_miner_trades

`strategy_id` 同步擴充，放空交易的 `return_pct` 計算方式反轉：
- 做多：`(exit - entry) / entry × 100`
- 放空：`(entry - exit) / entry × 100`

## 數據流

```
Alpha Miner（每日 17:10~17:40）
  ├─ 做多訊號（多策略同時看多）
  └─ 放空訊號（多策略同時看空）
      ↓
save_today_signals()（17:45）
  └─ 寫入 alpha_signal_history（含 direction 欄位）
      ↓
Strategy Miner run_daily()（18:00）
  ├─ 訊號強度過濾（觸發數前 30% + 勝率 >= 50%）
  ├─ 做多/放空各自獨立回測參數
  ├─ 多維共鳴加分（同方向跨維度）
  └─ 推薦輸出（做多 max 5 + 放空 max 5）
      ↓
前端 Strategy 頁面
  └─ 統一列表，direction 欄位區分多/空顏色
```

## 驗證計畫

每階段完成後執行：

1. `validate_vs_benchmark.py`：做多勝率 vs 0050（目標：超越）
2. `validate_short.py`（修改版）：放空勝率（目標：> 50%）
3. 回歸測試：`pytest` 確保現有功能不壞

## 實作順序

### 第一階段
1. DB migration：新增 direction 欄位
2. Alpha Miner：新增反向策略條件、產出放空訊號
3. Strategy Miner：加入訊號強度過濾器、放空回測邏輯
4. 前端：推薦列表支援多/空顯示
5. 驗證：跑 benchmark 比對

### 第二階段
6. 回測進場價改為隔日開盤價
7. 策略淘汰機制
8. 重訓全部維度
9. 最終驗證

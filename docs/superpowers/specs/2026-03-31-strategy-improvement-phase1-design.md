# Phase 1：策略基礎修正 + 風控強化

**日期**：2026-03-31
**目標**：修正回測偏差、擴展特徵維度、引入波動率自適應風控與市場狀態過濾，建立誠實的 baseline 供後續模型升級（Phase 2: LightGBM + Walk-Forward）評估。

---

## 總覽

| 項目 | 代號 | 改動範圍 | 難度 |
|------|------|----------|------|
| 交易成本建模 | E | `strategy_miner_service.py` | 低 |
| 修復 open fallback | G | `strategy_miner_service.py` | 低 |
| 籌碼面時間窗口擴展 | F | `stock_feature.py`, `feature_service.py`, `alpha_miner_service.py` | 低 |
| ATR 動態停損停利 | C | `indicator_service.py`, `stock_feature.py`, `feature_service.py`, `strategy_miner_service.py` | 中 |
| 市場狀態 Regime Filter | D | `stock_feature.py`, `feature_service.py`, `strategy_miner_service.py` | 低 |

---

## E — 交易成本建模

### 問題

`strategy_miner_service.py:610-611` 的 return 計算完全沒有扣除交易成本：

```python
raw_return = float(r[exit_idx])
exit_return = -raw_return if is_short else raw_return
```

台股真實成本：買入手續費 0.1425% + 賣出手續費 0.1425% + 交易稅 0.3% = **~0.585%**（取 0.006）。

### 改動

**檔案**：`backend/app/services/strategy_miner_service.py`

1. 在模組頂層定義常數：
   ```python
   ROUND_TRIP_COST = 0.006  # 0.6% 來回（手續費 + 交易稅）
   ```

2. 在 `_simulate_entries` 方法中（line 610-611 附近），扣除交易成本：
   ```python
   raw_return = float(r[exit_idx])
   exit_return = (-raw_return if is_short else raw_return) - ROUND_TRIP_COST
   ```

3. 更新 `exit_price` 計算（line 617）以反映淨報酬：
   ```python
   'exit_price': round(entry_price * (1 + raw_return), 2),  # exit_price 仍用原始價格
   'return_pct': round(exit_return * 100, 4),                # return 扣除成本
   ```

### 影響

- 回測勝率會下降（更真實）
- 邊際策略（勝率接近 50%、報酬 < 1%）會被自然淘汰
- 不影響 exit_price 的計算（那是市場價格，成本是隱含的）

---

## G — 修復 open 缺失 fallback

### 問題

`strategy_miner_service.py:560-564`：當隔日開盤價不存在時，fallback 到收盤價。這對停牌/下市股票會造成生存者偏差。

```python
if open_dict and stock_id in open_dict and next_date in open_dict[stock_id]:
    entry_price = open_dict[stock_id][next_date]
else:
    entry_price = px.get(next_date, 0)  # ← 用收盤價替代
```

### 改動

**檔案**：`backend/app/services/strategy_miner_service.py`

將 fallback 邏輯改為跳過該筆交易：

```python
if open_dict and stock_id in open_dict and next_date in open_dict[stock_id]:
    entry_price = open_dict[stock_id][next_date]
else:
    continue  # open 不可用時跳過，避免用收盤價造成回測偏差
```

### 影響

- 回測樣本數會略微減少（缺少 open 的交易被跳過）
- 消除因用收盤價進場導致的偏差

---

## F — 籌碼面時間窗口擴展（10d / 20d）

### 問題

目前只有 5 日滾動窗口。機構建倉/減碼通常持續 2-4 週，5 天太短無法捕捉中期佈局。

### 改動 1：StockFeature model 新增 6 個欄位

**檔案**：`backend/app/models/stock_feature.py`

在 `dealer_buy_5d` 之後新增：

```python
# --- 籌碼面中長期（Phase 7）---
foreign_buy_10d = Column(Float, nullable=True)   # 外資10日累積淨買超（張）
foreign_buy_20d = Column(Float, nullable=True)   # 外資20日累積淨買超（張）
trust_buy_10d   = Column(Float, nullable=True)   # 投信10日累積淨買超（張）
trust_buy_20d   = Column(Float, nullable=True)   # 投信20日累積淨買超（張）
dealer_buy_10d  = Column(Float, nullable=True)   # 自營商10日累積淨買超（張）
dealer_buy_20d  = Column(Float, nullable=True)   # 自營商20日累積淨買超（張）
```

### 改動 2：feature_service.py 擴展計算

**檔案**：`backend/app/services/feature_service.py`

**`_build_chip_features` 方法**（lines 462-473）：擴展為 5d/10d/20d 三個窗口。

```python
for src_col, base_name in [
    ('foreign_net_buy', 'foreign_buy'),
    ('trust_net_buy', 'trust_buy'),
    ('dealer_net_buy', 'dealer_buy'),
]:
    if src_col not in raw.columns:
        continue
    for w in [5, 10, 20]:
        dst_col = f'{base_name}_{w}d'
        raw[dst_col] = raw.groupby('stock_id')[src_col].transform(
            lambda x: x.rolling(w, min_periods=1).sum()
        )
```

保持 `foreign_buy_5d` 等既有欄位名稱不變（向後相容）。

**`compute_daily`**（line 124）：`chip_start` 從 `timedelta(days=10)` 改為 `timedelta(days=30)` 以支援 20d 窗口。

**`backfill`**（line 280）：`chip_warmup` 同理改為 `timedelta(days=30)`。

**`compute_daily` 和 `backfill` 的寫入邏輯**：在 `StockFeature(...)` 建構式中加入 6 個新欄位的賦值。

**`_build_chip_features` 的 `keep_cols`**（line 498-503）：加入 6 個新欄位名。

### 改動 3：alpha_miner_service.py 新增因子

**檔案**：`backend/app/services/alpha_miner_service.py`

**`FACTOR_LABELS`** 新增：
```python
'foreign_buy_10d': '外資10日累積',
'foreign_buy_20d': '外資20日累積',
'trust_buy_10d':   '投信10日累積',
'trust_buy_20d':   '投信20日累積',
'dealer_buy_10d':  '自營商10日累積',
'dealer_buy_20d':  '自營商20日累積',
```

**`FACTOR_COMBINATIONS`** 新增 ~8 組：
```python
# 中長期籌碼單因子
['foreign_buy_10d'], ['foreign_buy_20d'],
['trust_buy_10d'], ['trust_buy_20d'],
# 跨期籌碼動量
['foreign_buy_5d', 'foreign_buy_20d'],
['trust_buy_5d', 'trust_buy_20d'],
# 中期籌碼 + 技術面
['foreign_buy_20d', 'rsi14'],
['trust_buy_20d', 'sector_rs'],
```

**`_LOAD_COLS`**（line 149）：自動由 `FACTOR_LABELS.keys()` 生成，無需手動修改。

Bonferroni N 從 63 增至 ~71，校正門檻從 0.00079 變為 ~0.00070，影響極小。

### 改動 4：DB migration

```sql
ALTER TABLE stock_features ADD COLUMN foreign_buy_10d FLOAT;
ALTER TABLE stock_features ADD COLUMN foreign_buy_20d FLOAT;
ALTER TABLE stock_features ADD COLUMN trust_buy_10d FLOAT;
ALTER TABLE stock_features ADD COLUMN trust_buy_20d FLOAT;
ALTER TABLE stock_features ADD COLUMN dealer_buy_10d FLOAT;
ALTER TABLE stock_features ADD COLUMN dealer_buy_20d FLOAT;
```

之後跑 `backfill_features.py` 回補歷史資料。

---

## C — ATR 動態停損停利

### 問題

固定 TP/SL 百分比對所有股票一視同仁。低波動股（台積電，日波動 ~1%）永遠到不了 TP；高波動股（小型股，日波動 ~5%）頻繁假停損。

### 改動 1：indicator_service.py 新增 ATR

**檔案**：`backend/app/services/indicator_service.py`

```python
@staticmethod
def calculate_atr_vec(df: pd.DataFrame, window: int = 20) -> pd.Series:
    """向量化計算 Average True Range"""
    def _atr_logic(group):
        high_low = group['high'] - group['low']
        high_close = (group['high'] - group['close'].shift(1)).abs()
        low_close = (group['low'] - group['close'].shift(1)).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        return tr.rolling(window).mean()
    return df.groupby('stock_id', group_keys=False).apply(_atr_logic)
```

### 改動 2：StockFeature model 新增 2 個欄位

**檔案**：`backend/app/models/stock_feature.py`

```python
# --- 波動率（Phase 7）---
atr20   = Column(Float, nullable=True)    # 20日 Average True Range
atr_pct = Column(Float, nullable=True)    # ATR / close × 100（波動率百分比）
```

### 改動 3：feature_service.py 計算 ATR

**檔案**：`backend/app/services/feature_service.py`

在 `compute_daily` 和 `backfill` 的指標計算區塊中新增：

```python
df['atr20'] = IndicatorService.calculate_atr_vec(df, 20)
df['atr_pct'] = df['atr20'] / df['close'].replace(0, np.nan) * 100
```

在 `StockFeature(...)` 建構式中加入 `atr20` 和 `atr_pct` 的賦值。

### 改動 4：strategy_miner_service.py 參數網格改為 ATR 倍數

**檔案**：`backend/app/services/strategy_miner_service.py`

**常數定義**替換：
```python
# 舊：固定百分比
# TAKE_PROFITS = [0.05, 0.08, 0.12]
# STOP_LOSSES  = [0.03, 0.05, 0.08]

# 新：ATR 倍數
TP_ATR_MULTIPLIERS = [1.5, 2.5, 3.5]
SL_ATR_MULTIPLIERS = [1.0, 1.5, 2.0]
```

**`get_params_list`** 更新：
```python
def get_params_list(dimension: str) -> list:
    hd = DIM_HOLD_DAYS[dimension]
    return [
        {'tp_atr_mult': tp, 'sl_atr_mult': sl, 'hold_days': hd}
        for tp in TP_ATR_MULTIPLIERS
        for sl in SL_ATR_MULTIPLIERS
    ]
```

**`_load_prices`** 擴展：額外從 `stock_features` 載入每日 `atr20`：
```python
# 新增 ATR 查詢
atr_rows = (
    db.query(StockFeature.stock_id, StockFeature.date, StockFeature.atr20)
    .filter(StockFeature.stock_id.in_(stock_ids), StockFeature.date >= cutoff)
    .all()
)
atr_dict: Dict[str, Dict] = {}
for r in atr_rows:
    atr_dict.setdefault(str(r.stock_id), {})[r.date] = float(r.atr20) if r.atr20 else None
```

回傳值從 `(price_dict, sorted_dates_dict, open_dict)` 變為 `(price_dict, sorted_dates_dict, open_dict, atr_dict)`。

**`_simulate_entries`** 修改：

```python
# 方法簽名新增 atr_dict 參數
def _simulate_entries(cls, signals_df, price_dict, sorted_dates_dict,
                      params_list, is_short=False, open_dict=None, atr_dict=None):

    # 在進場邏輯中（line 556 之後），用 ATR 動態計算 TP/SL：
    atr_value = atr_dict.get(stock_id, {}).get(signal_date) if atr_dict else None
    if atr_value is None or atr_value <= 0:
        continue  # ATR 不可用時跳過

    # 在參數迴圈中（line 578）：
    for param_idx, params in enumerate(params_list):
        tp_pct = params['tp_atr_mult'] * atr_value / entry_price
        sl_pct = params['sl_atr_mult'] * atr_value / entry_price
        max_days = params['hold_days']
        # 後續 TP/SL 判斷邏輯不變，只是 tp 和 sl 變成動態值
```

### 改動 5：StrategyBacktestParam 語意更新

**檔案**：`backend/app/models/strategy_backtest_param.py`

新增欄位區分新舊格式：
```python
is_atr_based = Column(Boolean, default=True)  # True=ATR倍數, False=舊版固定百分比
```

`take_profit_pct` 和 `stop_loss_pct` 儲存 ATR 倍數值（例如 2.5, 1.5）。

### 改動 6：run_daily 推薦時轉換回實際百分比

在 `_generate_direction_picks` 中，從 `stock_features` 查詢每檔推薦股票的最新 `atr20`，將 ATR 倍數乘以 ATR/price 得到實際 TP/SL 百分比，寫入 `StrategyMinerPick`。

```python
# 查詢 ATR
atr_feature = db.query(StockFeature.atr20).filter(
    StockFeature.stock_id == r.stock_id,
    StockFeature.date == latest_date
).first()
atr = atr_feature.atr20 if atr_feature and atr_feature.atr20 else None

if atr and entry_price > 0:
    tp_actual = tp_atr_mult * atr / entry_price
    sl_actual = sl_atr_mult * atr / entry_price
else:
    tp_actual, sl_actual = 0.05, 0.03  # fallback
```

### DB migration

```sql
ALTER TABLE stock_features ADD COLUMN atr20 FLOAT;
ALTER TABLE stock_features ADD COLUMN atr_pct FLOAT;
ALTER TABLE strategy_backtest_params ADD COLUMN is_atr_based BOOLEAN DEFAULT TRUE;
```

---

## D — 市場狀態 Regime Filter

### 問題

不論大盤多頭或空頭，都照常產生做多/做空推薦。在系統性風險期間，個股因子預測力大幅下降。

### 改動 1：StockFeature model 新增 2 個市場層級欄位

**檔案**：`backend/app/models/stock_feature.py`

```python
# --- 市場狀態（Phase 7）---
market_breadth = Column(Float, nullable=True)  # 全市場站上 MA20 的股票比例 (0~1)
market_trend   = Column(Float, nullable=True)  # 全市場中位數 20 日報酬 > 0 為 1，否則 0
```

### 改動 2：feature_service.py 計算市場狀態

**檔案**：`backend/app/services/feature_service.py`

**`compute_daily`**（在 target_df 生成後、寫入前）：

```python
# 市場廣度：站上 MA20 的股票比例
valid_stocks = target_df.dropna(subset=['ma20', 'close'])
if len(valid_stocks) > 0:
    breadth = float((valid_stocks['close'] > valid_stocks['ma20']).mean())
else:
    breadth = None
target_df['market_breadth'] = breadth

# 大盤趨勢：全市場中位數 20 日報酬 > 0
median_ret20 = target_df['ret20'].median()
target_df['market_trend'] = 1.0 if (pd.notna(median_ret20) and median_ret20 > 0) else 0.0
```

**`backfill`**：同理，在逐日寫入前計算該日的 breadth 和 trend。

```python
# 在逐日迴圈 (line 335) 中，對 day_df 計算
valid_day = day_df.dropna(subset=['ma20', 'close'])
if len(valid_day) > 0:
    breadth = float((valid_day['close'] > valid_day['ma20']).mean())
else:
    breadth = None
day_df['market_breadth'] = breadth

median_ret20 = day_df['ret20'].median()
day_df['market_trend'] = 1.0 if (pd.notna(median_ret20) and median_ret20 > 0) else 0.0
```

### 改動 3：strategy_miner_service.py Regime Filter

**檔案**：`backend/app/services/strategy_miner_service.py`

在 `_generate_direction_picks` 方法中（step 1 查當日訊號之前），查詢最新市場狀態：

```python
from app.models.stock_feature import StockFeature as SF

# 查最新市場廣度（取任一筆當日記錄，因市場層級指標相同）
regime_row = (
    db.query(SF.market_breadth, SF.market_trend)
    .filter(SF.date == latest_date)
    .first()
)
breadth = regime_row.market_breadth if regime_row and regime_row.market_breadth is not None else 0.5
```

根據 breadth 動態調整推薦參數：

```python
if direction == 'long':
    if breadth < 0.30:        # 弱勢市場：不到 30% 股票站上 MA20
        max_picks = 2
        trigger_pct = 0.85
    elif breadth < 0.45:
        max_picks = 3
        trigger_pct = 0.80
    else:                     # 正常/強勢
        max_picks = MAX_PICKS_PER_DIRECTION  # 5
        trigger_pct = TRIGGER_COUNT_PERCENTILE  # 0.70
elif direction == 'short':
    if breadth > 0.70:        # 強勢市場
        max_picks = 2
        trigger_pct = 0.85
    elif breadth > 0.55:
        max_picks = 3
        trigger_pct = 0.80
    else:                     # 正常/弱勢（放空有利）
        max_picks = MAX_PICKS_PER_DIRECTION
        trigger_pct = TRIGGER_COUNT_PERCENTILE
```

將 step 5（line 178-187）中硬編碼的 `TRIGGER_COUNT_PERCENTILE` 替換為動態 `trigger_pct`，step 6（line 209）中的 `MAX_PICKS_PER_DIRECTION` 替換為動態 `max_picks`。

### 設計決策

- Regime Filter **只作用於推薦層**（`run_daily` / `_generate_direction_picks`）
- 不影響訓練層（`_train_all`）和回測層（`_optimize_dimension`）
- 回測仍在所有市場狀態下計算，確保 Sharpe/勝率是跨狀態的真實表現
- 只在推薦輸出時根據當下市場狀態動態調整數量和門檻

### DB migration

```sql
ALTER TABLE stock_features ADD COLUMN market_breadth FLOAT;
ALTER TABLE stock_features ADD COLUMN market_trend FLOAT;
```

---

## DB Migration 彙總

Phase 7 總共需要新增 **10 個欄位**到 `stock_features` + **1 個欄位**到 `strategy_backtest_params`：

```sql
-- stock_features: 籌碼面中長期
ALTER TABLE stock_features ADD COLUMN foreign_buy_10d FLOAT;
ALTER TABLE stock_features ADD COLUMN foreign_buy_20d FLOAT;
ALTER TABLE stock_features ADD COLUMN trust_buy_10d FLOAT;
ALTER TABLE stock_features ADD COLUMN trust_buy_20d FLOAT;
ALTER TABLE stock_features ADD COLUMN dealer_buy_10d FLOAT;
ALTER TABLE stock_features ADD COLUMN dealer_buy_20d FLOAT;

-- stock_features: 波動率
ALTER TABLE stock_features ADD COLUMN atr20 FLOAT;
ALTER TABLE stock_features ADD COLUMN atr_pct FLOAT;

-- stock_features: 市場狀態
ALTER TABLE stock_features ADD COLUMN market_breadth FLOAT;
ALTER TABLE stock_features ADD COLUMN market_trend FLOAT;

-- strategy_backtest_params: ATR 格式標記
ALTER TABLE strategy_backtest_params ADD COLUMN is_atr_based BOOLEAN DEFAULT TRUE;
```

Migration 後需執行 `backfill_features.py` 回補歷史資料。

---

## 執行順序

建議依序實作（後者依賴前者的結果）：

1. **E + G**（交易成本 + open fallback）— 獨立修正，不影響其他項目
2. **F**（籌碼面擴展）— 需要 DB migration + backfill
3. **C**（ATR 動態停損）— 依賴 F 的 DB migration 一起做、依賴 ATR 欄位
4. **D**（Regime Filter）— 依賴 market_breadth 欄位

E+G 可以先做完並驗證；F、C、D 的 DB migration 可以一次完成，但程式碼實作建議按順序。

---

## 驗證計畫

完成後需要執行以下驗證：

1. **回測勝率對比**：跑 `StrategyMinerService.run_all()` 比較 Phase 7 前後的勝率、Sharpe、平均報酬
2. **ATR 停損合理性**：檢查不同波動率股票的實際 TP/SL 百分比分布
3. **Regime Filter 觸發驗證**：確認在歷史弱勢市場期間，推薦數量確實被縮減
4. **交易成本影響**：量化扣除 0.6% 後有多少策略失去優勢（勝率 < 50%）
5. **單元測試**：ATR 計算、Regime 門檻邏輯

---

## Phase 2 展望（本次不做）

Phase 1 完成後，將在乾淨的 baseline 上進行：
- **A**: LightGBM 取代 Logistic Regression
- **B**: Walk-Forward 滾動驗證取代單一 6 個月測試期

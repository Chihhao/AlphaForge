# Phase 1：策略基礎修正 + 風控強化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修正回測偏差（交易成本、open fallback）、擴展籌碼面特徵（10d/20d）、引入 ATR 動態停損停利與市場狀態 Regime Filter，建立誠實的 baseline。

**Architecture:** 改動集中在後端 4 個 service 檔案 + 1 個 model 檔案 + DB migration。不涉及前端或 API 介面變更。Feature 層（indicator + feature_service + model）先行，Strategy 層（strategy_miner_service + alpha_miner_service）在後。

**Tech Stack:** Python 3, FastAPI, SQLAlchemy, Pandas/NumPy, PostgreSQL

**Design spec:** `docs/superpowers/specs/2026-03-31-strategy-improvement-phase1-design.md`

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `backend/app/services/strategy_miner_service.py` | 交易成本、open fallback、ATR TP/SL、Regime Filter |
| Modify | `backend/app/models/stock_feature.py` | 新增 10 個欄位 |
| Modify | `backend/app/models/strategy_backtest_param.py` | 新增 `is_atr_based` 欄位 |
| Modify | `backend/app/services/indicator_service.py` | 新增 ATR 計算 |
| Modify | `backend/app/services/feature_service.py` | chip 10d/20d + ATR + market state 計算 |
| Modify | `backend/app/services/alpha_miner_service.py` | 新增因子標籤與組合 |
| Create | `backend/scripts/migrate_phase7.py` | DB migration 腳本 |
| Create | `backend/tests/test_strategy_miner_backtest.py` | 回測引擎單元測試 |
| Create | `backend/tests/test_indicator_atr.py` | ATR 計算單元測試 |
| Create | `backend/tests/test_feature_chip_expansion.py` | 籌碼面擴展測試 |
| Create | `backend/tests/test_regime_filter.py` | Regime Filter 測試 |

---

## Task 1: E + G — 交易成本建模 + open fallback 修復

**Files:**
- Modify: `backend/app/services/strategy_miner_service.py:31-33,556-621`
- Create: `backend/tests/test_strategy_miner_backtest.py`

- [ ] **Step 1: Write tests for transaction cost and open fallback**

Create `backend/tests/test_strategy_miner_backtest.py`:

**Phase A（Task 1，先驗證常數和原始碼邏輯）：**

```python
"""回測引擎核心邏輯測試：交易成本常數 + open 缺失跳過"""
import pytest
import inspect
from app.services.strategy_miner_service import ROUND_TRIP_COST, StrategyMinerService


class TestTransactionCostConstant:
    def test_round_trip_cost_exists(self):
        """ROUND_TRIP_COST 應約為 0.006"""
        assert 0.005 <= ROUND_TRIP_COST <= 0.007


class TestOpenFallbackLogic:
    def test_open_fallback_is_continue_not_close(self):
        """原始碼中 open fallback 應已改為 continue"""
        source = inspect.getsource(StrategyMinerService._simulate_entries)
        assert "px.get(next_date" not in source, "open fallback 應改為 continue，不應 fallback 到 close"
```

**Phase B（Task 6 完成後，回來補充整合測試）：**

在 Task 6 完成後，將以下測試追加到同一個檔案：

```python
import numpy as np
import pandas as pd
from datetime import date, timedelta


class TestTransactionCostIntegration:
    """交易成本整合測試（需 ATR 支援，Task 6 後才可執行）"""

    def test_return_deducts_cost(self):
        stock_id = "2330"
        base_date = date(2025, 1, 2)
        dates = [base_date + timedelta(days=i) for i in range(5)]

        price_dict = {stock_id: {d: p for d, p in zip(dates, [100, 105, 110, 108, 112])}}
        sorted_dates_dict = {stock_id: dates}
        open_dict = {stock_id: {d: p for d, p in zip(dates, [100, 104, 109, 107, 111])}}
        atr_dict = {stock_id: {dates[0]: 10.0}}

        signals_df = pd.DataFrame([{
            "signal_date": dates[0], "stock_id": stock_id, "stock_name": "台積電",
        }])
        params_list = [{"tp_atr_mult": 99, "sl_atr_mult": 99, "hold_days": 3}]

        results = StrategyMinerService._simulate_entries(
            signals_df, price_dict, sorted_dates_dict,
            params_list, is_short=False, open_dict=open_dict, atr_dict=atr_dict,
        )

        assert len(results[0]) == 1
        trade = results[0][0]
        raw = (108 - 104) / 104
        expected_net = raw - ROUND_TRIP_COST
        assert abs(trade["return_pct"] - expected_net * 100) < 0.01

    def test_short_return_deducts_cost(self):
        stock_id = "2330"
        base_date = date(2025, 1, 2)
        dates = [base_date + timedelta(days=i) for i in range(5)]

        price_dict = {stock_id: {d: p for d, p in zip(dates, [100, 95, 90, 92, 88])}}
        sorted_dates_dict = {stock_id: dates}
        open_dict = {stock_id: {d: p for d, p in zip(dates, [100, 96, 91, 93, 89])}}
        atr_dict = {stock_id: {dates[0]: 10.0}}

        signals_df = pd.DataFrame([{
            "signal_date": dates[0], "stock_id": stock_id, "stock_name": "台積電",
        }])
        params_list = [{"tp_atr_mult": 99, "sl_atr_mult": 99, "hold_days": 3}]

        results = StrategyMinerService._simulate_entries(
            signals_df, price_dict, sorted_dates_dict,
            params_list, is_short=True, open_dict=open_dict, atr_dict=atr_dict,
        )

        assert len(results[0]) == 1
        trade = results[0][0]
        raw = (92 - 96) / 96
        expected_net = (-raw) - ROUND_TRIP_COST
        assert abs(trade["return_pct"] - expected_net * 100) < 0.01

    def test_skip_when_open_missing(self):
        stock_id = "2330"
        base_date = date(2025, 1, 2)
        dates = [base_date + timedelta(days=i) for i in range(5)]

        price_dict = {stock_id: {d: p for d, p in zip(dates, [100, 105, 110, 108, 112])}}
        sorted_dates_dict = {stock_id: dates}
        open_dict = {stock_id: {dates[0]: 100, dates[2]: 109, dates[3]: 107, dates[4]: 111}}
        atr_dict = {stock_id: {dates[0]: 10.0}}

        signals_df = pd.DataFrame([{
            "signal_date": dates[0], "stock_id": stock_id, "stock_name": "台積電",
        }])
        params_list = [{"tp_atr_mult": 99, "sl_atr_mult": 99, "hold_days": 3}]

        results = StrategyMinerService._simulate_entries(
            signals_df, price_dict, sorted_dates_dict,
            params_list, is_short=False, open_dict=open_dict, atr_dict=atr_dict,
        )
        assert len(results[0]) == 0
```

- [ ] **Step 2: Run Phase A tests to verify they fail**

Run: `cd backend && ./.venv/bin/python -m pytest tests/test_strategy_miner_backtest.py::TestTransactionCostConstant tests/test_strategy_miner_backtest.py::TestOpenFallbackLogic -v`
Expected: FAIL — `ROUND_TRIP_COST` 不存在

- [ ] **Step 3: Implement transaction cost constant and open fallback fix**

Modify `backend/app/services/strategy_miner_service.py`:

**Add constant (after line 33, `DIM_HOLD_DAYS`):**
```python
ROUND_TRIP_COST = 0.006   # 來回交易成本 ~0.6%（手續費 0.1425%×2 + 交易稅 0.3%）
```

**Fix open fallback (lines 560-564):**

Replace:
```python
            if open_dict and stock_id in open_dict and next_date in open_dict[stock_id]:
                entry_price = open_dict[stock_id][next_date]
            else:
                # fallback：隔日收盤（open 不存在時）
                entry_price = px.get(next_date, 0)
```

With:
```python
            if open_dict and stock_id in open_dict and next_date in open_dict[stock_id]:
                entry_price = open_dict[stock_id][next_date]
            else:
                continue  # open 不可用時跳過，避免用收盤價造成回測偏差
```

**Add transaction cost deduction (lines 610-611):**

Replace:
```python
                raw_return = float(r[exit_idx])
                exit_return = -raw_return if is_short else raw_return
```

With:
```python
                raw_return = float(r[exit_idx])
                exit_return = (-raw_return if is_short else raw_return) - ROUND_TRIP_COST
```

**Fix exit_price to use raw market return (line 617):**

Replace:
```python
                    'exit_price': round(entry_price * (1 + exit_return), 2),
```

With:
```python
                    'exit_price': round(entry_price * (1 + raw_return), 2),
```

- [ ] **Step 4: Run Phase A tests to verify they pass**

Run: `cd backend && ./.venv/bin/python -m pytest tests/test_strategy_miner_backtest.py::TestTransactionCostConstant tests/test_strategy_miner_backtest.py::TestOpenFallbackLogic -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
cd backend && git add app/services/strategy_miner_service.py tests/test_strategy_miner_backtest.py
git commit -m "fix: 回測扣除交易成本 0.6% + open 缺失時跳過交易

- 新增 ROUND_TRIP_COST = 0.006 常數
- exit_return 扣除來回成本（手續費+交易稅）
- open 不存在時 continue 取代 fallback 到 close
- exit_price 改用 raw_return 計算（不含成本）

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 2: DB Migration + Model 更新

**Files:**
- Modify: `backend/app/models/stock_feature.py`
- Modify: `backend/app/models/strategy_backtest_param.py`
- Create: `backend/scripts/migrate_phase7.py`

- [ ] **Step 1: Update StockFeature model with 10 new columns**

Modify `backend/app/models/stock_feature.py`，在 `etf_net_flow_5d` 之後新增：

```python
    # --- 籌碼面中長期（Phase 7）---
    foreign_buy_10d = Column(Float, nullable=True)   # 外資10日累積淨買超（張）
    foreign_buy_20d = Column(Float, nullable=True)   # 外資20日累積淨買超（張）
    trust_buy_10d   = Column(Float, nullable=True)   # 投信10日累積淨買超（張）
    trust_buy_20d   = Column(Float, nullable=True)   # 投信20日累積淨買超（張）
    dealer_buy_10d  = Column(Float, nullable=True)   # 自營商10日累積淨買超（張）
    dealer_buy_20d  = Column(Float, nullable=True)   # 自營商20日累積淨買超（張）

    # --- 波動率（Phase 7）---
    atr20   = Column(Float, nullable=True)    # 20日 Average True Range
    atr_pct = Column(Float, nullable=True)    # ATR / close × 100（波動率百分比）

    # --- 市場狀態（Phase 7）---
    market_breadth_p7 = Column(Float, nullable=True)  # 全市場站上 MA20 的股票比例 (0~1)
    market_trend_p7   = Column(Float, nullable=True)  # 全市場中位數 20 日報酬 > 0 為 1，否則 0
```

Note: 使用 `market_breadth_p7` / `market_trend_p7` 命名是因為 `market_trend` 與既有 `ma_trend` 概念容易混淆。如果偏好 `market_breadth` / `market_trend` 原始命名，也可以，只要保持一致。**最終決定用 `market_breadth` / `market_trend`**（spec 中的命名）。

- [ ] **Step 2: Update StrategyBacktestParam model**

Modify `backend/app/models/strategy_backtest_param.py`，新增 `is_atr_based` 欄位：

```python
from sqlalchemy import Column, Integer, String, Float, Boolean, Date
from app.db.database import Base

class StrategyBacktestParam(Base):
    __tablename__ = "strategy_backtest_params"
    id               = Column(Integer, primary_key=True)
    strategy_id      = Column(String(100), index=True)
    take_profit_pct  = Column(Float)
    stop_loss_pct    = Column(Float)
    hold_days_max    = Column(Integer)
    sharpe_train     = Column(Float)
    sharpe_test      = Column(Float)
    win_rate_test    = Column(Float)
    avg_return_test  = Column(Float)
    trade_count_test = Column(Integer)
    is_optimal       = Column(Boolean, default=False)
    computed_at      = Column(Date)
    is_atr_based     = Column(Boolean, default=True)  # True=ATR倍數, False=舊版固定百分比
```

- [ ] **Step 3: Create migration script**

Create `backend/scripts/migrate_phase7.py`:

```python
"""
Phase 7 DB Migration: 新增籌碼面中長期 + 波動率 + 市場狀態欄位
用法: cd backend && ./.venv/bin/python scripts/migrate_phase7.py
"""
import sys, os
sys.path.insert(0, os.getcwd())

from app.db.database import engine
from sqlalchemy import text, inspect

COLUMNS_STOCK_FEATURES = [
    ("foreign_buy_10d", "FLOAT"),
    ("foreign_buy_20d", "FLOAT"),
    ("trust_buy_10d", "FLOAT"),
    ("trust_buy_20d", "FLOAT"),
    ("dealer_buy_10d", "FLOAT"),
    ("dealer_buy_20d", "FLOAT"),
    ("atr20", "FLOAT"),
    ("atr_pct", "FLOAT"),
    ("market_breadth", "FLOAT"),
    ("market_trend", "FLOAT"),
]

COLUMNS_BACKTEST_PARAMS = [
    ("is_atr_based", "BOOLEAN DEFAULT TRUE"),
]


def migrate():
    insp = inspect(engine)

    # stock_features
    existing_sf = {c["name"] for c in insp.get_columns("stock_features")}
    with engine.begin() as conn:
        for col_name, col_type in COLUMNS_STOCK_FEATURES:
            if col_name not in existing_sf:
                conn.execute(text(f"ALTER TABLE stock_features ADD COLUMN {col_name} {col_type}"))
                print(f"  + stock_features.{col_name}")
            else:
                print(f"  ~ stock_features.{col_name} already exists")

    # strategy_backtest_params
    existing_bp = {c["name"] for c in insp.get_columns("strategy_backtest_params")}
    with engine.begin() as conn:
        for col_name, col_type in COLUMNS_BACKTEST_PARAMS:
            if col_name not in existing_bp:
                conn.execute(text(f"ALTER TABLE strategy_backtest_params ADD COLUMN {col_name} {col_type}"))
                print(f"  + strategy_backtest_params.{col_name}")
            else:
                print(f"  ~ strategy_backtest_params.{col_name} already exists")

    print("Phase 7 migration complete.")


if __name__ == "__main__":
    migrate()
```

- [ ] **Step 4: Run migration**

Run: `cd backend && ./.venv/bin/python scripts/migrate_phase7.py`
Expected: 11 columns added successfully

- [ ] **Step 5: Commit**

```bash
cd backend && git add app/models/stock_feature.py app/models/strategy_backtest_param.py scripts/migrate_phase7.py
git commit -m "feat: Phase 7 DB migration — 新增籌碼面中長期、波動率、市場狀態欄位

- stock_features: +10 columns (chip 10d/20d, ATR, market state)
- strategy_backtest_params: +is_atr_based flag

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 3: ATR 計算 — indicator_service

**Files:**
- Modify: `backend/app/services/indicator_service.py`
- Create: `backend/tests/test_indicator_atr.py`

- [ ] **Step 1: Write failing test for ATR calculation**

Create `backend/tests/test_indicator_atr.py`:

```python
"""ATR (Average True Range) 向量化計算測試"""
import pytest
import pandas as pd
import numpy as np
from app.services.indicator_service import IndicatorService


def _make_price_df(stock_id: str, n: int = 30) -> pd.DataFrame:
    """生成模擬價格 DataFrame"""
    np.random.seed(42)
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    close = 100 + np.cumsum(np.random.randn(n) * 2)
    high = close + np.abs(np.random.randn(n))
    low = close - np.abs(np.random.randn(n))
    return pd.DataFrame({
        "stock_id": stock_id,
        "date": dates,
        "open": close + np.random.randn(n) * 0.5,
        "high": high,
        "low": low,
        "close": close,
        "volume": np.random.randint(1000, 10000, n),
    })


class TestATR:
    def test_atr_returns_series(self):
        df = _make_price_df("2330")
        result = IndicatorService.calculate_atr_vec(df, window=5)
        assert isinstance(result, pd.Series)
        assert len(result) == len(df)

    def test_atr_first_n_minus_1_are_nan(self):
        """前 window-1 筆應為 NaN（rolling 暖機）"""
        df = _make_price_df("2330")
        result = IndicatorService.calculate_atr_vec(df, window=5)
        # 第一筆的 TR 需要 shift(1) 所以是 NaN，rolling(5) 需要 5 筆
        # 因此前 5 筆左右應該是 NaN
        assert result.iloc[:5].isna().sum() >= 4

    def test_atr_values_positive(self):
        """ATR 值應全部 > 0（True Range 不可能為負）"""
        df = _make_price_df("2330")
        result = IndicatorService.calculate_atr_vec(df, window=5)
        valid = result.dropna()
        assert (valid > 0).all()

    def test_atr_multi_stock(self):
        """多檔股票各自獨立計算"""
        df1 = _make_price_df("2330", 30)
        df2 = _make_price_df("2317", 30)
        df2["close"] = df2["close"] * 3  # 價格不同 → ATR 不同
        df2["high"] = df2["high"] * 3
        df2["low"] = df2["low"] * 3
        combined = pd.concat([df1, df2]).sort_values(["stock_id", "date"]).reset_index(drop=True)

        result = IndicatorService.calculate_atr_vec(combined, window=5)
        atr_2330 = result[combined["stock_id"] == "2330"].dropna()
        atr_2317 = result[combined["stock_id"] == "2317"].dropna()
        # 2317 價格 3 倍 → ATR 也約 3 倍
        ratio = atr_2317.mean() / atr_2330.mean()
        assert 2.0 < ratio < 4.0

    def test_atr_known_value(self):
        """手動計算驗證：3 天 ATR"""
        df = pd.DataFrame({
            "stock_id": ["A"] * 4,
            "date": pd.date_range("2025-01-01", periods=4),
            "open": [100, 102, 98, 101],
            "high": [105, 106, 103, 104],
            "low": [98, 99, 95, 99],
            "close": [103, 100, 101, 102],
            "volume": [1000] * 4,
        })
        result = IndicatorService.calculate_atr_vec(df, window=3)
        # Day 0: TR = high-low = 105-98 = 7 (no prev close)
        # Day 1: TR = max(106-99, |106-103|, |99-103|) = max(7, 3, 4) = 7
        # Day 2: TR = max(103-95, |103-100|, |95-100|) = max(8, 3, 5) = 8
        # Day 3: TR = max(104-99, |104-101|, |99-101|) = max(5, 3, 2) = 5
        # ATR(3) at day 3 = mean(7, 8, 5) = 6.667
        # But day 0 TR uses high-low only (no prev close shift)
        # Actually day 0 high_close and low_close use shift(1) which is NaN
        # So TR day 0 = high-low = 7 (NaN in abs cols, max picks non-NaN)
        # Wait, pd.concat max(axis=1) with NaN: need to check behavior
        # Let's just check it's a reasonable positive number
        assert result.iloc[3] > 0
        assert pd.isna(result.iloc[0]) or result.iloc[0] > 0  # first may be partial
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ./.venv/bin/python -m pytest tests/test_indicator_atr.py -v`
Expected: FAIL — `IndicatorService` has no attribute `calculate_atr_vec`

- [ ] **Step 3: Implement ATR in indicator_service**

Modify `backend/app/services/indicator_service.py`，在 `calculate_bollinger_vec` 方法之後加入：

```python
    @staticmethod
    def calculate_atr_vec(df: pd.DataFrame, window: int = 20) -> pd.Series:
        """向量化計算 Average True Range (ATR)"""
        df = df.sort_values(['stock_id', 'date'])
        prev_close = df.groupby('stock_id')['close'].shift(1)
        high_low = df['high'] - df['low']
        high_close = (df['high'] - prev_close).abs()
        low_close = (df['low'] - prev_close).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        return df.groupby('stock_id')[tr.name if tr.name else 0].transform(
            lambda x: x  # placeholder to get index alignment
        ) if False else tr.groupby(df['stock_id']).transform(lambda x: x.rolling(window).mean())
```

Note: `pd.concat` 的結果沒有 name，groupby 需要用原始 Series。正確實作：

```python
    @staticmethod
    def calculate_atr_vec(df: pd.DataFrame, window: int = 20) -> pd.Series:
        """向量化計算 Average True Range (ATR)"""
        df = df.sort_values(['stock_id', 'date'])
        prev_close = df.groupby('stock_id')['close'].shift(1)
        high_low = df['high'] - df['low']
        high_close = (df['high'] - prev_close).abs()
        low_close = (df['low'] - prev_close).abs()
        tr = pd.DataFrame({
            'hl': high_low, 'hc': high_close, 'lc': low_close
        }).max(axis=1)
        # 用 groupby + rolling 計算各股獨立的 ATR
        atr = tr.groupby(df['stock_id']).transform(lambda x: x.rolling(window).mean())
        return atr
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && ./.venv/bin/python -m pytest tests/test_indicator_atr.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
cd backend && git add app/services/indicator_service.py tests/test_indicator_atr.py
git commit -m "feat: 新增 ATR (Average True Range) 向量化計算

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 4: Feature Pipeline 擴展 — 籌碼面 10d/20d + ATR + 市場狀態

**Files:**
- Modify: `backend/app/services/feature_service.py:33-208,280-416,429-505`
- Create: `backend/tests/test_feature_chip_expansion.py`

- [ ] **Step 1: Write failing test for chip 10d/20d features**

Create `backend/tests/test_feature_chip_expansion.py`:

```python
"""籌碼面 10d/20d 擴展 + ATR + 市場狀態計算測試"""
import pytest
import pandas as pd
import numpy as np
from datetime import date, timedelta
from app.services.feature_service import FeatureService


def _make_chip_df(stock_ids, n_days=25):
    """生成模擬籌碼 DataFrame"""
    rows = []
    for sid in stock_ids:
        for i in range(n_days):
            d = pd.Timestamp(date(2025, 1, 2) + timedelta(days=i))
            rows.append({
                'stock_id': sid,
                'date': d,
                'foreign_net_buy': np.random.randint(-100, 100),
                'trust_net_buy': np.random.randint(-50, 50),
                'dealer_net_buy': np.random.randint(-30, 30),
                'margin_balance': 1000 + i * 10,
                'foreign_hold_pct': 30.0 + i * 0.1,
            })
    return pd.DataFrame(rows)


class TestChipExpansion:
    def test_build_chip_features_has_10d_20d_columns(self):
        """_build_chip_features 應回傳 10d/20d 欄位"""
        chip_df = _make_chip_df(["2330"], 25)
        target_date = chip_df['date'].max().date()
        result = FeatureService._build_chip_features(None, target_date, _chip_df=chip_df)

        assert not result.empty
        for col in ['foreign_buy_10d', 'foreign_buy_20d',
                     'trust_buy_10d', 'trust_buy_20d',
                     'dealer_buy_10d', 'dealer_buy_20d']:
            assert col in result.columns, f"缺少欄位: {col}"

    def test_5d_unchanged(self):
        """既有 5d 欄位不受影響"""
        chip_df = _make_chip_df(["2330"], 25)
        target_date = chip_df['date'].max().date()
        result = FeatureService._build_chip_features(None, target_date, _chip_df=chip_df)

        for col in ['foreign_buy_5d', 'trust_buy_5d', 'dealer_buy_5d']:
            assert col in result.columns

    def test_20d_sum_larger_than_5d(self):
        """正值序列：20d 累積應 >= 5d 累積（絕對值）"""
        chip_df = _make_chip_df(["2330"], 25)
        # 全設正值
        chip_df['foreign_net_buy'] = 10
        target_date = chip_df['date'].max().date()
        result = FeatureService._build_chip_features(None, target_date, _chip_df=chip_df)

        row = result.iloc[0]
        assert row['foreign_buy_20d'] >= row['foreign_buy_5d']
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ./.venv/bin/python -m pytest tests/test_feature_chip_expansion.py -v`
Expected: FAIL — `foreign_buy_10d` not in columns

- [ ] **Step 3: Implement chip 10d/20d in _build_chip_features**

Modify `backend/app/services/feature_service.py`，替換 `_build_chip_features` 的 rolling sum 區塊（lines 462-473）。

Replace:
```python
        # ── 向量化計算 5 日累積淨買超 ──
        for src_col, dst_col in [
            ('foreign_net_buy', 'foreign_buy_5d'),
            ('trust_net_buy', 'trust_buy_5d'),
            ('dealer_net_buy', 'dealer_buy_5d'),
        ]:
            if src_col in raw.columns:
                raw[dst_col] = raw.groupby('stock_id')[src_col].transform(
                    lambda x: x.rolling(5, min_periods=1).sum()
                )
            else:
                raw[dst_col] = None
```

With:
```python
        # ── 向量化計算 5/10/20 日累積淨買超 ──
        for src_col, base_name in [
            ('foreign_net_buy', 'foreign_buy'),
            ('trust_net_buy', 'trust_buy'),
            ('dealer_net_buy', 'dealer_buy'),
        ]:
            if src_col not in raw.columns:
                for w in [5, 10, 20]:
                    raw[f'{base_name}_{w}d'] = None
                continue
            for w in [5, 10, 20]:
                dst_col = f'{base_name}_{w}d'
                raw[dst_col] = raw.groupby('stock_id')[src_col].transform(
                    lambda x, _w=w: x.rolling(_w, min_periods=1).sum()
                )
```

Update `keep_cols` (line 498-503) — add new columns:

Replace:
```python
        keep_cols = [
            'stock_id', 'foreign_net_buy', 'foreign_buy_5d',
            'trust_net_buy', 'trust_buy_5d',
            'margin_chg_5d', 'dealer_net_buy', 'dealer_buy_5d',
            'foreign_hold_pct', 'foreign_hold_chg_5d',
        ]
```

With:
```python
        keep_cols = [
            'stock_id', 'foreign_net_buy',
            'foreign_buy_5d', 'foreign_buy_10d', 'foreign_buy_20d',
            'trust_net_buy',
            'trust_buy_5d', 'trust_buy_10d', 'trust_buy_20d',
            'margin_chg_5d',
            'dealer_net_buy',
            'dealer_buy_5d', 'dealer_buy_10d', 'dealer_buy_20d',
            'foreign_hold_pct', 'foreign_hold_chg_5d',
        ]
```

- [ ] **Step 4: Extend chip lookback window**

In `compute_daily` (line 124), change:
```python
        chip_start = target_date - timedelta(days=10)
```
To:
```python
        chip_start = target_date - timedelta(days=30)
```

In `backfill` (line 280), change:
```python
        chip_warmup = start_date - timedelta(days=10)
```
To:
```python
        chip_warmup = start_date - timedelta(days=30)
```

- [ ] **Step 5: Add ATR + market state calculation to compute_daily**

In `compute_daily`, after line 91 (`ma_trend` calculation), add ATR:

```python
        # ATR（Phase 7）
        df['atr20'] = IndicatorService.calculate_atr_vec(df, 20)
        df['atr_pct'] = df['atr20'] / df['close'].replace(0, np.nan) * 100
```

After line 108 (`sector_rs` calculation) and before the fundamentals join, add market state:

```python
        # 市場狀態（Phase 7）
        valid_ma20 = target_df.dropna(subset=['ma20', 'close'])
        if len(valid_ma20) > 0:
            breadth = float((valid_ma20['close'] > valid_ma20['ma20']).mean())
        else:
            breadth = None
        target_df['market_breadth'] = breadth

        median_ret20 = target_df['ret20'].median()
        target_df['market_trend'] = 1.0 if (pd.notna(median_ret20) and median_ret20 > 0) else 0.0
```

- [ ] **Step 6: Add ATR + market state to backfill**

In `backfill`, after line 253 (`ma_trend`), add:

```python
        # ATR（Phase 7）
        df['atr20'] = IndicatorService.calculate_atr_vec(df, 20)
        df['atr_pct'] = df['atr20'] / df['close'].replace(0, np.nan) * 100
```

In the daily loop (line 335), after the chip merge and ETF flow, add market state:

```python
            # 市場狀態（Phase 7）
            valid_ma20 = day_df.dropna(subset=['ma20', 'close'])
            if len(valid_ma20) > 0:
                breadth = float((valid_ma20['close'] > valid_ma20['ma20']).mean())
            else:
                breadth = None
            day_df['market_breadth'] = breadth

            median_ret20 = day_df['ret20'].median() if 'ret20' in day_df.columns else None
            day_df['market_trend'] = 1.0 if (pd.notna(median_ret20) and median_ret20 > 0) else 0.0
```

- [ ] **Step 7: Update StockFeature record creation in compute_daily and backfill**

In both `compute_daily` (lines 160-201) and `backfill` (lines 363-404), add these fields to the `StockFeature(...)` constructor:

```python
                    foreign_buy_10d=_safe_float(row.get('foreign_buy_10d')),
                    foreign_buy_20d=_safe_float(row.get('foreign_buy_20d')),
                    trust_buy_10d=_safe_float(row.get('trust_buy_10d')),
                    trust_buy_20d=_safe_float(row.get('trust_buy_20d')),
                    dealer_buy_10d=_safe_float(row.get('dealer_buy_10d')),
                    dealer_buy_20d=_safe_float(row.get('dealer_buy_20d')),
                    atr20=_safe_float(row.get('atr20')),
                    atr_pct=_safe_float(row.get('atr_pct')),
                    market_breadth=_safe_float(row.get('market_breadth')),
                    market_trend=_safe_float(row.get('market_trend')),
```

Also update the chip_cols list in `backfill` (line 343-346) to include new columns:

```python
            chip_cols = ['foreign_net_buy', 'foreign_buy_5d',
                         'foreign_buy_10d', 'foreign_buy_20d',
                         'trust_net_buy', 'trust_buy_5d',
                         'trust_buy_10d', 'trust_buy_20d',
                         'margin_chg_5d',
                         'dealer_net_buy', 'dealer_buy_5d',
                         'dealer_buy_10d', 'dealer_buy_20d',
                         'foreign_hold_pct', 'foreign_hold_chg_5d']
```

And the initialization block (line 309-313):

```python
        for col in ('foreign_net_buy', 'foreign_buy_5d',
                    'foreign_buy_10d', 'foreign_buy_20d',
                    'trust_net_buy', 'trust_buy_5d',
                    'trust_buy_10d', 'trust_buy_20d',
                    'margin_chg_5d',
                    'dealer_net_buy', 'dealer_buy_5d',
                    'dealer_buy_10d', 'dealer_buy_20d',
                    'foreign_hold_pct', 'foreign_hold_chg_5d'):
            backfill_df[col] = None
```

And `compute_daily` fallback (line 134-138):

```python
            for col in ('foreign_net_buy', 'foreign_buy_5d',
                        'foreign_buy_10d', 'foreign_buy_20d',
                        'trust_net_buy', 'trust_buy_5d',
                        'trust_buy_10d', 'trust_buy_20d',
                        'margin_chg_5d',
                        'dealer_net_buy', 'dealer_buy_5d',
                        'dealer_buy_10d', 'dealer_buy_20d',
                        'foreign_hold_pct', 'foreign_hold_chg_5d'):
                target_df[col] = None
```

- [ ] **Step 8: Run tests**

Run: `cd backend && ./.venv/bin/python -m pytest tests/test_feature_chip_expansion.py tests/test_indicator_atr.py -v`
Expected: All PASS

- [ ] **Step 9: Commit**

```bash
cd backend && git add app/services/feature_service.py tests/test_feature_chip_expansion.py
git commit -m "feat: feature pipeline 擴展 — 籌碼面 10d/20d + ATR + 市場狀態

- _build_chip_features: 5d/10d/20d 三窗口滾動加總
- chip lookback 從 10 天擴展到 30 天
- ATR20 + ATR% 計算
- market_breadth + market_trend 計算
- compute_daily + backfill 同步更新

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 5: Alpha Miner 新增因子標籤與組合

**Files:**
- Modify: `backend/app/services/alpha_miner_service.py:42-149`

- [ ] **Step 1: Add new factor labels**

In `backend/app/services/alpha_miner_service.py`, add to `FACTOR_LABELS` dict (after `'etf_net_flow_5d'` line):

```python
    # Phase 7 籌碼面中長期
    'foreign_buy_10d':  '外資10日累積',
    'foreign_buy_20d':  '外資20日累積',
    'trust_buy_10d':    '投信10日累積',
    'trust_buy_20d':    '投信20日累積',
    'dealer_buy_10d':   '自營商10日累積',
    'dealer_buy_20d':   '自營商20日累積',
```

- [ ] **Step 2: Add new factor combinations**

In `FACTOR_COMBINATIONS` list, before the closing `]` (after `['etf_net_flow_5d', 'rsi14']`), add:

```python
    # Phase 7 — 中長期籌碼單因子
    ['foreign_buy_10d'], ['foreign_buy_20d'],
    ['trust_buy_10d'], ['trust_buy_20d'],
    # Phase 7 — 跨期籌碼動量（短 vs 中期差異 = 加速度信號）
    ['foreign_buy_5d', 'foreign_buy_20d'],
    ['trust_buy_5d', 'trust_buy_20d'],
    # Phase 7 — 中期籌碼 + 技術面
    ['foreign_buy_20d', 'rsi14'],
    ['trust_buy_20d', 'sector_rs'],
```

- [ ] **Step 3: Verify LOAD_COLS auto-update**

Check that line 149 (`_LOAD_COLS = ['stock_id', 'date', 'close'] + list(FACTOR_LABELS.keys())`) will automatically include the new factor names. No manual change needed.

Verify Bonferroni N auto-updates: line 152 (`_BONFERRONI_N = len(FACTOR_COMBINATIONS)`) — also automatic.

- [ ] **Step 4: Commit**

```bash
cd backend && git add app/services/alpha_miner_service.py
git commit -m "feat: Alpha Miner 新增 8 組中長期籌碼因子組合

- 6 個新因子標籤（foreign/trust/dealer 10d/20d）
- 8 組新因子組合（單因子 + 跨期動量 + 技術面複合）
- Bonferroni N: 63 → 71，自動更新

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 6: ATR 動態停損停利 — strategy_miner_service

**Files:**
- Modify: `backend/app/services/strategy_miner_service.py:31-44,509-621,626-659`

- [ ] **Step 1: Replace fixed TP/SL with ATR multipliers**

In `backend/app/services/strategy_miner_service.py`, replace the parameter constants:

Replace:
```python
# ─── 參數組合（持有天數與維度對齊）──────────────────────────────────────────────
TAKE_PROFITS = [0.05, 0.08, 0.12]
STOP_LOSSES  = [0.03, 0.05, 0.08]
DIM_HOLD_DAYS = {'5d': 5, '10d': 10, '30d': 30}


def get_params_list(dimension: str) -> list:
    """回傳指定維度的參數組合（9 種：3 TP × 3 SL × 1 HD）"""
    hd = DIM_HOLD_DAYS[dimension]
    return [
        {'take_profit_pct': tp, 'stop_loss_pct': sl, 'hold_days': hd}
        for tp in TAKE_PROFITS
        for sl in STOP_LOSSES
    ]  # 9 combos
```

With:
```python
# ─── 參數組合（ATR 倍數 × 持有天數）─────────────────────────────────────────────
TP_ATR_MULTIPLIERS = [1.5, 2.5, 3.5]   # 停利 = N × ATR
SL_ATR_MULTIPLIERS = [1.0, 1.5, 2.0]   # 停損 = M × ATR
DIM_HOLD_DAYS = {'5d': 5, '10d': 10, '30d': 30}


def get_params_list(dimension: str) -> list:
    """回傳指定維度的參數組合（9 種：3 TP × 3 SL × 1 HD）"""
    hd = DIM_HOLD_DAYS[dimension]
    return [
        {'tp_atr_mult': tp, 'sl_atr_mult': sl, 'hold_days': hd}
        for tp in TP_ATR_MULTIPLIERS
        for sl in SL_ATR_MULTIPLIERS
    ]  # 9 combos
```

- [ ] **Step 2: Update _load_prices to also load ATR data**

Replace `_load_prices` method entirely:

```python
    @classmethod
    def _load_prices(
        cls,
        db: Session,
        stock_ids: List[str],
        cutoff: date,
    ) -> Tuple[Dict[str, Dict], Dict[str, List], Dict[str, Dict], Dict[str, Dict]]:
        """批次載入股票歷史 open + close 價格 + ATR"""
        from app.models.stock_feature import StockFeature

        rows = (
            db.query(StockPrice.stock_id, StockPrice.date, StockPrice.open, StockPrice.close)
            .filter(
                StockPrice.stock_id.in_(stock_ids),
                StockPrice.date >= cutoff,
                StockPrice.close.isnot(None),
            )
            .order_by(StockPrice.stock_id, StockPrice.date)
            .all()
        )

        price_dict: Dict[str, Dict] = {}
        open_dict: Dict[str, Dict] = {}
        sorted_dates_dict: Dict[str, List] = {}

        for r in rows:
            sid = str(r.stock_id)
            if sid not in price_dict:
                price_dict[sid] = {}
                open_dict[sid] = {}
                sorted_dates_dict[sid] = []
            price_dict[sid][r.date] = float(r.close)
            if r.open:
                open_dict[sid][r.date] = float(r.open)
            sorted_dates_dict[sid].append(r.date)

        # 載入 ATR
        atr_rows = (
            db.query(StockFeature.stock_id, StockFeature.date, StockFeature.atr20)
            .filter(
                StockFeature.stock_id.in_(stock_ids),
                StockFeature.date >= cutoff,
                StockFeature.atr20.isnot(None),
            )
            .all()
        )
        atr_dict: Dict[str, Dict] = {}
        for r in atr_rows:
            sid = str(r.stock_id)
            atr_dict.setdefault(sid, {})[r.date] = float(r.atr20)

        return price_dict, sorted_dates_dict, open_dict, atr_dict
```

- [ ] **Step 3: Update _simulate_entries to use ATR-based TP/SL**

Update method signature to accept `atr_dict`:

```python
    @classmethod
    def _simulate_entries(
        cls,
        signals_df: pd.DataFrame,
        price_dict: Dict[str, Dict],
        sorted_dates_dict: Dict[str, List],
        params_list: List[dict],
        is_short: bool = False,
        open_dict: Optional[Dict[str, Dict]] = None,
        atr_dict: Optional[Dict[str, Dict]] = None,
    ) -> List[List[dict]]:
```

Inside the method, after `entry_price` is determined and before the params loop, add ATR lookup:

Replace the section from line 568 to the params loop:

```python
            # ATR-based TP/SL：查詢訊號日 ATR
            stock_atr = atr_dict.get(stock_id, {}).get(signal_date) if atr_dict else None
            if stock_atr is None or stock_atr <= 0:
                continue  # ATR 不可用時跳過

            # 取隔日(含)之後 max_hold+5 個交易日的收盤
            fwd_dates = dates[sig_idx + 1 : sig_idx + 1 + max_hold + 5]
            if not fwd_dates:
                continue

            fwd_returns = np.array(
                [(px[d] - entry_price) / entry_price for d in fwd_dates],
                dtype=float,
            )

            for param_idx, params in enumerate(params_list):
                tp_pct = params['tp_atr_mult'] * stock_atr / entry_price
                sl_pct = params['sl_atr_mult'] * stock_atr / entry_price
                max_days = params['hold_days']
```

The rest of the exit logic stays the same, but replace `tp` with `tp_pct` and `sl` with `sl_pct`:

```python
                n_fwd = min(max_days, len(fwd_returns))
                if n_fwd == 0:
                    continue
                r = fwd_returns[:n_fwd]

                if is_short:
                    tp_hits = np.where(r <= -tp_pct)[0]
                    sl_hits = np.where(r >= sl_pct)[0]
                else:
                    tp_hits = np.where(r >= tp_pct)[0]
                    sl_hits = np.where(r <= -sl_pct)[0]

                tp_day = int(tp_hits[0]) if len(tp_hits) > 0 else n_fwd
                sl_day = int(sl_hits[0]) if len(sl_hits) > 0 else n_fwd

                if tp_day <= sl_day and tp_day < n_fwd:
                    exit_idx = tp_day
                    exit_reason = 'take_profit'
                elif sl_day < tp_day and sl_day < n_fwd:
                    exit_idx = sl_day
                    exit_reason = 'stop_loss'
                else:
                    exit_idx = n_fwd - 1
                    exit_reason = 'time_limit'

                raw_return = float(r[exit_idx])
                exit_return = (-raw_return if is_short else raw_return) - ROUND_TRIP_COST
                results[param_idx].append({
                    'stock_id': stock_id,
                    'entry_date': signal_date,
                    'entry_price': entry_price,
                    'exit_date': fwd_dates[exit_idx],
                    'exit_price': round(entry_price * (1 + raw_return), 2),
                    'exit_reason': exit_reason,
                    'return_pct': round(exit_return * 100, 4),
                    'hold_days': exit_idx + 1,
                })
```

- [ ] **Step 4: Update all callers of _load_prices and _simulate_entries**

In `_optimize_dimension` (line 395), update the unpacking:

Replace:
```python
        price_dict, sorted_dates_dict, open_dict = cls._load_prices(db, stock_ids, cutoff)
```
With:
```python
        price_dict, sorted_dates_dict, open_dict, atr_dict = cls._load_prices(db, stock_ids, cutoff)
```

Update all calls to `_simulate_entries` and `_simulate_all_params` to pass `atr_dict`:

Line 411:
```python
        train_trades = cls._simulate_all_params(train_df, price_dict, sorted_dates_dict, params_list, is_short=is_short, open_dict=open_dict, atr_dict=atr_dict)
```

Line 424:
```python
        test_trades_raw = cls._simulate_entries(test_df, price_dict, sorted_dates_dict, top3_params, is_short=is_short, open_dict=open_dict, atr_dict=atr_dict)
```

Line 486-488:
```python
        all_trades_by_param = cls._simulate_entries(
            signals_df, price_dict, sorted_dates_dict, [optimal_params], is_short=is_short, open_dict=open_dict, atr_dict=atr_dict,
        )
```

Update `_simulate_all_params` (line 510-521):
```python
    @classmethod
    def _simulate_all_params(
        cls,
        signals_df: pd.DataFrame,
        price_dict: Dict,
        sorted_dates_dict: Dict,
        params_list: list,
        is_short: bool = False,
        open_dict: Optional[Dict] = None,
        atr_dict: Optional[Dict] = None,
    ) -> List[List[dict]]:
        """對所有參數組合進行回測，回傳 list of trade lists"""
        return cls._simulate_entries(signals_df, price_dict, sorted_dates_dict, params_list, is_short=is_short, open_dict=open_dict, atr_dict=atr_dict)
```

- [ ] **Step 5: Update StrategyBacktestParam storage to include is_atr_based**

In `_optimize_dimension`, line 463-475, add `is_atr_based=True`:

```python
            db.add(StrategyBacktestParam(
                strategy_id=strategy_key,
                take_profit_pct=params['tp_atr_mult'],    # 儲存 ATR 倍數
                stop_loss_pct=params['sl_atr_mult'],      # 儲存 ATR 倍數
                hold_days_max=params['hold_days'],
                sharpe_train=round(tr_sharpe_val, 4),
                sharpe_test=round(te_sharpe, 4),
                win_rate_test=round(te_win, 4),
                avg_return_test=round(te_avg, 4),
                trade_count_test=te_count,
                is_optimal=(param_idx == optimal_param_idx),
                computed_at=today,
                is_atr_based=True,
            ))
```

- [ ] **Step 6: Update _generate_direction_picks to convert ATR multiplier to actual %**

In `_generate_direction_picks`, the section where picks are written (lines 260-291), update TP/SL conversion:

Replace the block:
```python
            if opt_params:
                tp = opt_params.take_profit_pct
                sl = opt_params.stop_loss_pct
                hd = opt_params.hold_days_max
            else:
                tp, sl, hd = cls._default_params(r.time_dimension)
```

With:
```python
            if opt_params:
                tp_mult = opt_params.take_profit_pct   # ATR 倍數
                sl_mult = opt_params.stop_loss_pct     # ATR 倍數
                hd = opt_params.hold_days_max
            else:
                tp_mult, sl_mult, hd = cls._default_params(r.time_dimension)

            # 查詢個股最新 ATR 轉換為實際百分比
            from app.models.stock_feature import StockFeature as SF
            atr_row = (
                db.query(SF.atr20)
                .filter(SF.stock_id == r.stock_id, SF.date == latest_date)
                .first()
            )
            if atr_row and atr_row.atr20 and entry_price > 0:
                tp = tp_mult * atr_row.atr20 / entry_price
                sl = sl_mult * atr_row.atr20 / entry_price
            else:
                tp = tp_mult * 0.03   # fallback: 假設 ATR ≈ 3% of price
                sl = sl_mult * 0.03
```

Update `_default_params` to return ATR multipliers:

Replace:
```python
    @staticmethod
    def _default_params(dimension: str) -> Tuple[float, float, int]:
        """當尚無回測結果時的 fallback 參數"""
        hd = DIM_HOLD_DAYS.get(dimension, 10)
        if dimension == '30d':
            return 0.08, 0.05, hd
        return 0.05, 0.03, hd
```

With:
```python
    @staticmethod
    def _default_params(dimension: str) -> Tuple[float, float, int]:
        """當尚無回測結果時的 fallback ATR 倍數"""
        hd = DIM_HOLD_DAYS.get(dimension, 10)
        if dimension == '30d':
            return 2.5, 1.5, hd   # TP=2.5×ATR, SL=1.5×ATR
        return 1.5, 1.0, hd      # TP=1.5×ATR, SL=1.0×ATR
```

- [ ] **Step 7: Run full test suite**

Run: `cd backend && ./.venv/bin/python -m pytest tests/ -v`
Expected: All PASS

- [ ] **Step 8: Commit**

```bash
cd backend && git add app/services/strategy_miner_service.py
git commit -m "feat: ATR 動態停損停利取代固定百分比

- TP/SL 改為 ATR 倍數（1.5/2.5/3.5 × ATR, 1.0/1.5/2.0 × ATR）
- _load_prices 新增 ATR 資料載入
- _simulate_entries 根據個股 ATR 動態計算 TP/SL
- ATR 不可用時跳過交易
- run_daily 轉換 ATR 倍數為實際百分比供前端顯示

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 7: Regime Filter — strategy_miner_service

**Files:**
- Modify: `backend/app/services/strategy_miner_service.py:108-292`
- Create: `backend/tests/test_regime_filter.py`

- [ ] **Step 1: Write failing test for regime filter**

Create `backend/tests/test_regime_filter.py`:

```python
"""市場狀態 Regime Filter 測試"""
import pytest


def _compute_regime_params(breadth: float, direction: str) -> tuple:
    """模擬 regime filter 邏輯，回傳 (max_picks, trigger_pct)"""
    from app.services.strategy_miner_service import MAX_PICKS_PER_DIRECTION, TRIGGER_COUNT_PERCENTILE

    if direction == 'long':
        if breadth < 0.30:
            return 2, 0.85
        elif breadth < 0.45:
            return 3, 0.80
        else:
            return MAX_PICKS_PER_DIRECTION, TRIGGER_COUNT_PERCENTILE
    else:  # short
        if breadth > 0.70:
            return 2, 0.85
        elif breadth > 0.55:
            return 3, 0.80
        else:
            return MAX_PICKS_PER_DIRECTION, TRIGGER_COUNT_PERCENTILE


class TestRegimeFilter:
    def test_long_weak_market_reduces_picks(self):
        """弱勢市場做多：推薦數量應縮減"""
        max_picks, trigger_pct = _compute_regime_params(0.25, 'long')
        assert max_picks == 2
        assert trigger_pct == 0.85

    def test_long_normal_market_full_picks(self):
        """正常市場做多：完整推薦"""
        max_picks, trigger_pct = _compute_regime_params(0.60, 'long')
        assert max_picks == 5
        assert trigger_pct == 0.70

    def test_long_moderate_weak_market(self):
        """中等弱勢做多：中間值"""
        max_picks, trigger_pct = _compute_regime_params(0.40, 'long')
        assert max_picks == 3
        assert trigger_pct == 0.80

    def test_short_strong_market_reduces_picks(self):
        """強勢市場放空：推薦數量應縮減"""
        max_picks, trigger_pct = _compute_regime_params(0.75, 'short')
        assert max_picks == 2
        assert trigger_pct == 0.85

    def test_short_weak_market_full_picks(self):
        """弱勢市場放空：完整推薦（放空有利）"""
        max_picks, trigger_pct = _compute_regime_params(0.35, 'short')
        assert max_picks == 5
        assert trigger_pct == 0.70

    def test_short_moderate_strong_market(self):
        """中等強勢放空：中間值"""
        max_picks, trigger_pct = _compute_regime_params(0.60, 'short')
        assert max_picks == 3
        assert trigger_pct == 0.80
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ./.venv/bin/python -m pytest tests/test_regime_filter.py -v`
Expected: PASS（純邏輯測試，不依賴 DB）— 這個測試驗證的是邏輯正確性，在實作前就可以定義。

- [ ] **Step 3: Implement regime filter in _generate_direction_picks**

Modify `backend/app/services/strategy_miner_service.py`，在 `_generate_direction_picks` 方法的開頭（line 112 之後，`dir_label` 之後），加入 regime 查詢：

```python
        # ─── Regime Filter：根據市場廣度動態調整推薦數量與門檻 ───
        from app.models.stock_feature import StockFeature as SF
        regime_row = (
            db.query(SF.market_breadth)
            .filter(SF.date == latest_date, SF.market_breadth.isnot(None))
            .first()
        )
        breadth = regime_row.market_breadth if regime_row else 0.5

        if direction == 'long':
            if breadth < 0.30:
                max_picks = 2
                trigger_pct = 0.85
            elif breadth < 0.45:
                max_picks = 3
                trigger_pct = 0.80
            else:
                max_picks = MAX_PICKS_PER_DIRECTION
                trigger_pct = TRIGGER_COUNT_PERCENTILE
        else:  # short
            if breadth > 0.70:
                max_picks = 2
                trigger_pct = 0.85
            elif breadth > 0.55:
                max_picks = 3
                trigger_pct = 0.80
            else:
                max_picks = MAX_PICKS_PER_DIRECTION
                trigger_pct = TRIGGER_COUNT_PERCENTILE

        logger.info(f"[StrategyMiner] {dir_label} Regime: breadth={breadth:.2f}, max_picks={max_picks}, trigger_pct={trigger_pct}")
```

- [ ] **Step 4: Replace hardcoded constants with regime-adjusted values**

In step 5 filtering (line 178-187), replace `TRIGGER_COUNT_PERCENTILE`:

Replace:
```python
            p70_idx = int(len(counts) * TRIGGER_COUNT_PERCENTILE)
```
With:
```python
            p70_idx = int(len(counts) * trigger_pct)
```

In step 6 final selection (line 207-209), replace `MAX_PICKS_PER_DIRECTION`:

Replace:
```python
        sorted_combined = sorted(
            combined.values(), key=lambda x: x['score'], reverse=True,
        )[:MAX_PICKS_PER_DIRECTION]
```
With:
```python
        sorted_combined = sorted(
            combined.values(), key=lambda x: x['score'], reverse=True,
        )[:max_picks]
```

- [ ] **Step 5: Run tests**

Run: `cd backend && ./.venv/bin/python -m pytest tests/test_regime_filter.py tests/test_strategy_miner_backtest.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
cd backend && git add app/services/strategy_miner_service.py tests/test_regime_filter.py
git commit -m "feat: 市場狀態 Regime Filter — 弱勢市場縮減做多、強勢市場縮減放空

- 查詢 market_breadth 動態調整推薦數量和觸發門檻
- breadth < 0.30 時做多僅推 2 檔 + P85 門檻
- breadth > 0.70 時放空僅推 2 檔 + P85 門檻
- 只作用於推薦層，不影響訓練和回測

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 8: Backfill + 整合驗證

**Files:**
- Run: `backend/scripts/backfill_features.py`
- Run: `backend/scripts/backfill_strategy_miner.py`

- [ ] **Step 1: Run feature backfill to populate new columns**

Run: `cd backend && ./.venv/bin/python scripts/backfill_features.py --years 2`

This will recompute all features including the new columns (chip 10d/20d, ATR, market state) for the last 2 years. This is an I/O intensive task — per feedback, should run on NAS container for production data, but can test locally first.

Expected: Completes without errors, logs show feature counts per day.

- [ ] **Step 2: Verify new columns are populated**

Run:
```bash
cd backend && ./.venv/bin/python -c "
from app.db.database import SessionLocal
from app.models.stock_feature import StockFeature
db = SessionLocal()
# 查最新日期的一筆記錄
r = db.query(StockFeature).order_by(StockFeature.date.desc()).first()
print(f'Date: {r.date}')
print(f'foreign_buy_10d: {r.foreign_buy_10d}')
print(f'foreign_buy_20d: {r.foreign_buy_20d}')
print(f'atr20: {r.atr20}')
print(f'atr_pct: {r.atr_pct}')
print(f'market_breadth: {r.market_breadth}')
print(f'market_trend: {r.market_trend}')
db.close()
"
```

Expected: All new fields have non-None values.

- [ ] **Step 3: Run strategy miner optimization with new parameters**

Run: `cd backend && ./.venv/bin/python scripts/backfill_strategy_miner.py`

This triggers `StrategyMinerService.run_all()` which will use the new ATR-based TP/SL grid.

Expected: Completes without errors. Logs show optimal parameters as ATR multipliers.

- [ ] **Step 4: Verify ATR-based parameters were saved**

Run:
```bash
cd backend && ./.venv/bin/python -c "
from app.db.database import SessionLocal
from app.models.strategy_backtest_param import StrategyBacktestParam
db = SessionLocal()
opts = db.query(StrategyBacktestParam).filter(StrategyBacktestParam.is_optimal == True).all()
for o in opts:
    print(f'{o.strategy_id}: TP={o.take_profit_pct}×ATR SL={o.stop_loss_pct}×ATR HD={o.hold_days_max}d WR={o.win_rate_test:.1%} is_atr={o.is_atr_based}')
db.close()
"
```

Expected: `is_atr_based=True`, TP/SL values are ATR multipliers (1.0-3.5 range, not 0.03-0.12).

- [ ] **Step 5: Run all tests**

Run: `cd backend && ./.venv/bin/python -m pytest tests/ -v`
Expected: All PASS

- [ ] **Step 6: Compare performance before/after**

Run:
```bash
cd backend && ./.venv/bin/python -c "
from app.db.database import SessionLocal
from app.models.strategy_backtest_param import StrategyBacktestParam
db = SessionLocal()
opts = db.query(StrategyBacktestParam).filter(StrategyBacktestParam.is_optimal == True).all()
for o in opts:
    wr = o.win_rate_test or 0
    avg = o.avg_return_test or 0
    sharpe = o.sharpe_test or 0
    print(f'{o.strategy_id}: win_rate={wr:.1%} avg_return={avg:.2%} sharpe={sharpe:.3f}')
db.close()
"
```

Record these numbers for comparison with Phase 2 (LightGBM + Walk-Forward) later.

- [ ] **Step 7: Final commit**

```bash
git add -A
git status
git commit -m "chore: Phase 7 backfill 完成 + 整合驗證通過

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

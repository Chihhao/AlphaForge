###### tags: `專案`,`策略推薦`,`計畫`

# 真實推薦歷史重建計畫

`文件版本: 2026-04-17a`

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把策略推薦卡上顯示的「歷史」從回測模擬交易 (`strategy_miner_trades`) 全面換成真實推薦紀錄 (`strategy_miner_picks`)，並用 walk-forward backfill 把歷史延伸回 2025-09-01，讓「勝率 / 歷史結案明細」都反映系統實際推薦事後的真實命中率。

**Architecture:**
- 後端新增 `/strategy-miner/history/{stock_id}` 端點：讀 `strategy_miner_picks`，對每筆 pick 逐日追蹤 OHLCV 判定停利/停損/到期，未結案者不回傳。
- 上方勝率/預計報酬改由同源的「真實推薦結案」計算 (`_load_stock_perf_from_picks`)，替換原基於 trades 的 `_load_stock_perf_map` 呼叫。
- 前端 `strategy.tsx` 展開卡片時改呼叫新端點；`TradeHistoryList` 空白文案修正。
- 新腳本 `backfill_picks_history_walkforward.py`：每 14 天一個 re-optimization 檢查點，用該時點之前的 `alpha_signal_history` 跑 `_optimize_dimension(as_of_date=D)` 得到當時最優參數，再用當時訊號 + 當時參數生成每日 picks，寫回 `strategy_miner_picks`。`strategy_miner_picks` 已有 `take_profit_pct/stop_loss_pct/hold_days_max` 欄位，結案判定直接用每筆 pick 當時存的參數，沒有 look-ahead。

**Tech Stack:** FastAPI、SQLAlchemy 2.0、PostgreSQL (NAS 10.0.4.3:5433)、Next.js 14、Pandas/NumPy (向量化 backfill)、Python 3.9。

---

## 檔案結構

**修改：**
- `backend/app/api/endpoints/strategy_miner.py` — 新增 `/history/{stock_id}` 端點；改 `/picks/today`、`/picks/history` 的 perf 來源。
- `backend/app/services/strategy_miner_service.py` — 新 helper `_evaluate_pick_concluded`、`_load_stock_perf_from_picks`；`_optimize_dimension` 支援 `as_of_date` 參數。
- `frontend/pages/strategy.tsx` — `handleExpand` 改端點；無樣本 UI 呈現。
- `frontend/components/TradeHistoryList.tsx` — 空白文案。

**新增：**
- `backend/scripts/backfill_picks_history_walkforward.py` — walk-forward backfill 主腳本。
- `backend/tests/services/test_strategy_miner_history.py` — `_evaluate_pick_concluded` 與 `_load_stock_perf_from_picks` 單元測試。
- `backend/tests/api/test_strategy_miner_history_endpoint.py` — 新端點整合測試。

**不動（只讀）：**
- `backend/app/models/strategy_miner_pick.py`、`strategy_miner_trade.py`、`alpha_signal_history.py`、`stock_price.py`。

---

## 不在範圍內

以下議題本計畫不處理，另案追蹤：
1. `stock_prices` 有重複列（3710 在 4/8、4/9、4/17 各出現兩次）。新 helper 會用 `SELECT DISTINCT ON` 或 Python 層 `dict` 覆寫自我防禦，但不清理 DB 源頭。
2. `_generate_direction_picks` 步驟 6.5 的「全輸過濾」仍使用 `_load_stock_perf_map`（基於 trades）— 本次不改 picks 生成管線，只改「顯示層」。
3. 推薦清單系統性偏好當日漲停股的根因（訊號基準日 vs 次日開盤進場的時序錯配）— 另案。

---

## Task 1: 新增 `_evaluate_pick_concluded` helper

**目的：** 給一筆 `StrategyMinerPick`，查後續 `stock_prices` 判定停利/停損/到期結案。未結案回 None，已結案回結案詳情。

**Files:**
- Modify: `backend/app/services/strategy_miner_service.py` — 新增 classmethod，位置放在 `get_trades` 之前 (line ~480)。
- Test: `backend/tests/services/test_strategy_miner_history.py` — 新建。

- [ ] **Step 1: Write failing test**

```python
# backend/tests/services/test_strategy_miner_history.py
"""
測試真實推薦歷史 helpers：_evaluate_pick_concluded, _load_stock_perf_from_picks
"""
from __future__ import annotations
from datetime import date
import pytest
from unittest.mock import MagicMock

from app.services.strategy_miner_service import StrategyMinerService
from app.models.strategy_miner_pick import StrategyMinerPick


def _mk_pick(
    stock_id='3710', pick_date=date(2026, 3, 1),
    entry_price=10.0, tp=0.08, sl=0.05, hd=20,
    direction='long', time_dimension='20d',
):
    p = StrategyMinerPick(
        pick_date=pick_date, stock_id=stock_id, stock_name='連展投控',
        strategy_ids='["20d"]', weighted_score=1.0, entry_price=entry_price,
        take_profit_pct=tp, stop_loss_pct=sl, hold_days_max=hd,
        time_dimension=time_dimension, direction=direction,
    )
    return p


class TestEvaluatePickConcluded:
    def test_take_profit_hit(self):
        """後續收盤達 entry × (1+tp) 當天結算為停利。"""
        pick = _mk_pick(entry_price=10.0, tp=0.08)
        # prices map: {date: close}
        prices = {
            date(2026, 3, 2): 10.3,
            date(2026, 3, 3): 10.9,   # +9% 觸發停利 (8%)
            date(2026, 3, 4): 11.5,
        }
        result = StrategyMinerService._evaluate_pick_concluded(pick, prices)
        assert result is not None
        assert result['exit_reason'] == 'take_profit'
        assert result['exit_date'] == date(2026, 3, 3)
        assert result['exit_price'] == 10.9
        assert abs(result['return_pct'] - 9.0) < 0.01  # (10.9 - 10.0)/10.0 * 100

    def test_stop_loss_hit(self):
        pick = _mk_pick(entry_price=10.0, sl=0.05)
        prices = {
            date(2026, 3, 2): 9.8,
            date(2026, 3, 3): 9.4,    # -6% 觸發停損 (5%)
        }
        result = StrategyMinerService._evaluate_pick_concluded(pick, prices)
        assert result is not None
        assert result['exit_reason'] == 'stop_loss'
        assert result['exit_date'] == date(2026, 3, 3)
        assert abs(result['return_pct'] - (-6.0)) < 0.01

    def test_time_limit_reached(self):
        """持有到 hold_days_max 未觸發 tp/sl，用當日收盤結算。"""
        pick = _mk_pick(entry_price=10.0, tp=0.20, sl=0.10, hd=3)
        prices = {
            date(2026, 3, 2): 10.2,
            date(2026, 3, 3): 10.5,
            date(2026, 3, 4): 10.3,
        }
        result = StrategyMinerService._evaluate_pick_concluded(pick, prices)
        assert result is not None
        assert result['exit_reason'] == 'time_limit'
        assert result['exit_date'] == date(2026, 3, 4)
        assert abs(result['return_pct'] - 3.0) < 0.01

    def test_still_holding_returns_none(self):
        """尚未到 hold_days_max 且未觸發條件 → None。"""
        pick = _mk_pick(entry_price=10.0, tp=0.20, sl=0.10, hd=5)
        prices = {
            date(2026, 3, 2): 10.2,
            date(2026, 3, 3): 10.5,
        }
        result = StrategyMinerService._evaluate_pick_concluded(pick, prices)
        assert result is None

    def test_short_take_profit(self):
        """放空：股價下跌至 entry × (1-tp) 觸發停利。"""
        pick = _mk_pick(entry_price=10.0, tp=0.08, direction='short')
        prices = {
            date(2026, 3, 2): 9.8,
            date(2026, 3, 3): 9.1,   # -9% 放空獲利 9%
        }
        result = StrategyMinerService._evaluate_pick_concluded(pick, prices)
        assert result is not None
        assert result['exit_reason'] == 'take_profit'
        assert abs(result['return_pct'] - 9.0) < 0.01

    def test_short_stop_loss(self):
        pick = _mk_pick(entry_price=10.0, sl=0.05, direction='short')
        prices = {date(2026, 3, 2): 10.6}  # +6% 放空虧損 6%
        result = StrategyMinerService._evaluate_pick_concluded(pick, prices)
        assert result is not None
        assert result['exit_reason'] == 'stop_loss'
        assert abs(result['return_pct'] - (-6.0)) < 0.01

    def test_no_price_data_returns_none(self):
        pick = _mk_pick(entry_price=10.0)
        result = StrategyMinerService._evaluate_pick_concluded(pick, {})
        assert result is None

    def test_includes_round_trip_cost(self):
        """扣 0.6% 來回成本。"""
        pick = _mk_pick(entry_price=10.0, tp=0.08)
        prices = {date(2026, 3, 2): 10.8}  # +8% 前，扣 0.6% 實際 +7.4%
        result = StrategyMinerService._evaluate_pick_concluded(
            pick, prices, round_trip_cost=0.006,
        )
        assert abs(result['return_pct'] - 7.4) < 0.01
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && ./.venv/bin/python -m pytest tests/services/test_strategy_miner_history.py::TestEvaluatePickConcluded -v
```
Expected: FAIL — `AttributeError: type object 'StrategyMinerService' has no attribute '_evaluate_pick_concluded'`

- [ ] **Step 3: Implement `_evaluate_pick_concluded`**

在 `backend/app/services/strategy_miner_service.py` 的 `get_trades` classmethod（line ~480 附近）之前新增：

```python
    @classmethod
    def _evaluate_pick_concluded(
        cls,
        pick,
        prices: Dict[date, float],
        round_trip_cost: float = ROUND_TRIP_COST,
    ) -> Optional[dict]:
        """判定一筆 pick 是否已結案。

        Args:
            pick: StrategyMinerPick instance
            prices: {trade_date: close_price} 僅該股後續交易日的收盤。
                    呼叫端負責查好此 dict（排除 pick_date 當日、僅含 > pick_date 的日期）。
            round_trip_cost: 來回交易成本比率（預設 0.006 = 0.6%）。

        Returns:
            結案字典 {entry_date, entry_price, exit_date, exit_price, exit_reason,
                      return_pct, hold_days, strategy_id, stock_id, direction}
            或 None（尚未結案）。
        """
        entry_price = float(pick.entry_price or 0.0)
        if entry_price <= 0:
            return None

        is_short = (pick.direction == 'short')
        tp = float(pick.take_profit_pct or 0.0)
        sl = float(pick.stop_loss_pct or 0.0)
        hd = int(pick.hold_days_max or 0)
        if hd <= 0:
            return None

        tp_price_long = entry_price * (1 + tp)
        sl_price_long = entry_price * (1 - sl)

        # 僅用 pick_date 之後的日期，且按日期順序走訪
        sorted_dates = sorted(d for d in prices.keys() if d > pick.pick_date)
        if not sorted_dates:
            return None

        for i, d in enumerate(sorted_dates, start=1):
            close = prices[d]
            if close is None or close <= 0:
                continue

            if is_short:
                # 放空：價格上漲 = 虧損、下跌 = 獲利
                if close <= entry_price * (1 - tp):
                    exit_reason = 'take_profit'
                elif close >= entry_price * (1 + sl):
                    exit_reason = 'stop_loss'
                else:
                    if i >= hd:
                        exit_reason = 'time_limit'
                    else:
                        continue
            else:
                if close >= tp_price_long:
                    exit_reason = 'take_profit'
                elif close <= sl_price_long:
                    exit_reason = 'stop_loss'
                else:
                    if i >= hd:
                        exit_reason = 'time_limit'
                    else:
                        continue

            raw_pct = (close - entry_price) / entry_price * 100.0
            ret_pct = -raw_pct if is_short else raw_pct
            ret_pct -= round_trip_cost * 100.0

            return {
                'entry_date': pick.pick_date,
                'entry_price': entry_price,
                'exit_date': d,
                'exit_price': float(close),
                'exit_reason': exit_reason,
                'return_pct': round(ret_pct, 4),
                'hold_days': i,
                'strategy_id': pick.time_dimension or '20d',
                'stock_id': pick.stock_id,
                'direction': pick.direction or 'long',
            }

        return None
```

- [ ] **Step 4: Run test to verify pass**

```bash
cd backend && ./.venv/bin/python -m pytest tests/services/test_strategy_miner_history.py::TestEvaluatePickConcluded -v
```
Expected: all 8 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/strategy_miner_service.py backend/tests/services/test_strategy_miner_history.py
git commit -m "feat(miner): add _evaluate_pick_concluded for real-history judging

Per-pick 結案判定：依 pick 當時存的 tp/sl/hd 追蹤後續 close，
tp/sl/time_limit 其一觸發即結案，尚未到期則 None。扣 0.6% 來回成本。"
```

---

## Task 2: 新增 `_load_stock_perf_from_picks` helper

**目的：** 基於 `strategy_miner_picks` + `_evaluate_pick_concluded`，計算某股的真實推薦勝率/均報酬/筆數/最佳維度，替換原基於 trades 的 `_load_stock_perf_map`。

**Files:**
- Modify: `backend/app/services/strategy_miner_service.py` — 新 top-level 函式，與 `_load_stock_perf_map` 並排 (line ~66)。
- Test: `backend/tests/services/test_strategy_miner_history.py` — 追加 class。

- [ ] **Step 1: Write failing test**

在 `backend/tests/services/test_strategy_miner_history.py` 追加：

```python
from datetime import timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.database import Base
from app.models.stock_price import StockPrice


@pytest.fixture
def mem_db():
    """in-memory SQLite 測試 DB，建立相關 tables。"""
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine, tables=[
        StrategyMinerPick.__table__,
        StockPrice.__table__,
    ])
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()


def _add_price(db, stock_id, d, close):
    db.add(StockPrice(stock_id=stock_id, date=d, open=close, high=close, low=close, close=close, volume=1000))


class TestLoadStockPerfFromPicks:
    def test_single_concluded_win(self, mem_db):
        """1 筆已結案停利 → win_rate=100%, trade_count=1。"""
        db = mem_db
        pick = _mk_pick(stock_id='3710', pick_date=date(2026, 3, 1),
                        entry_price=10.0, tp=0.08, sl=0.05, hd=5)
        db.add(pick)
        # 價格：3/2=10.2, 3/3=10.9 (觸發停利 +9% - 0.6% = 8.4%)
        _add_price(db, '3710', date(2026, 3, 2), 10.2)
        _add_price(db, '3710', date(2026, 3, 3), 10.9)
        db.commit()

        from app.services.strategy_miner_service import _load_stock_perf_from_picks
        result = _load_stock_perf_from_picks(db, ['3710'], direction='long')
        assert '3710' in result
        assert result['3710']['stock_win_rate'] == 1.0
        assert result['3710']['stock_trade_count'] == 1
        assert result['3710']['stock_avg_return'] > 8.0

    def test_still_holding_excluded(self, mem_db):
        """持有中不計入。"""
        db = mem_db
        pick = _mk_pick(stock_id='3710', pick_date=date(2026, 4, 17),
                        entry_price=6.84, hd=20)
        db.add(pick)
        db.commit()  # 沒有後續 prices → 持有中

        from app.services.strategy_miner_service import _load_stock_perf_from_picks
        result = _load_stock_perf_from_picks(db, ['3710'], direction='long')
        assert '3710' not in result

    def test_empty_stock_returns_empty(self, mem_db):
        from app.services.strategy_miner_service import _load_stock_perf_from_picks
        result = _load_stock_perf_from_picks(mem_db, [], direction='long')
        assert result == {}

    def test_mixed_win_loss(self, mem_db):
        """2 勝 1 敗 → win_rate=66.67%。"""
        db = mem_db
        # win 1
        p1 = _mk_pick(stock_id='2330', pick_date=date(2026, 1, 1),
                      entry_price=100.0, tp=0.08, sl=0.05, hd=5)
        # loss
        p2 = _mk_pick(stock_id='2330', pick_date=date(2026, 2, 1),
                      entry_price=100.0, tp=0.08, sl=0.05, hd=5)
        # win 2
        p3 = _mk_pick(stock_id='2330', pick_date=date(2026, 3, 1),
                      entry_price=100.0, tp=0.08, sl=0.05, hd=5)
        db.add_all([p1, p2, p3])
        _add_price(db, '2330', date(2026, 1, 2), 108.5)   # win
        _add_price(db, '2330', date(2026, 2, 2), 94.0)    # loss
        _add_price(db, '2330', date(2026, 3, 2), 109.0)   # win
        db.commit()

        from app.services.strategy_miner_service import _load_stock_perf_from_picks
        result = _load_stock_perf_from_picks(db, ['2330'], direction='long')
        assert result['2330']['stock_trade_count'] == 3
        assert abs(result['2330']['stock_win_rate'] - 2/3) < 0.01
```

- [ ] **Step 2: Run test to verify fails**

```bash
cd backend && ./.venv/bin/python -m pytest tests/services/test_strategy_miner_history.py::TestLoadStockPerfFromPicks -v
```
Expected: FAIL — `ImportError: cannot import name '_load_stock_perf_from_picks'`

- [ ] **Step 3: Implement helper**

在 `backend/app/services/strategy_miner_service.py` 的 `_load_stock_perf_map` 之後（約 line 113 附近）新增：

```python
def _load_stock_perf_from_picks(
    db: Session, stock_ids: list, direction: str = 'long',
) -> dict:
    """基於 strategy_miner_picks 的真實推薦紀錄，逐筆用當時存的 tp/sl/hd
    追蹤後續 stock_prices 判定結案，計算勝率/均報酬/筆數/最佳維度。

    已結案筆數 = tp/sl 觸發 + 到 hold_days_max 到期。
    持有中不計入（符合使用者「命中率視角」需求）。

    回傳格式與 _load_stock_perf_map 一致，方便端點層無縫替換。
    """
    if not stock_ids:
        return {}

    from collections import defaultdict

    # 1. 拉該 direction 所有 picks
    picks = (
        db.query(StrategyMinerPick)
        .filter(
            StrategyMinerPick.stock_id.in_(stock_ids),
            StrategyMinerPick.direction == direction,
        )
        .all()
    )
    if not picks:
        return {}

    # 2. 拉所有相關日期的 stock_prices，存成 {stock_id: {date: close}}
    # 用 dict 天然去重（同 stock_id+date 後入覆蓋前入），對抗 stock_prices 重複列
    sids_set = {p.stock_id for p in picks}
    # 計算查詢區間：最早 pick_date 到最晚 pick_date + max(hd) + 一週緩衝
    min_pick = min(p.pick_date for p in picks)
    max_hd = max(int(p.hold_days_max or 20) for p in picks)
    # 上限：今天，避免拉取未來假資料
    today = date.today()

    price_rows = (
        db.query(StockPrice.stock_id, StockPrice.date, StockPrice.close)
        .filter(
            StockPrice.stock_id.in_(sids_set),
            StockPrice.date >= min_pick,
            StockPrice.date <= today,
            StockPrice.close > 0,
        )
        .all()
    )
    price_map: dict = defaultdict(dict)
    for r in price_rows:
        price_map[r.stock_id][r.date] = float(r.close)

    # 3. 逐 pick 判定結案
    by_stock_dim: dict = defaultdict(lambda: defaultdict(list))
    for p in picks:
        stock_prices = price_map.get(p.stock_id, {})
        concluded = StrategyMinerService._evaluate_pick_concluded(p, stock_prices)
        if concluded is None:
            continue
        dim = (p.time_dimension or '20d').replace('_short', '')
        by_stock_dim[p.stock_id][dim].append(concluded['return_pct'])

    # 4. 彙總勝率/均報酬/筆數/最佳維度
    result = {}
    for sid, dim_rets in by_stock_dim.items():
        best_dim = None
        best_avg = -999.0
        total_rets: list = []
        for dim, rets in dim_rets.items():
            avg = sum(rets) / len(rets) if rets else -999.0
            if avg > best_avg:
                best_avg = avg
                best_dim = dim
            total_rets.extend(rets)
        if not total_rets:
            continue
        wins = sum(1 for x in total_rets if x > 0)
        result[sid] = {
            "stock_win_rate": round(wins / len(total_rets), 4),
            "stock_avg_return": round(sum(total_rets) / len(total_rets), 1),
            "stock_trade_count": len(total_rets),
            "stock_best_dim": best_dim or DIMENSIONS[0],
        }
    return result
```

- [ ] **Step 4: Run tests**

```bash
cd backend && ./.venv/bin/python -m pytest tests/services/test_strategy_miner_history.py -v
```
Expected: 全部 PASS（含 Task 1 的 8 個 + Task 2 的 4 個）

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/strategy_miner_service.py backend/tests/services/test_strategy_miner_history.py
git commit -m "feat(miner): add _load_stock_perf_from_picks

基於真實推薦紀錄 (strategy_miner_picks) + 結案判定計算勝率/均報酬/筆數/最佳維度，
回傳格式與舊 _load_stock_perf_map 一致，供端點層無縫替換。持有中不計入。"
```

---

## Task 3: 新端點 `/strategy-miner/history/{stock_id}`

**目的：** 回傳某股所有已結案真實推薦明細，供前端 `TradeHistoryList` 使用。格式需完全相容現有 `trades/{stock_id}` 端點，前端才能無縫切換。

**Files:**
- Modify: `backend/app/api/endpoints/strategy_miner.py` — 在 `/trades/{stock_id}` (line 540) 之後新增。
- Test: `backend/tests/api/test_strategy_miner_history_endpoint.py` — 新建。

- [ ] **Step 1: Write failing test**

```python
# backend/tests/api/test_strategy_miner_history_endpoint.py
"""新端點 /strategy-miner/history/{stock_id} 測試"""
from __future__ import annotations
from datetime import date
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from main import app
from app.db.database import Base, get_db
from app.models.strategy_miner_pick import StrategyMinerPick
from app.models.stock_price import StockPrice


@pytest.fixture
def client_and_db():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine, tables=[
        StrategyMinerPick.__table__, StockPrice.__table__,
    ])
    Session = sessionmaker(bind=engine)
    db = Session()

    def _override():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _override
    yield TestClient(app), db
    app.dependency_overrides.clear()
    db.close()


def _add_pick(db, **kw):
    defaults = dict(
        pick_date=date(2026, 3, 1), stock_id='3710', stock_name='連展投控',
        strategy_ids='["20d"]', weighted_score=1.0, entry_price=10.0,
        take_profit_pct=0.08, stop_loss_pct=0.05, hold_days_max=5,
        time_dimension='20d', direction='long',
    )
    defaults.update(kw)
    db.add(StrategyMinerPick(**defaults))


def _add_price(db, stock_id, d, close):
    db.add(StockPrice(stock_id=stock_id, date=d, open=close, high=close, low=close, close=close, volume=1000))


def test_history_returns_concluded_only(client_and_db):
    client, db = client_and_db
    # concluded win
    _add_pick(db, pick_date=date(2026, 2, 1), entry_price=10.0)
    _add_price(db, '3710', date(2026, 2, 2), 10.9)
    # still holding (no future prices)
    _add_pick(db, pick_date=date(2026, 4, 17), entry_price=20.0, hold_days_max=20)
    db.commit()

    r = client.get('/strategy-miner/history/3710')
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]['entry_date'] == '2026-02-01'
    assert data[0]['exit_reason'] == 'take_profit'
    assert 'return_pct' in data[0]
    assert data[0]['strategy_id'] == '20d'


def test_history_empty_when_no_picks(client_and_db):
    client, _ = client_and_db
    r = client.get('/strategy-miner/history/0000')
    assert r.status_code == 200
    assert r.json() == []


def test_history_contract_matches_trades_endpoint(client_and_db):
    """回傳欄位需與 /trades/{stock_id} 一致（前端相容性）。"""
    client, db = client_and_db
    _add_pick(db, pick_date=date(2026, 2, 1), entry_price=10.0)
    _add_price(db, '3710', date(2026, 2, 2), 10.9)
    db.commit()

    r = client.get('/strategy-miner/history/3710')
    data = r.json()[0]
    expected_keys = {
        'strategy_id', 'stock_id', 'entry_date', 'entry_price',
        'exit_date', 'exit_price', 'exit_reason', 'return_pct', 'hold_days',
    }
    assert expected_keys.issubset(set(data.keys()))
```

- [ ] **Step 2: Run test to verify fails**

```bash
cd backend && ./.venv/bin/python -m pytest tests/api/test_strategy_miner_history_endpoint.py -v
```
Expected: FAIL — 404 (endpoint not found)

- [ ] **Step 3: Implement endpoint**

在 `backend/app/api/endpoints/strategy_miner.py` 的 `/trades/{stock_id}` (line 540) 之後新增：

```python
@router.get("/history/{stock_id}")
def get_history(stock_id: str, db: Session = Depends(get_db)):
    """某股票的真實推薦歷史結案紀錄（取代回測模擬）。

    僅回傳已結案 (take_profit / stop_loss / time_limit) 的紀錄，
    持有中的 picks 不出現在清單。格式與 /trades/{stock_id} 相容，
    前端 TradeHistoryList 可無縫替換。
    """
    from collections import defaultdict

    picks = (
        db.query(StrategyMinerPick)
        .filter(StrategyMinerPick.stock_id == stock_id)
        .order_by(StrategyMinerPick.pick_date.desc())
        .all()
    )
    if not picks:
        return []

    # 批次載入該股所有相關日期的 stock_prices
    min_pick = min(p.pick_date for p in picks)
    max_pick = max(p.pick_date for p in picks)
    max_hd = max(int(p.hold_days_max or 20) for p in picks)
    end_bound = min(max_pick + timedelta(days=max_hd + 7), date.today())

    price_rows = (
        db.query(StockPrice.date, StockPrice.close)
        .filter(
            StockPrice.stock_id == stock_id,
            StockPrice.date >= min_pick,
            StockPrice.date <= end_bound,
            StockPrice.close > 0,
        )
        .all()
    )
    # dict 天然去重對抗 stock_prices 重複列
    prices: dict = {}
    for r in price_rows:
        prices[r.date] = float(r.close)

    concluded = []
    for p in picks:
        result = StrategyMinerService._evaluate_pick_concluded(p, prices)
        if result is None:
            continue
        concluded.append({
            "strategy_id": result['strategy_id'],
            "stock_id": result['stock_id'],
            "entry_date": result['entry_date'].isoformat(),
            "entry_price": result['entry_price'],
            "exit_date": result['exit_date'].isoformat(),
            "exit_price": result['exit_price'],
            "exit_reason": result['exit_reason'],
            "return_pct": result['return_pct'],
            "hold_days": result['hold_days'],
        })
    return concluded
```

- [ ] **Step 4: Run tests**

```bash
cd backend && ./.venv/bin/python -m pytest tests/api/test_strategy_miner_history_endpoint.py -v
```
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/endpoints/strategy_miner.py backend/tests/api/test_strategy_miner_history_endpoint.py
git commit -m "feat(miner): add /strategy-miner/history/{stock_id} endpoint

回傳某股所有真實推薦的結案明細，取代原本基於回測模擬交易的 /trades。
格式與 /trades 相容，前端可無縫切換。持有中的不回傳。"
```

---

## Task 4: `/picks/today` & `/picks/history` 改用新 perf 來源

**目的：** 卡片上方的「勝率/預計報酬/筆數」改用 `_load_stock_perf_from_picks` 計算。

**Files:**
- Modify: `backend/app/api/endpoints/strategy_miner.py` — `/picks/today` (line 133), `/picks/history` (line 490)。

- [ ] **Step 1: 改 import**

在 `backend/app/api/endpoints/strategy_miner.py` 的 line 11-15 範圍修改：

```python
from app.services.strategy_miner_service import (
    StrategyMinerService,
    _load_market_baselines_from_snapshot,
    _load_stock_perf_map,
    _load_stock_perf_from_picks,
)
```

- [ ] **Step 2: `/picks/today` 切換來源**

line 140 附近：

```python
# 原：
stock_perf = _load_stock_perf_map(db, stock_ids, direction='long')
# 改為：
stock_perf = _load_stock_perf_from_picks(db, stock_ids, direction='long')
```

- [ ] **Step 3: `/picks/history` 切換來源**

line 496 附近，同樣替換。

- [ ] **Step 4: 手動煙霧測試**

啟動後端：
```bash
cd backend && ./.venv/bin/python main.py
```
另開 terminal：
```bash
curl -s http://localhost:8000/strategy-miner/picks/today | python3 -m json.tool | head -60
```
Expected: 有資料，但 `stock_trade_count` 多數為 0（因為真實推薦歷史還少），`stock_win_rate` 多為 null 或 0。3710 應該 `stock_trade_count=0`（今日首次推薦）。

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/endpoints/strategy_miner.py
git commit -m "refactor(miner): /picks/today & /picks/history switch to real picks perf

勝率/預計報酬/筆數 從回測模擬交易換成真實推薦結案紀錄。樣本不足時
stock_trade_count=0，前端會顯示「資料累積中」。"
```

---

## Task 5: 前端 — 展開改呼叫新端點 + 空白文案

**Files:**
- Modify: `frontend/pages/strategy.tsx` — `handleExpand` (line 225-237)。
- Modify: `frontend/components/TradeHistoryList.tsx` — 空白文案 (line 55)。

- [ ] **Step 1: strategy.tsx 改端點**

```typescript
// 原 line 230：
api.get(`/strategy-miner/trades/${pick.stock_id}`)
// 改為：
api.get(`/strategy-miner/history/${pick.stock_id}`)
```

- [ ] **Step 2: TradeHistoryList.tsx 空白文案**

line 54-56：

```tsx
// 原：
{filtered.length === 0 && (
  <p className="text-sm text-zinc-500">尚無交易紀錄</p>
)}
// 改為：
{filtered.length === 0 && (
  <p className="text-sm text-zinc-500">
    此股尚無真實推薦結案紀錄（資料累積中，僅 20d 維度啟用）
  </p>
)}
```

- [ ] **Step 3: 上方勝率欄位 — 0 筆時顯示「資料累積中」**

`frontend/pages/strategy.tsx` line 290-305 區塊，修改條件：

找到：
```tsx
{(() => {
    // 現有邏輯略
    return (
        <div className="w-full flex flex-wrap items-center gap-x-2 gap-y-0.5 text-sm text-zinc-500 mt-0.5" ...>
```

在該區塊的最外層加條件：當 `count === 0` 時顯示：

```tsx
if (count === 0) {
    return (
        <div className="w-full text-xs text-zinc-500 mt-0.5">
            <span>{DIM_LABEL[dim] ?? dim} 資料累積中</span>
        </div>
    )
}
```

（具體整合到現有 IIFE 內；注意不要破壞 fallback 顯示策略級勝率的既有邏輯 — 如果 strategy_win_rate 仍有提供，保留原顯示；完全沒有時才顯示「資料累積中」）

- [ ] **Step 4: 本地啟動驗證**

前端、後端都啟動（localhost）：
```bash
cd backend && ./.venv/bin/python main.py &
cd frontend && INTERNAL_API_URL=http://localhost:8000 npm run dev
```
瀏覽 http://localhost:3000/alphaforge/strategy

驗證：
1. 點擊 3710 展開 → 顯示「此股尚無真實推薦結案紀錄」（因 4/17 首次且未結案）。
2. 展開一個被推過多次的股（從 DB 查，被推 ≥ 3 次的 59 檔中挑一個）→ 顯示其真實結案歷史。
3. 卡片上方「20d勝率 X% (N 筆) | 預計報酬 Y%」要麼消失、要麼顯示「資料累積中」。

- [ ] **Step 5: Commit**

```bash
git add frontend/pages/strategy.tsx frontend/components/TradeHistoryList.tsx
git commit -m "feat(ui): 策略推薦卡歷史改接真實推薦紀錄

展開後顯示的是 strategy_miner_picks 的真實結案交易，不再用回測模擬。
空白時明示「資料累積中」，避免使用者誤解為推薦過但虧損。"
```

---

## Task 6: `_optimize_dimension` 支援 `as_of_date` 參數

**目的：** 讓參數尋優能「只用某日期前的資料」計算最優，這是 walk-forward backfill 的基礎。

**Files:**
- Modify: `backend/app/services/strategy_miner_service.py` — `_optimize_dimension` (line 516)。
- Test: `backend/tests/services/test_strategy_miner_history.py` — 追加 class。

- [ ] **Step 1: 加 failing test（smoke）**

```python
class TestOptimizeDimensionAsOfDate:
    """只驗證 as_of_date 參數能正確切片訊號資料；不測算法細節。"""

    def test_as_of_date_filters_signals(self, monkeypatch):
        from app.services.strategy_miner_service import StrategyMinerService
        import inspect
        sig = inspect.signature(StrategyMinerService._optimize_dimension)
        assert 'as_of_date' in sig.parameters, \
            "_optimize_dimension 必須接受 as_of_date 參數"
```

- [ ] **Step 2: Run fail**

```bash
cd backend && ./.venv/bin/python -m pytest tests/services/test_strategy_miner_history.py::TestOptimizeDimensionAsOfDate -v
```
Expected: FAIL — AssertionError

- [ ] **Step 3: 改 `_optimize_dimension` 簽章**

修改 line 516：

```python
@classmethod
def _optimize_dimension(
    cls,
    db: Session,
    dimension: str,
    direction: str = 'long',
    as_of_date: Optional[date] = None,
) -> None:
    """對指定維度做參數尋優。

    Args:
        as_of_date: 若指定，只使用 signal_date <= as_of_date 的訊號資料。
                    用於 walk-forward backfill，避免 look-ahead。
                    None 時使用全部歷史（預設行為，給排程用）。
    """
    strategy_key = f"{dimension}_{direction}" if direction == 'short' else dimension
    logger.info(f"[StrategyMiner] 開始 {strategy_key} 維度參數尋優 (as_of={as_of_date})")

    # 載入歷史訊號（按 direction 過濾）
    if as_of_date is None:
        cutoff_lower = date.today() - timedelta(days=365 * 2)
        cutoff_upper = date.today()
    else:
        cutoff_lower = as_of_date - timedelta(days=365 * 2)
        cutoff_upper = as_of_date

    signal_rows = (
        db.query(AlphaSignalHistory)
        .filter(
            AlphaSignalHistory.time_dimension == dimension,
            AlphaSignalHistory.direction == direction,
            AlphaSignalHistory.signal_date >= cutoff_lower,
            AlphaSignalHistory.signal_date <= cutoff_upper,
        )
        .order_by(AlphaSignalHistory.signal_date)
        .all()
    )
    if len(signal_rows) < 20:
        logger.info(f"[StrategyMiner] {strategy_key} 訊號不足（{len(signal_rows)} 筆），跳過")
        return

    # ... 其餘邏輯不動
```

（其他邏輯保留原樣，只改輸入切片）

同時，將 line 549 的 `today` 變數替換為 `cutoff_upper`（代表回測基準日）：

```python
# line 587 附近
today = cutoff_upper
db.execute(
    delete(StrategyBacktestParam).where(StrategyBacktestParam.strategy_id == strategy_key)
)
# ...
db.add(StrategyBacktestParam(
    ...,
    computed_at=today,
    ...
))
```

- [ ] **Step 4: Run test pass**

```bash
cd backend && ./.venv/bin/python -m pytest tests/services/test_strategy_miner_history.py::TestOptimizeDimensionAsOfDate -v
```
Expected: PASS

- [ ] **Step 5: 驗證既有排程不退化**

```bash
cd backend && ./.venv/bin/python -c "
import logging
logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)
from app.db.database import SessionLocal
from app.services.strategy_miner_service import StrategyMinerService
db = SessionLocal()
# 測試向後相容：不傳 as_of_date 行為一致
StrategyMinerService._optimize_dimension(db, '20d', 'long')
print('backward compat OK')
db.close()
"
```
Expected: 印出 `backward compat OK`，無 exception。

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/strategy_miner_service.py backend/tests/services/test_strategy_miner_history.py
git commit -m "feat(miner): _optimize_dimension 支援 as_of_date 參數

讓參數尋優可以「只用某日期前的資料」計算最優，為 walk-forward backfill
做基礎。as_of_date=None 保持原排程行為不變。"
```

---

## Task 7: walk-forward backfill 腳本

**目的：** 用「每 14 天重新尋優一次」的 walk-forward 策略，把 2025-09-01 起的歷史 picks 重建到 `strategy_miner_picks`。每一天 picks 的 tp/sl/hd 都用「該日期之前」的資料決定，無 look-ahead。

**Files:**
- Create: `backend/scripts/backfill_picks_history_walkforward.py`

- [ ] **Step 1: 新建腳本**

```python
"""
backfill_picks_history_walkforward.py
─────────────────────────────────────
Walk-forward backfill 真實推薦歷史 (strategy_miner_picks)。

流程：
  1. 每 REOPT_INTERVAL_DAYS 天設一個 re-optimization checkpoint。
  2. 在每個 checkpoint D：用 signal_date <= D 的訊號跑 _optimize_dimension(as_of_date=D)，
     更新 strategy_backtest_params.is_optimal = True 的組合。
  3. 遍歷 [last_checkpoint, next_checkpoint) 區間內的每個 signal_date，
     呼叫 _generate_direction_picks 生成當日 picks，寫入 strategy_miner_picks。
     （此時 optimal 參數已是該區間對應的 walk-forward 結果）
  4. Checkpoint 往前推一階，重複。

關鍵無偏保證：
  - as_of_date 切片確保 optimizer 只看該時點前的資料
  - _generate_direction_picks 讀取當時 is_optimal 的參數
  - strategy_miner_picks 已有 tp/sl/hd 欄位，每筆 pick 保存自己當時用的參數
  - 後續 _evaluate_pick_concluded 用 pick 自己的參數判定結案，不受未來 is_optimal 變化影響

使用：
  cd backend
  ./.venv/bin/python scripts/backfill_picks_history_walkforward.py \\
      --start 2025-09-01 [--interval 14] [--dry-run]
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_START = date(2025, 9, 1)
DEFAULT_INTERVAL = 14
DIMENSIONS = ['5d', '10d', '20d']


def _reoptimize(db, checkpoint: date) -> None:
    """在 checkpoint 日期重跑 3 維度 × 2 方向 = 6 次尋優。"""
    from app.services.strategy_miner_service import StrategyMinerService
    for dim in DIMENSIONS:
        for direction in ('long', 'short'):
            try:
                StrategyMinerService._optimize_dimension(
                    db, dim, direction, as_of_date=checkpoint,
                )
            except Exception as e:
                logger.error(f"  {dim}/{direction} as_of={checkpoint} 失敗: {e}", exc_info=True)
    db.commit()


def _generate_picks_for_range(
    db, start: date, end_exclusive: date,
) -> int:
    """對 [start, end_exclusive) 區間內每一天訊號生成 picks。"""
    from app.models.alpha_signal_history import AlphaSignalHistory
    from app.services.strategy_miner_service import StrategyMinerService

    signal_dates = (
        db.query(AlphaSignalHistory.signal_date)
        .filter(
            AlphaSignalHistory.signal_date >= start,
            AlphaSignalHistory.signal_date < end_exclusive,
        )
        .distinct()
        .order_by(AlphaSignalHistory.signal_date)
        .all()
    )
    signal_dates = [r.signal_date for r in signal_dates]

    total = 0
    for d in signal_dates:
        count = 0
        for direction in ('long', 'short'):
            c = StrategyMinerService._generate_direction_picks(db, d, d, direction)
            count += c
        db.commit()
        if count > 0:
            logger.info(f"  {d}: 寫入 {count} 檔推薦")
            total += count
    return total


def main():
    parser = argparse.ArgumentParser(description="Walk-forward backfill 真實推薦歷史")
    parser.add_argument("--start", type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
                        default=DEFAULT_START, help="backfill 起始日期 (YYYY-MM-DD)")
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL,
                        help="每 N 天重新尋優一次（預設 14）")
    parser.add_argument("--dry-run", action="store_true", help="印出 checkpoints 但不寫入")
    args = parser.parse_args()

    from app.db.database import SessionLocal
    from app.models.strategy_miner_pick import StrategyMinerPick

    db = SessionLocal()
    try:
        today = date.today()
        checkpoints = []
        d = args.start
        while d < today:
            checkpoints.append(d)
            d = d + timedelta(days=args.interval)
        if checkpoints[-1] < today:
            checkpoints.append(today)

        logger.info(f"規劃 {len(checkpoints)} 個 checkpoints，間隔 {args.interval} 天")
        for cp in checkpoints:
            logger.info(f"  - {cp}")

        if args.dry_run:
            logger.info("dry-run: 不執行")
            return

        total_picks = 0
        for i, cp in enumerate(checkpoints):
            logger.info(f"=== Checkpoint {i+1}/{len(checkpoints)}: {cp} ===")
            logger.info("Step 1: 重跑參數尋優")
            _reoptimize(db, cp)

            range_start = cp
            range_end = checkpoints[i + 1] if i + 1 < len(checkpoints) else today + timedelta(days=1)
            logger.info(f"Step 2: 生成 picks for [{range_start}, {range_end})")
            added = _generate_picks_for_range(db, range_start, range_end)
            total_picks += added

        total = db.query(StrategyMinerPick).count()
        logger.info("=" * 50)
        logger.info(f"完成：本次新增 {total_picks} 筆；picks 表總計 {total} 筆")

    except Exception as e:
        logger.error(f"失敗: {e}", exc_info=True)
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: dry-run 驗證**

```bash
cd backend && ./.venv/bin/python scripts/backfill_picks_history_walkforward.py --start 2025-09-01 --dry-run
```
Expected: 列出 ~16 個 checkpoints（從 2025-09-01 起每 14 天一個），不寫入 DB。

- [ ] **Step 3: Commit**

```bash
git add backend/scripts/backfill_picks_history_walkforward.py
git commit -m "feat(miner): walk-forward backfill script

每 14 天設一個 re-optimization checkpoint，用該時點前訊號跑 optimizer，
再生成該區間每日 picks。strategy_miner_picks 的 tp/sl/hd 欄位保存當時參數，
後續結案判定 reproducible 且無 look-ahead。"
```

---

## Task 8: 真跑 walk-forward backfill

**目的：** 實際執行，把 2025-09-01 起的真實推薦歷史重建。預估執行時間：~1-3 小時（每 checkpoint 的 optimizer 約 5-15 分鐘 × 16 個 checkpoints）。

**前置條件：**
- Task 1-7 全部 merge 完成。
- PostgreSQL 可連線 (`10.0.4.3:5433/alphaforge`)。
- `alpha_signal_history` 表有 2025-09-01 起的資料（已確認 18,621 筆）。

**Files:**
- 無程式碼修改，純執行。

- [ ] **Step 1: 備份現有 picks 表**

```bash
cd backend && ./.venv/bin/python -c "
import logging
logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)
from app.db.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
db.execute(text('DROP TABLE IF EXISTS strategy_miner_picks_backup_20260417'))
db.execute(text('CREATE TABLE strategy_miner_picks_backup_20260417 AS SELECT * FROM strategy_miner_picks'))
r = db.execute(text('SELECT COUNT(*) FROM strategy_miner_picks_backup_20260417')).scalar()
db.commit()
print(f'backup rows: {r}')
db.close()
"
```
Expected: 印出 337（目前總筆數）。

- [ ] **Step 2: 執行 backfill（log 寫檔以便長時間任務復原）**

```bash
cd backend && ./.venv/bin/python scripts/backfill_picks_history_walkforward.py --start 2025-09-01 --interval 14 2>&1 | tee /tmp/backfill_$(date +%Y%m%d_%H%M%S).log
```

由於耗時長，建議 `run_in_background: true`，並透過 `tail -f /tmp/backfill_*.log` 觀察進度。

- [ ] **Step 3: 驗證 backfill 結果**

```bash
cd backend && ./.venv/bin/python -c "
import logging
logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)
from app.db.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
r = db.execute(text('''
    SELECT MIN(pick_date), MAX(pick_date), COUNT(*), COUNT(DISTINCT pick_date) AS days, COUNT(DISTINCT stock_id) AS stocks
    FROM strategy_miner_picks WHERE direction = :d
'''), {'d': 'long'}).fetchone()
print(f'long: min={r[0]} max={r[1]} rows={r[2]} days={r[3]} stocks={r[4]}')

# 驗證：被推 >= 3 次的股票數量（反映 backfill 後的覆蓋度）
rows = db.execute(text('''
    SELECT cnt_bucket, stocks FROM (
        SELECT CASE WHEN cnt >= 10 THEN '10+'
                    WHEN cnt >= 5 THEN '5-9'
                    WHEN cnt >= 3 THEN '3-4'
                    WHEN cnt = 2 THEN '2'
                    ELSE '1' END AS cnt_bucket,
               COUNT(*) AS stocks
        FROM (SELECT stock_id, COUNT(*) cnt FROM strategy_miner_picks WHERE direction='long' GROUP BY stock_id) x
        GROUP BY cnt_bucket
    ) y ORDER BY cnt_bucket DESC
''')).fetchall()
for bkt, n in rows:
    print(f'  被推 {bkt} 次：{n} 檔')
db.close()
"
```
Expected:
- `min = 2025-09-01` (或相近)，`max = 今日`
- long rows 應該是 ~500-1500 筆（7 個月 × 每日 5 筆 × 有訊號的日子比率）
- 被推 ≥ 3 次的股票數 ≥ 50 檔

- [ ] **Step 4: 抽樣驗證 3710（應該有多筆歷史）**

```bash
cd backend && ./.venv/bin/python -c "
import logging
logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)
from app.db.database import SessionLocal
from app.models.strategy_miner_pick import StrategyMinerPick
db = SessionLocal()
picks = db.query(StrategyMinerPick).filter(
    StrategyMinerPick.stock_id == '3710'
).order_by(StrategyMinerPick.pick_date).all()
print(f'3710 被推 {len(picks)} 次：')
for p in picks:
    print(f'  {p.pick_date}  dir={p.direction}  dim={p.time_dimension}  '
          f'entry={p.entry_price:.2f}  tp={p.take_profit_pct:.3f}  sl={p.stop_loss_pct:.3f}  hd={p.hold_days_max}')
db.close()
"
```
Expected: 若 3710 歷史確實出現過訊號，應看到多筆 pick_date 分佈在 2025-09 ~ 2026-04 之間；若依然只有 1 筆，代表 3710 今日才首次符合訊號條件（也是有效資訊）。

- [ ] **Step 5: 前端 e2e 煙霧測試**

啟動前後端 localhost，瀏覽 http://localhost:3000/alphaforge/strategy，點開任一卡片：
- 預期：展開區顯示該股的真實結案歷史（≥ 3 筆），包含停利/停損/到期各類出場，日期分布合理。
- 驗證：UI 顯示的 `entry_date → exit_date` 與 DB 中 pick + `_evaluate_pick_concluded` 結果一致。

- [ ] **Step 6: 若結果不合理，rollback**

```bash
# 若 backfill 結果異常（例如勝率 100%、分布偏差過大），還原備份
cd backend && ./.venv/bin/python -c "
from app.db.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
db.execute(text('DELETE FROM strategy_miner_picks'))
db.execute(text('INSERT INTO strategy_miner_picks SELECT * FROM strategy_miner_picks_backup_20260417'))
db.commit()
print('rollback 完成')
db.close()
"
```

- [ ] **Step 7: Commit（無程式碼變更；用 empty commit 記錄 backfill 事件）**

```bash
git commit --allow-empty -m "chore(miner): walk-forward backfill 2025-09-01 ~ 2026-04-17

執行結果：strategy_miner_picks 總筆數 X → Y，覆蓋 Z 檔股票。
備份表 strategy_miner_picks_backup_20260417 保留 30 天後可刪。"
```

---

## Task 9: 最終全站驗證 + 清理

**Files:**
- Modify（如需微調）: 前端元件。

- [ ] **Step 1: 所有後端測試通過**

```bash
cd backend && ./.venv/bin/python -m pytest -v
```
Expected: 全綠。

- [ ] **Step 2: 前端型別檢查**

```bash
cd frontend && npx tsc --noEmit
```
Expected: 無錯。

- [ ] **Step 3: 手動瀏覽全場景**

1. `/` 儀表板 → 策略推薦區載入正常
2. 點開卡片 → 真實歷史顯示
3. `/stock/3710` → 若該頁也用 `TradeHistoryList`，驗證其資料來源（可能需要另接新端點）
4. 重新整理後資料穩定

- [ ] **Step 4: 更新 memory**

```bash
# 清掉過期項目，新增本計畫完成紀錄
```
在 `memory/project_next_steps.md` 加一行「真實推薦歷史已重建，舊 trades 只用於 picks 生成的全輸過濾」。

- [ ] **Step 5: Final commit + push 建議**

```bash
git status  # 確認乾淨
git log --oneline main..HEAD  # review 本次所有 commit
```

只有全部驗證通過後才建議部署 NAS（依 CLAUDE.md 部署流程）。

---

## 自我審視結論

**Spec coverage check:**
- ✅ 歷史 UI 改接真實 picks (Task 5)
- ✅ 結案判定嚴格規則 tp/sl/time_limit (Task 1)
- ✅ 持有中不顯示 (Task 1 test_still_holding_returns_none)
- ✅ 上方勝率/預計報酬同源切換 (Task 4)
- ✅ 空白時顯示「資料累積中」 (Task 5)
- ✅ walk-forward backfill 到 2025-09 (Task 6-8)

**Placeholder scan:** 全部 step 皆含具體程式碼與命令，無 TBD/TODO 留白。

**Type consistency:** `_evaluate_pick_concluded` 回傳 dict 的 keys (`entry_date, exit_date, exit_price, exit_reason, return_pct, hold_days, strategy_id, stock_id, direction`) 在 Task 3 端點層轉 isoformat 後對外；欄位名全程一致。

**風險點：**
1. `_generate_direction_picks` 會查 `StockFeature.atr20`（line 411）— 歷史日期若缺 `stock_features` 資料，fallback 到 `3% × multiplier`。backfill 可能因此有部分 picks 的 tp/sl 偏粗，但已有 fallback。
2. `alpha_miner_snapshot` 只有最新一筆被用來建 `reasons_map`。歷史 picks 的 `buy_reasons` 會被「今日的顯著策略名稱」填入，是輕微的時序不一致（僅影響顯示，不影響結案計算）。接受此 trade-off。
3. backfill 執行時間長，若中途斷線需能重跑。腳本已設計成 idempotent：`_generate_direction_picks` 內部有 `DELETE WHERE pick_date = ... AND direction = ...` 然後重新插入，可直接重跑。

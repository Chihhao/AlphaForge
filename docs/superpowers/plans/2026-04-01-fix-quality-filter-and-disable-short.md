# 修正品質過濾 + 關閉做空推薦 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修正品質過濾改用相對指標（超額勝率），並關閉做空推薦，解決空頭市場做多全滅只剩做空的問題。

**Architecture:** 後端兩處改動：(1) `strategy_miner.py` endpoint 的品質過濾改用市場基準相對門檻 + 最低樣本數；(2) `strategy_miner_service.py` 和 `scheduler.py` 停止產生 short picks/signals。前端不改。

**Tech Stack:** Python / FastAPI / SQLAlchemy / PostgreSQL

---

### Task 1: 新增 `_load_market_baselines()` 函式

**Files:**
- Modify: `backend/app/api/endpoints/strategy_miner.py:1-19` (imports)
- Modify: `backend/app/api/endpoints/strategy_miner.py:63` (新增函式，插在 `_load_buy_reasons_fallback` 之前)

- [ ] **Step 1: 新增 import**

在 `backend/app/api/endpoints/strategy_miner.py` 頂部 imports 區加入 `AlphaMinerSnapshot`：

```python
from app.models.alpha_miner_snapshot import AlphaMinerSnapshot
```

- [ ] **Step 2: 新增 `_load_market_baselines()` 函式**

在 `_load_stock_perf_map()` 函式之後（`_load_buy_reasons_fallback()` 之前）插入：

```python
def _load_market_baselines(db: Session) -> dict:
    """從 Alpha Miner snapshot 取各維度市場基準勝率。
    回傳 {'5d': 0.194, '10d': 0.244, '30d': 0.261}"""
    snap = (
        db.query(AlphaMinerSnapshot)
        .order_by(AlphaMinerSnapshot.train_date.desc())
        .first()
    )
    if not snap:
        return {}
    result_data = json.loads(snap.result_json)
    dim_rates: dict = defaultdict(list)
    for s in result_data.get('strategies', []):
        dim = s['time_dimension'].replace('_short', '')
        mwr = s.get('market_win_rate')
        if mwr is not None:
            dim_rates[dim].append(mwr)
    baselines = {}
    for dim, rates in dim_rates.items():
        rates.sort()
        baselines[dim] = rates[len(rates) // 2]
    return baselines
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/api/endpoints/strategy_miner.py
git commit -m "feat: 新增 _load_market_baselines() 從 snapshot 取各維度市場基準"
```

---

### Task 2: 修改 `get_today_picks()` 過濾邏輯

**Files:**
- Modify: `backend/app/api/endpoints/strategy_miner.py:166-213`

- [ ] **Step 1: 載入 baselines 並移除 short 相關邏輯**

將 `get_today_picks()` 函式修改為：

```python
@router.get("/picks/today")
def get_today_picks(db: Session = Depends(get_db)):
    """今日推薦清單（含停利停損參數 + 個股回測績效 + 買入理由）"""
    import json as _json
    picks = StrategyMinerService.get_today_picks(db)
    stock_ids = [p.stock_id for p in picks]
    stock_perf = _load_stock_perf_map(db, stock_ids, direction='long')
    baselines = _load_market_baselines(db)

    # 優先使用 DB 儲存的 buy_reasons；若為 null（舊資料），使用 fallback 近似值
    any_missing = any(p.buy_reasons is None for p in picks)
    live_reasons: dict = _load_buy_reasons_fallback(db, picks) if any_missing else {}

    result = []
    for p in picks:
        perf = stock_perf.get(p.stock_id, {
            "stock_win_rate": None,
            "stock_avg_return": None,
            "stock_trade_count": 0,
            "stock_best_dim": None,
        })
        # 品質過濾：相對門檻 + 最低樣本數
        trade_count = perf.get("stock_trade_count", 0)
        if trade_count < 10:
            perf["stock_win_rate"] = None
            perf["stock_avg_return"] = None
        else:
            dim = (p.time_dimension or '10d').replace('_short', '')
            baseline = baselines.get(dim, 0.25)
            wr = perf.get("stock_win_rate")
            avg = perf.get("stock_avg_return")
            if wr is not None and wr <= baseline + 0.05:
                continue
            if avg is not None and avg < 0:
                continue

        result.append({
            "pick_date": p.pick_date.isoformat(),
            "stock_id": p.stock_id,
            "stock_name": p.stock_name,
            "strategy_ids": p.strategy_ids,
            "weighted_score": p.weighted_score,
            "entry_price": p.entry_price,
            "take_profit_pct": p.take_profit_pct,
            "stop_loss_pct": p.stop_loss_pct,
            "hold_days_max": p.hold_days_max,
            "time_dimension": p.time_dimension,
            "direction": getattr(p, 'direction', 'long') or 'long',
            "buy_reasons": (
                _json.loads(p.buy_reasons) if p.buy_reasons
                else live_reasons.get(p.stock_id, [])
            ),
            **perf,
        })
    return result
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/api/endpoints/strategy_miner.py
git commit -m "fix: picks/today 品質過濾改用相對門檻（超額勝率 > baseline+5pp）"
```

---

### Task 3: 修改 `get_picks_history()` 過濾邏輯

**Files:**
- Modify: `backend/app/api/endpoints/strategy_miner.py:499-529`

- [ ] **Step 1: 套用相同的相對過濾邏輯**

將 `get_picks_history()` 修改為：

```python
@router.get("/picks/history")
def get_picks_history(days: int = 7, db: Session = Depends(get_db)):
    """過去 N 天的推薦記錄（含個股回測績效）"""
    picks = StrategyMinerService.get_picks_history(db, days=days)
    stock_ids = [p.stock_id for p in picks]
    stock_perf = _load_stock_perf_map(db, stock_ids, direction='long')
    baselines = _load_market_baselines(db)

    result = []
    for p in picks:
        perf = stock_perf.get(p.stock_id, {
            "stock_win_rate": None,
            "stock_avg_return": None,
            "stock_trade_count": 0,
        })
        trade_count = perf.get("stock_trade_count", 0)
        if trade_count < 10:
            perf["stock_win_rate"] = None
            perf["stock_avg_return"] = None
        else:
            dim = (p.time_dimension or '10d').replace('_short', '')
            baseline = baselines.get(dim, 0.25)
            wr = perf.get("stock_win_rate")
            avg = perf.get("stock_avg_return")
            if wr is not None and wr <= baseline + 0.05:
                continue
            if avg is not None and avg < 0:
                continue

        result.append({
            "pick_date": p.pick_date.isoformat(),
            "stock_id": p.stock_id,
            "stock_name": p.stock_name,
            "weighted_score": p.weighted_score,
            "entry_price": p.entry_price,
            "hold_days_max": p.hold_days_max,
            "time_dimension": p.time_dimension,
            "direction": getattr(p, 'direction', 'long') or 'long',
            **perf,
        })
    return result
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/api/endpoints/strategy_miner.py
git commit -m "fix: picks/history 品質過濾改用相對門檻，與 picks/today 一致"
```

---

### Task 4: Strategy Miner 關閉做空 picks 產生

**Files:**
- Modify: `backend/app/services/strategy_miner_service.py:100-108`

- [ ] **Step 1: `run_daily()` 只產生做多 picks**

將 `run_daily()` 中的迴圈：

```python
        count = 0
        for direction in ('long', 'short'):
            n = cls._generate_direction_picks(db, latest_date, pick_date, direction)
            count += n
```

改為：

```python
        count = cls._generate_direction_picks(db, latest_date, pick_date, 'long')
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/services/strategy_miner_service.py
git commit -m "fix: Strategy Miner 關閉做空推薦（整體做空策略虧損）"
```

---

### Task 5: Scheduler 關閉做空訊號儲存

**Files:**
- Modify: `backend/app/core/scheduler.py:203-213` (第六梯次)
- Modify: `backend/app/core/scheduler.py:271-273` (retry 區塊)

- [ ] **Step 1: 第六梯次只存 long 訊號**

將 scheduler.py 第六梯次的 lambda：

```python
    scheduler.add_job(
        lambda: run_on_trading_day(lambda db: [
            AlphaMinerService.save_today_signals(db, dim, direction)
            for dim in ["5d", "10d", "30d"]
            for direction in ["long", "short"]
        ]),
        trigger=CronTrigger(day_of_week='mon-fri', hour=18, minute=10),
        id="save_signal_history",
        name="Save today alpha signals to history (long + short)",
        replace_existing=True
    )
```

改為：

```python
    scheduler.add_job(
        lambda: run_on_trading_day(lambda db: [
            AlphaMinerService.save_today_signals(db, dim, 'long')
            for dim in ["5d", "10d", "30d"]
        ]),
        trigger=CronTrigger(day_of_week='mon-fri', hour=18, minute=10),
        id="save_signal_history",
        name="Save today alpha signals to history (long only)",
        replace_existing=True
    )
```

- [ ] **Step 2: retry 區塊同步修改**

將 retry 區塊的：

```python
            for dim in ["5d", "10d", "30d"]:
                for direction in ["long", "short"]:
                    AlphaMinerService.save_today_signals(db, dim, direction)
```

改為：

```python
            for dim in ["5d", "10d", "30d"]:
                AlphaMinerService.save_today_signals(db, dim, 'long')
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/core/scheduler.py
git commit -m "fix: 排程器關閉做空訊號儲存，只保留做多"
```

---

### Task 6: 驗證

- [ ] **Step 1: 啟動本地後端並測試 API**

```bash
cd backend && ./.venv/bin/python main.py
```

- [ ] **Step 2: 驗證 picks/today 回傳做多推薦**

```bash
curl -s http://localhost:8000/strategy-miner/picks/today | python3 -m json.tool
```

預期：
- 回傳的 picks 全部 `direction: "long"`
- 不應有 `direction: "short"` 的 picks
- 如果有做多 picks 通過新的相對門檻，應該看到它們（如高力、大量）
- `stock_trade_count < 10` 的 picks，`stock_win_rate` 和 `stock_avg_return` 應為 `null`

- [ ] **Step 3: 驗證 picks/history 一致**

```bash
curl -s "http://localhost:8000/strategy-miner/picks/history?days=7" | python3 -m json.tool
```

預期：歷史 picks 中，做多的應通過相對門檻顯示；做空的歷史仍在（DB 已存的資料不刪）。

- [ ] **Step 4: Commit 最終狀態（如有修正）**

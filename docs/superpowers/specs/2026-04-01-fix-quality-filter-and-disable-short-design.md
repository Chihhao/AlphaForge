# 修正品質過濾 + 關閉做空推薦

**日期：** 2026-04-01
**狀態：** 設計確認

## 問題

Alpha Miner 測試窗口（2025-09 ~ 2026-03）處於空頭，市場基準勝率僅 24%（正常 ~50%）。做多策略的超額報酬仍有 +15.9pp，但絕對勝率 < 50%，被 endpoint 品質過濾全數刪除。結果頁面只剩做空推薦（整體虧損策略 + 小樣本倖存者偏差）。

### 因果鏈

```
固定測試窗口碰上空頭
  → 做多絕對勝率最高 42.9%（市場基準 27%，超額 +15.9pp）
  → endpoint 用絕對 50% 門檻過濾 → 做多全滅
  → 做空策略整體虧損（Sharpe 全負），但個別股票有小樣本好運
  → 頁面只顯示做空推薦，誤導用戶
```

## 改動範圍

### P0-A：品質過濾改用相對指標

**檔案：** `backend/app/api/endpoints/strategy_miner.py`

#### 1. 取得市場基準

在 `get_today_picks()` 和 `get_picks_history()` 中，從 Alpha Miner snapshot 讀取各維度 `market_win_rate` 中位數作為基準。

```python
def _load_market_baselines(db: Session) -> dict[str, float]:
    """從 Alpha Miner snapshot 取各維度市場基準勝率。
    回傳 {'5d': 0.194, '10d': 0.244, '30d': 0.261}"""
    snap = db.query(AlphaMinerSnapshot).order_by(
        AlphaMinerSnapshot.train_date.desc()
    ).first()
    if not snap:
        return {}
    result_data = json.loads(snap.result_json)
    from collections import defaultdict
    dim_rates = defaultdict(list)
    for s in result_data.get('strategies', []):
        dim = s['time_dimension'].replace('_short', '')
        mwr = s.get('market_win_rate')
        if mwr is not None:
            dim_rates[dim].append(mwr)
    baselines = {}
    for dim, rates in dim_rates.items():
        rates.sort()
        baselines[dim] = rates[len(rates) // 2]  # 中位數
    return baselines
```

#### 2. 過濾邏輯改動

現行（絕對門檻）：
```python
if perf.get("stock_avg_return") is not None and perf["stock_avg_return"] < 1.0:
    continue
if perf.get("stock_win_rate") is not None and perf["stock_win_rate"] <= 0.5:
    continue
```

改為（相對門檻 + 最低樣本數）：
```python
trade_count = perf.get("stock_trade_count", 0)
if trade_count < 10:
    # 樣本不足：保留 pick，但不顯示勝率/報酬（設為 null）
    perf["stock_win_rate"] = None
    perf["stock_avg_return"] = None
else:
    dim = p.time_dimension or '10d'
    baseline = baselines.get(dim, 0.25)
    if perf["stock_win_rate"] <= baseline + 0.05:
        continue  # 超額勝率 < 5pp
    if perf["stock_avg_return"] < 0:
        continue  # 平均報酬為負
```

#### 3. 影響範圍

- `get_today_picks()`：加載 baselines，套用新過濾
- `get_picks_history()`：同上
- 前端不改：`stock_win_rate == null` 時已正確隱藏勝率區塊

### P0-C：關閉做空推薦

#### 1. Strategy Miner 不再產生做空 picks

**檔案：** `backend/app/services/strategy_miner_service.py` — `run_daily()`

```python
# 現在
for direction in ('long', 'short'):
    n = cls._generate_direction_picks(db, latest_date, pick_date, direction)

# 改為
n = cls._generate_direction_picks(db, latest_date, pick_date, 'long')
```

#### 2. Alpha Miner 不再存做空訊號

**檔案：** `backend/app/services/alpha_miner_service.py` — `save_today_signals()`

只存 long 方向的 `AlphaSignalHistory`。short 維度的訓練保留（未來復用），但不產生訊號。

#### 3. 前端不改

做空區塊已有 `picks.filter(p => p.direction === 'short').length > 0` 守衛，DB 無 short picks 時自然隱藏。

## 不做的事

- **不改 Alpha Miner 訓練邏輯** — short 維度繼續訓練（資料保留），只是不推薦
- **不改前端** — 後端修正後前端自動適應
- **不做 Walk-Forward** — 列為 P1 後續項目

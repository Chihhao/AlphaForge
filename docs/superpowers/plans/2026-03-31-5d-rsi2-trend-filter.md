# 5D RSI(2) + 趨勢過濾器 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 RSI(2) 極短期反轉因子 + Alpha Miner 趨勢過濾器（close > MA60），提升 5d 策略勝率。

**Architecture:** 在 feature pipeline 中新增 RSI(2) 計算和存儲，在 Alpha Miner 訓練層加入 MA60 趨勢過濾，讓模型只學習順勢環境的訊號。最後透過輕量 backfill 腳本回補歷史資料。

**Tech Stack:** Python, Pandas, SQLAlchemy, PostgreSQL, scikit-learn

**Spec:** `docs/superpowers/specs/2026-03-31-5d-rsi2-trend-filter-design.md`

---

### Task 1: DB Migration — 新增 rsi2 欄位

**Files:**
- 無檔案建立或修改，直接對 NAS PostgreSQL 執行 DDL

- [ ] **Step 1: 執行 migration**

```bash
cd /Users/chihhaolai/Documents/GitHub/AlphaForge/backend
./.venv/bin/python -c "
from sqlalchemy import text
from app.db.database import engine
with engine.connect() as conn:
    conn.execute(text('ALTER TABLE stock_features ADD COLUMN IF NOT EXISTS rsi2 FLOAT'))
    conn.commit()
    print('OK: rsi2 column added')
"
```

Expected: `OK: rsi2 column added`

- [ ] **Step 2: 驗證欄位存在**

```bash
./.venv/bin/python -c "
from sqlalchemy import text
from app.db.database import engine
with engine.connect() as conn:
    cols = conn.execute(text(\"SELECT column_name FROM information_schema.columns WHERE table_name='stock_features' AND column_name='rsi2'\")).fetchall()
    print(f'rsi2 exists: {len(cols) > 0}')
"
```

Expected: `rsi2 exists: True`

- [ ] **Step 3: Commit**

```bash
git add -A && git commit -m "chore: DB migration — add rsi2 column to stock_features"
```

---

### Task 2: Model — StockFeature 加入 rsi2

**Files:**
- Modify: `backend/app/models/stock_feature.py:33` (rsi14 附近)

- [ ] **Step 1: 在 rsi14 之後新增 rsi2 欄位**

在 `backend/app/models/stock_feature.py` 的 `rsi14 = Column(Float)` 之後加入：

```python
    rsi2 = Column(Float, nullable=True)     # 2期 RSI（極短期超賣/超買）
```

- [ ] **Step 2: 跑測試確認無破壞**

```bash
cd /Users/chihhaolai/Documents/GitHub/AlphaForge/backend && ./.venv/bin/python -m pytest -x -q 2>&1 | tail -5
```

Expected: all tests pass

- [ ] **Step 3: Commit**

```bash
git add backend/app/models/stock_feature.py && git commit -m "feat: add rsi2 column to StockFeature model"
```

---

### Task 3: Feature Pipeline — 計算 RSI(2) 並寫入 DB

**Files:**
- Modify: `backend/app/services/feature_service.py:76` (rsi14 計算附近)
- Modify: `backend/app/services/feature_service.py:191` (compute_daily 寫入)
- Modify: `backend/app/services/feature_service.py:270` (compute_batch 計算)
- Modify: `backend/app/services/feature_service.py:427` (compute_batch 寫入)

- [ ] **Step 1: compute_daily — 加入 RSI(2) 計算**

在 `feature_service.py` 約 line 76（`df['bias10']` 計算之後，`df['vol_ma5']` 之前）加入：

```python
        df['rsi2'] = IndicatorService.calculate_rsi_vec(df, 2)
```

- [ ] **Step 2: compute_daily — 加入 RSI(2) 寫入**

在 `feature_service.py` 約 line 191（`rsi14=_safe_float(row.get('rsi14')),` 之後）加入：

```python
                rsi2=_safe_float(row.get('rsi2')),
```

- [ ] **Step 3: compute_batch — 加入 RSI(2) 計算**

在 `feature_service.py` 約 line 272（`df['bias10']` 計算之後）加入：

```python
        df['rsi2'] = IndicatorService.calculate_rsi_vec(df, 2)
```

- [ ] **Step 4: compute_batch — 加入 RSI(2) 寫入**

在 `feature_service.py` 約 line 427（`rsi14=_safe_float(row.get('rsi14')),` 之後）加入：

```python
                    rsi2=_safe_float(row.get('rsi2')),
```

- [ ] **Step 5: 跑測試**

```bash
cd /Users/chihhaolai/Documents/GitHub/AlphaForge/backend && ./.venv/bin/python -m pytest -x -q 2>&1 | tail -5
```

Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/feature_service.py && git commit -m "feat: compute RSI(2) in feature pipeline (daily + batch)"
```

---

### Task 4: Alpha Miner — RSI(2) 因子 + MA60 趨勢過濾

**Files:**
- Modify: `backend/app/services/alpha_miner_service.py:42` (FACTOR_LABELS)
- Modify: `backend/app/services/alpha_miner_service.py:84` (FACTOR_COMBINATIONS)
- Modify: `backend/app/services/alpha_miner_service.py:165` (_LOAD_COLS)
- Modify: `backend/app/services/alpha_miner_service.py:638-641` (_train_one train/test split)

- [ ] **Step 1: FACTOR_LABELS 新增 rsi2**

在 `alpha_miner_service.py` 的 `FACTOR_LABELS` dict 中，`'rsi14': 'RSI'` 之後加入：

```python
    'rsi2':            'RSI(2)',
```

- [ ] **Step 2: FACTOR_COMBINATIONS 新增 6 組**

在 `FACTOR_COMBINATIONS` 列表尾端（`['trust_buy_20d', 'sector_rs']` 之後）加入：

```python
    # Phase 8 — RSI(2) 極短期反轉
    ['rsi2'],
    ['rsi2', 'vol_ratio'],
    ['rsi2', 'pb_ratio'],
    ['rsi2', 'foreign_buy_5d'],
    ['rsi2', 'bias10'],
    ['rsi2', 'bias10', 'vol_ratio'],
```

- [ ] **Step 3: _LOAD_COLS 加入 ma60**

將 `_LOAD_COLS` 從：

```python
_LOAD_COLS = ['stock_id', 'date', 'close'] + list(FACTOR_LABELS.keys())
```

改為：

```python
_LOAD_COLS = ['stock_id', 'date', 'close', 'ma60'] + list(FACTOR_LABELS.keys())
```

- [ ] **Step 4: _train_one 加入趨勢過濾**

在 `_train_one` 方法中，現有的 train/test split（約 line 638-641）之後、樣本數檢查（`if len(train_df) < 100`）之前，加入：

```python
        # 趨勢過濾：做多只用上升趨勢樣本，做空只用下降趨勢樣本
        dim_direction = dim.get('direction', 'long')
        if 'ma60' in df.columns:
            if dim_direction == 'long':
                train_df = train_df[train_df['close'] > train_df['ma60']].copy()
                test_df = test_df[test_df['close'] > test_df['ma60']].copy()
            else:
                train_df = train_df[train_df['close'] < train_df['ma60']].copy()
                test_df = test_df[test_df['close'] < test_df['ma60']].copy()
```

注意：放在 `dropna` 之後、`if len(train_df) < 100` 之前。完整上下文：

```python
        train_df = df[df['date'] <= pd.Timestamp(train_end)].dropna(
            subset=rank_cols + ['label'])
        test_df = df[df['date'] >= pd.Timestamp(test_start)].dropna(
            subset=rank_cols + ['label', 'forward_return'])

        # 趨勢過濾：做多只用上升趨勢樣本，做空只用下降趨勢樣本
        dim_direction = dim.get('direction', 'long')
        if 'ma60' in df.columns:
            if dim_direction == 'long':
                train_df = train_df[train_df['close'] > train_df['ma60']].copy()
                test_df = test_df[test_df['close'] > test_df['ma60']].copy()
            else:
                train_df = train_df[train_df['close'] < train_df['ma60']].copy()
                test_df = test_df[test_df['close'] < test_df['ma60']].copy()

        if len(train_df) < 100 or len(test_df) < 30:
            return None, None
```

- [ ] **Step 5: 跑測試**

```bash
cd /Users/chihhaolai/Documents/GitHub/AlphaForge/backend && ./.venv/bin/python -m pytest -x -q 2>&1 | tail -5
```

Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/alpha_miner_service.py && git commit -m "feat: RSI(2) factor combos + MA60 trend filter in Alpha Miner"
```

---

### Task 5: Backfill 腳本 — 回補 RSI(2) 歷史資料

**Files:**
- Create: `backend/scripts/backfill_rsi2.py`

- [ ] **Step 1: 建立 backfill 腳本**

```python
"""
backfill_rsi2.py — 輕量回補 RSI(2) 至 stock_features 表
只更新 rsi2 IS NULL 的記錄，不重跑整個 feature pipeline。
"""
from __future__ import annotations
import logging, sys, os
import numpy as np, pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)


def main():
    from app.db.database import engine
    from sqlalchemy import text

    logger.info("=== RSI(2) 回補開始 ===")

    # 1. 找出需要回補的日期範圍
    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT MIN(date), MAX(date), COUNT(*) FROM stock_features WHERE rsi2 IS NULL"
        )).fetchone()
        null_min, null_max, null_count = row
        logger.info(f"待回補: {null_count:,} 筆 ({null_min} ~ {null_max})")

        if null_count == 0:
            logger.info("無需回補")
            return

    # 2. 讀取所有 stock_prices 的 close（含暖機期）
    with engine.connect() as conn:
        warmup_start = (pd.Timestamp(null_min) - pd.DateOffset(days=30)).strftime('%Y-%m-%d')
        df = pd.read_sql(text(
            "SELECT stock_id, date, close FROM stock_prices WHERE date >= :start ORDER BY stock_id, date"
        ), conn, params={"start": warmup_start})

    logger.info(f"讀取 stock_prices: {len(df):,} 筆")
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values(['stock_id', 'date'])

    # 3. 向量化計算 RSI(2)
    def rsi_logic(s):
        delta = s.diff()
        up = delta.clip(lower=0)
        down = -1 * delta.clip(upper=0)
        ema_up = up.ewm(com=1, adjust=False).mean()   # com = window - 1 = 1
        ema_down = down.ewm(com=1, adjust=False).mean()
        rs = ema_up / ema_down
        return 100 - (100 / (1 + rs))

    df['rsi2'] = df.groupby('stock_id')['close'].transform(rsi_logic)

    # 4. 只保留需要更新的日期
    df = df[(df['date'] >= pd.Timestamp(null_min)) & (df['date'] <= pd.Timestamp(null_max))]
    df = df.dropna(subset=['rsi2'])
    logger.info(f"計算完成: {len(df):,} 筆待寫入")

    # 5. 批量 UPDATE
    batch_size = 5000
    updated = 0
    with engine.connect() as conn:
        for i in range(0, len(df), batch_size):
            batch = df.iloc[i:i+batch_size]
            for _, row in batch.iterrows():
                conn.execute(text(
                    "UPDATE stock_features SET rsi2 = :rsi2 "
                    "WHERE stock_id = :sid AND date = :dt AND rsi2 IS NULL"
                ), {"rsi2": float(row['rsi2']), "sid": row['stock_id'], "dt": row['date'].date()})
            conn.commit()
            updated += len(batch)
            logger.info(f"進度: {updated:,} / {len(df):,}")

    logger.info(f"=== RSI(2) 回補完成: {updated:,} 筆 ===")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 執行 backfill**

```bash
cd /Users/chihhaolai/Documents/GitHub/AlphaForge/backend && ./.venv/bin/python scripts/backfill_rsi2.py
```

Expected: 約 2-5 分鐘完成，更新 ~930,000 筆

- [ ] **Step 3: 驗證回補結果**

```bash
./.venv/bin/python -c "
from sqlalchemy import text
from app.db.database import engine
with engine.connect() as conn:
    total = conn.execute(text('SELECT COUNT(*) FROM stock_features')).scalar()
    filled = conn.execute(text('SELECT COUNT(*) FROM stock_features WHERE rsi2 IS NOT NULL')).scalar()
    null = total - filled
    print(f'total={total:,} rsi2_filled={filled:,} null={null:,} fill_rate={filled/total*100:.1f}%')
"
```

Expected: fill_rate > 60%（2024-04 以後的資料應全部填滿）

- [ ] **Step 4: Commit**

```bash
git add backend/scripts/backfill_rsi2.py && git commit -m "feat: add backfill_rsi2.py for lightweight RSI(2) backfill"
```

---

### Task 6: 驗證 — 重跑 Strategy Miner + 診斷

- [ ] **Step 1: 重跑 Strategy Miner**

```bash
cd /Users/chihhaolai/Documents/GitHub/AlphaForge/backend && ./.venv/bin/python scripts/backfill_strategy_miner.py
```

Expected: 約 60-90 秒完成，6 個維度各自產出最優參數

- [ ] **Step 2: 跑 5d 診斷對比改善**

```bash
cd /Users/chihhaolai/Documents/GitHub/AlphaForge/backend && ./.venv/bin/python scripts/diagnose_5d.py 2>&1 | grep -v "^[0-9]\{4\}-\|^INFO:\|^WARNING:\|ConstantInput\|^FROM \|^WHERE \|^SELECT "
```

**驗證標準：**
- 5d long 勝率（>0%）從 45.0% → 47%+
- 5d long vs 隨機差距從 +0.1pp → +3pp+
- 5d short 平均報酬收窄或轉正

- [ ] **Step 3: 跑全量診斷確認 10d/30d 沒有退步**

```bash
cd /Users/chihhaolai/Documents/GitHub/AlphaForge/backend && ./.venv/bin/python scripts/diagnose_alpha_quality.py 2>&1 | grep -E "策略勝率|差距|平均報酬"
```

Expected: 10d/30d 勝率維持或提升（趨勢過濾對所有維度都有正面效果）

###### tags: `專案`,`架構重構`,`strategy-miner`

# Per-Dimension Picks 架構 Implementation Plan

`文件版本: 2026-04-18a`

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `strategy_miner_picks` 從「每日每股每方向一筆融合結果」改成「每日每股每方向每維度獨立一筆」，讓 5d/10d/20d 三維度資料可獨立驗證、持續監控、歷史補滿。

**Architecture:** 核心改動是 (1) DB unique constraint 從 3 欄擴成 4 欄 `(pick_date, stock_id, direction, time_dimension)`；(2) `_generate_direction_picks` 不再融合多維、改為對每個 dim 獨立執行步驟 4-9；(3) 保留「多維共鳴」概念但轉移到 API 回傳時動態計算 `resonance_count` (同股當日在幾個 dim 出現)；(4) 前端 tab 語意由「primary 維度」變「該維度獨立推薦」，並加共鳴徽章視覺化。

**Tech Stack:** PostgreSQL (NAS 10.0.4.3:5433)、FastAPI、SQLAlchemy 2.0、Next.js 14、TypeScript。專案無 alembic，migration 寫 Python 一次性腳本。

---

## 影響範圍總覽

### 會修改的檔案

- `backend/app/models/strategy_miner_pick.py` — unique constraint
- `backend/app/services/strategy_miner_service.py` — `_generate_direction_picks` 重構、DELETE 條件、`_load_stock_perf_from_picks` 維持
- `backend/app/api/endpoints/strategy_miner.py` — `/picks/today`、`/picks/history` 加 `resonance_count`
- `backend/scripts/backfill_picks_history_walkforward.py` — 呼叫方式不變，內部 service 改完即可
- `frontend/components/StrategyMinerPreview.tsx` — 首頁 preview 加共鳴徽章
- `frontend/pages/strategy.tsx` — tab 語意轉為真獨立維度、加共鳴徽章

### 新增的檔案

- `backend/scripts/migrate_picks_v3_unique_key.py` — 一次性 migration: 備份、刪舊 constraint、建新 constraint
- `backend/scripts/rebuild_picks_per_dim.py` — 清空 picks 並用新架構重跑 9/1~4/17 walk-forward
- `backend/tests/services/test_strategy_miner_per_dim.py` — 單元測試新邏輯

### 不動

- `backend/app/core/scheduler.py` — 呼叫 `run_daily` 不變
- `_load_stock_perf_from_picks` — 內部 by-dim 分組邏輯已存在，新架構下更精確，程式不用改
- `strategy_miner_trades` (舊回測) — 只用於全輸過濾，不受影響

---

## 資料遷移策略

新舊架構資料不相容 (舊是融合、新是獨立)，無法「in-place 漸進遷移」。策略:

1. **備份**: 建立 `strategy_miner_picks_backup_20260418_pre_v3` 保留改動前全量
2. **清空**: 不嘗試轉換舊融合 picks (那些 pick 的 `time_dimension` 是 primary dim，不是真維度歸屬)
3. **重建**: 用新架構 + `rebuild_picks_per_dim.py` 跑 walk-forward 生出完整三維歷史

現有資料會暫時不可用約 1 小時 (rebuild 執行期間)。非交易時段執行不影響生產。

---

## Task 1: 備份現有 picks 表

**Files:**
- Modify (DB): 建立新備份表 `strategy_miner_picks_backup_20260418_pre_v3`

- [ ] **Step 1: 執行備份 SQL**

於 NAS container 執行:

```bash
ssh chihhaolai@10.0.4.3 "sudo /usr/local/bin/docker exec alphaforge-backend python -c \"
from app.db.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
db.execute(text('CREATE TABLE strategy_miner_picks_backup_20260418_pre_v3 AS SELECT * FROM strategy_miner_picks'))
db.commit()
cnt = db.execute(text('SELECT COUNT(*) FROM strategy_miner_picks_backup_20260418_pre_v3')).scalar()
print(f'backup rows: {cnt}')
db.close()
\""
```

- [ ] **Step 2: 驗證備份完整**

Expected output: `backup rows: 1875` (與原表同筆數)

- [ ] **Step 3: Commit (僅 plan 檔案，若有)**

```bash
git add docs/superpowers/plans/2026-04-18-per-dimension-picks-architecture.md
git commit -m "docs: Per-dimension picks 架構重構計畫"
```

---

## Task 2: 更新 Model Unique Constraint

**Files:**
- Modify: `backend/app/models/strategy_miner_pick.py`

- [ ] **Step 1: 寫失敗測試**

Create: `backend/tests/services/test_strategy_miner_per_dim.py`

```python
"""驗證 per-dimension picks 架構: 同股同天同方向可有多筆 (不同維度)。"""
import pytest
from datetime import date
from app.models.strategy_miner_pick import StrategyMinerPick
from app.db.database import SessionLocal


def test_same_stock_same_day_multiple_dims_allowed():
    """同 stock_id + pick_date + direction, 不同 time_dimension 應可共存。"""
    db = SessionLocal()
    try:
        db.query(StrategyMinerPick).filter(
            StrategyMinerPick.pick_date == date(2099, 1, 1),
            StrategyMinerPick.stock_id == 'TEST1',
        ).delete()
        db.commit()

        for dim in ('5d', '10d', '20d'):
            db.add(StrategyMinerPick(
                pick_date=date(2099, 1, 1),
                stock_id='TEST1',
                stock_name='測試股',
                strategy_ids='["' + dim + '"]',
                weighted_score=1.0,
                entry_price=100.0,
                take_profit_pct=0.05,
                stop_loss_pct=0.03,
                hold_days_max=int(dim[:-1]),
                time_dimension=dim,
                direction='long',
                buy_reasons='[]',
            ))
        db.commit()

        got = db.query(StrategyMinerPick).filter(
            StrategyMinerPick.pick_date == date(2099, 1, 1),
            StrategyMinerPick.stock_id == 'TEST1',
            StrategyMinerPick.direction == 'long',
        ).all()
        assert len(got) == 3, f"預期 3 筆 (三維度), 實際 {len(got)}"

        db.query(StrategyMinerPick).filter(
            StrategyMinerPick.pick_date == date(2099, 1, 1),
            StrategyMinerPick.stock_id == 'TEST1',
        ).delete()
        db.commit()
    finally:
        db.close()
```

- [ ] **Step 2: 跑測試驗證 FAIL**

```bash
cd backend && ./.venv/bin/python -m pytest tests/services/test_strategy_miner_per_dim.py::test_same_stock_same_day_multiple_dims_allowed -v
```

Expected: FAIL with `IntegrityError: duplicate key value violates unique constraint "uq_strategy_miner_pick_v2"` (因為舊 constraint 還在)

- [ ] **Step 3: 修改 model**

Modify `backend/app/models/strategy_miner_pick.py`:

Before:
```python
    __table_args__ = (
        UniqueConstraint('pick_date', 'stock_id', 'direction', name='uq_strategy_miner_pick_v2'),
    )
```

After:
```python
    __table_args__ = (
        UniqueConstraint(
            'pick_date', 'stock_id', 'direction', 'time_dimension',
            name='uq_strategy_miner_pick_v3',
        ),
    )
```

- [ ] **Step 4: 不要跑測試 (此時 DB 仍是舊 constraint)，進入 Task 3**

---

## Task 3: DB Migration — 切換 Unique Constraint

**Files:**
- Create: `backend/scripts/migrate_picks_v3_unique_key.py`

- [ ] **Step 1: 寫 migration 腳本**

Create `backend/scripts/migrate_picks_v3_unique_key.py`:

```python
"""Migration: strategy_miner_picks unique constraint v2 → v3

v2: (pick_date, stock_id, direction)                      — 融合架構
v3: (pick_date, stock_id, direction, time_dimension)      — per-dim 架構

先檢查是否有任何「同 pick_date+stock_id+direction 但 time_dimension 不同」
的潛在衝突 (應為 0，因舊 constraint 阻擋過)，再切換。
"""
from __future__ import annotations
import logging
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.db.database import SessionLocal

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

OLD_NAME = 'uq_strategy_miner_pick_v2'
NEW_NAME = 'uq_strategy_miner_pick_v3'


def main():
    db = SessionLocal()
    try:
        exists_old = db.execute(text(
            "SELECT 1 FROM pg_constraint WHERE conname = :n"
        ), {'n': OLD_NAME}).scalar()
        exists_new = db.execute(text(
            "SELECT 1 FROM pg_constraint WHERE conname = :n"
        ), {'n': NEW_NAME}).scalar()
        logger.info(f"old constraint {OLD_NAME}: {'exists' if exists_old else 'absent'}")
        logger.info(f"new constraint {NEW_NAME}: {'exists' if exists_new else 'absent'}")

        if exists_new:
            logger.info("v3 constraint already present, skipping")
            return

        if exists_old:
            logger.info(f"DROP CONSTRAINT {OLD_NAME}")
            db.execute(text(f'ALTER TABLE strategy_miner_picks DROP CONSTRAINT {OLD_NAME}'))

        logger.info(f"ADD CONSTRAINT {NEW_NAME}")
        db.execute(text(
            f'ALTER TABLE strategy_miner_picks ADD CONSTRAINT {NEW_NAME} '
            'UNIQUE (pick_date, stock_id, direction, time_dimension)'
        ))
        db.commit()
        logger.info("migration complete")
    except Exception as e:
        logger.error(f"failed: {e}", exc_info=True)
        db.rollback()
        sys.exit(1)
    finally:
        db.close()


if __name__ == '__main__':
    main()
```

- [ ] **Step 2: 於 NAS container 執行 migration**

```bash
# 先把腳本同步到 NAS (Synology Drive 自動同步, 等 1 分鐘; 或用 docker cp)
ssh chihhaolai@10.0.4.3 "sudo /usr/local/bin/docker exec alphaforge-backend python scripts/migrate_picks_v3_unique_key.py"
```

Expected output:
```
old constraint uq_strategy_miner_pick_v2: exists
new constraint uq_strategy_miner_pick_v3: absent
DROP CONSTRAINT uq_strategy_miner_pick_v2
ADD CONSTRAINT uq_strategy_miner_pick_v3
migration complete
```

- [ ] **Step 3: 驗證 constraint 切換成功**

```bash
ssh chihhaolai@10.0.4.3 "sudo /usr/local/bin/docker exec alphaforge-backend python -c \"
from app.db.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
r = db.execute(text(\\\"SELECT conname FROM pg_constraint WHERE conrelid='strategy_miner_picks'::regclass AND contype='u'\\\")).all()
for row in r: print(row[0])
db.close()
\""
```

Expected: 只有 `uq_strategy_miner_pick_v3`，沒有 v2。

- [ ] **Step 4: 跑 Task 2 的測試**

```bash
cd backend && ./.venv/bin/python -m pytest tests/services/test_strategy_miner_per_dim.py::test_same_stock_same_day_multiple_dims_allowed -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/strategy_miner_pick.py \
        backend/scripts/migrate_picks_v3_unique_key.py \
        backend/tests/services/test_strategy_miner_per_dim.py
git commit -m "feat(miner): unique constraint v2→v3 per-dimension"
```

---

## Task 4: 重構 `_generate_direction_picks` 為 Per-Dimension

**Files:**
- Modify: `backend/app/services/strategy_miner_service.py` (lines ~264-540, 方法 `_generate_direction_picks`)

這是最核心的重構。舊邏輯把三維合併成單一排序 (步驟 6)，新邏輯要對每個 dim 分別跑步驟 4-9。

- [ ] **Step 1: 先讀整個 `_generate_direction_picks` 方法理解舊邏輯**

```bash
cd backend && ./.venv/bin/python -c "
import inspect
from app.services.strategy_miner_service import StrategyMinerService
src = inspect.getsource(StrategyMinerService._generate_direction_picks)
print(src)
"
```

- [ ] **Step 2: 寫重構後單元測試**

Append to `backend/tests/services/test_strategy_miner_per_dim.py`:

```python
from unittest.mock import patch
from app.services.strategy_miner_service import StrategyMinerService


def test_generate_direction_picks_writes_per_dim(monkeypatch):
    """呼叫 _generate_direction_picks 應為每個有 signal 的 dim 寫入獨立 picks,
    不再 merge 出單一融合列表。"""
    db = SessionLocal()
    try:
        target_date = date(2099, 1, 2)
        db.query(StrategyMinerPick).filter(
            StrategyMinerPick.pick_date == target_date,
        ).delete()
        db.commit()

        StrategyMinerService._generate_direction_picks(
            db, target_date, target_date, 'long',
        )
        db.commit()

        rows = db.query(StrategyMinerPick).filter(
            StrategyMinerPick.pick_date == target_date,
        ).all()
        dims = {r.time_dimension for r in rows}
        assert dims.issubset({'5d', '10d', '20d'})
        for r in rows:
            import json as _json
            assert r.time_dimension in _json.loads(r.strategy_ids)

        db.query(StrategyMinerPick).filter(
            StrategyMinerPick.pick_date == target_date,
        ).delete()
        db.commit()
    finally:
        db.close()
```

注意: 此測試在沒有 2099-01-02 signal 時會回傳空結果，算 PASS。它的價值是防止 regression (未來跑 run_daily 不崩)。

- [ ] **Step 3: 重構 `_generate_direction_picks`**

修改重點 (不需重寫整個函式，依以下 diff 規則改):

**(a) 步驟 6 從「跨維度 combined」改為「per-dim sorted」**

Before (lines ~389-409):
```python
        # 6. 合併：多維共鳴加分 10%/維度
        combined: Dict[str, dict] = {}
        for dim, dim_map in by_dim.items():
            for stock_id, r in dim_map.items():
                base_score = r.trigger_count * (r.weighted_odds_ratio or 1.0)
                if stock_id not in combined:
                    combined[stock_id] = {
                        'primary': r,
                        'dims': [dim],
                        'score': base_score,
                    }
                else:
                    combined[stock_id]['dims'].append(dim)
                    if base_score > combined[stock_id]['score']:
                        combined[stock_id]['primary'] = r
                        combined[stock_id]['score'] = base_score
                    combined[stock_id]['score'] *= 1.10

        sorted_combined = sorted(
            combined.values(), key=lambda x: x['score'], reverse=True,
        )
```

After:
```python
        # 6. per-dimension sort (每維度獨立 Top5, 不再跨維度 merge)
        #    共鳴資訊由 API 回傳層動態計算 (同 pick_date+stock_id+direction 有幾筆)
        per_dim_sorted: Dict[str, list] = {}
        for dim, dim_map in by_dim.items():
            items = [
                {
                    'primary': r,
                    'dims': [dim],
                    'score': r.trigger_count * (r.weighted_odds_ratio or 1.0),
                }
                for r in dim_map.values()
            ]
            per_dim_sorted[dim] = sorted(items, key=lambda x: x['score'], reverse=True)
```

**(b) 步驟 6.5 全輸過濾 + 步驟 7 理由建立 + 步驟 8-9 寫入：全部移到每個 dim 的迴圈內**

Before (lines ~411-540, 一次跑完整 sorted_combined):
```python
        # 6.5 全輸過濾
        candidate_ids = [item['primary'].stock_id for item in sorted_combined]
        perf_map = _load_stock_perf_from_picks(db, candidate_ids, direction=direction)
        filtered_combined = []
        for item in sorted_combined:
            ...
            filtered_combined.append(item)
            if len(filtered_combined) >= max_picks:
                break
        sorted_combined = filtered_combined

        # 7. 理由 map (沿用原 snippet 全部)
        reasons_map: Dict[str, List[str]] = {}
        ...

        # 8. 刪除今日已有的同方向 picks
        db.execute(
            delete(StrategyMinerPick).where(
                StrategyMinerPick.pick_date == pick_date,
                StrategyMinerPick.direction == direction,
            )
        )

        # 9. 寫入 picks
        count = 0
        for item in sorted_combined:
            ...
        return count
```

After:
```python
        # 6.5 理由 map 建立 (只做一次, 與 dim 無關)
        reasons_map: Dict[str, List[str]] = {}
        try:
            snap = (
                db.query(AlphaMinerSnapshot)
                .order_by(AlphaMinerSnapshot.train_date.desc())
                .first()
            )
            if snap:
                # (保留原本的 reasons_map 建立邏輯, lines ~438-471)
                ...
        except Exception as e:
            logger.warning(f"[StrategyMiner] {dir_label}理由建立失敗: {e}")

        # 7. 刪除今日所有三維度同方向 picks (整批覆寫, 避免殘留歷史)
        db.execute(
            delete(StrategyMinerPick).where(
                StrategyMinerPick.pick_date == pick_date,
                StrategyMinerPick.direction == direction,
            )
        )

        # 8. 對每個 dim 獨立做全輸過濾 + Top5 寫入
        total_count = 0
        for dim, sorted_items in per_dim_sorted.items():
            # 8a. 全輸過濾 (per-dim, 只看該 dim 的歷史)
            candidate_ids = [item['primary'].stock_id for item in sorted_items]
            perf_map = _load_stock_perf_from_picks(db, candidate_ids, direction=direction)
            filtered = []
            for item in sorted_items:
                sid = item['primary'].stock_id
                perf = perf_map.get(sid)
                if perf is not None:
                    raw_count = perf.get('stock_trade_count') or 0
                    raw_avg = perf.get('stock_avg_return')
                    if raw_count > 0 and raw_avg is not None and raw_avg < 0:
                        logger.info(
                            f"[StrategyMiner] {dir_label}/{dim} skip {sid} "
                            f"(歷史 {raw_count} 筆平均 {raw_avg:.2f}% < 0)"
                        )
                        continue
                filtered.append(item)
                if len(filtered) >= max_picks:
                    break

            # 8b. 寫入 per-dim picks
            opt_params = optimal[dim]  # 步驟 4 已確保 None 的 dim 不進 by_dim
            tp_mult = opt_params.take_profit_pct
            sl_mult = opt_params.stop_loss_pct
            hd = opt_params.hold_days_max

            for item in filtered:
                r = item['primary']
                entry_price = price_map.get(r.stock_id, 0.0)

                atr_row = (
                    db.query(StockFeature.atr20)
                    .filter(StockFeature.stock_id == r.stock_id, StockFeature.date == latest_date)
                    .first()
                )
                if atr_row and atr_row.atr20 and entry_price > 0:
                    tp = tp_mult * atr_row.atr20 / entry_price
                    sl = sl_mult * atr_row.atr20 / entry_price
                else:
                    tp = tp_mult * 0.03
                    sl = sl_mult * 0.03

                reasons = reasons_map.get(r.stock_id, [])

                db.add(StrategyMinerPick(
                    pick_date=pick_date,
                    stock_id=r.stock_id,
                    stock_name=r.stock_name,
                    strategy_ids=json.dumps([dim]),
                    weighted_score=round(item['score'], 4),
                    entry_price=entry_price,
                    take_profit_pct=tp,
                    stop_loss_pct=sl,
                    hold_days_max=hd,
                    time_dimension=dim,
                    direction=direction,
                    buy_reasons=json.dumps(reasons) if reasons else None,
                ))
                total_count += 1

        return total_count
```

- [ ] **Step 4: 跑新增的單元測試**

```bash
cd backend && ./.venv/bin/python -m pytest tests/services/test_strategy_miner_per_dim.py -v
```

Expected: 全部 PASS

- [ ] **Step 5: 跑既有 strategy_miner 測試防 regression**

```bash
cd backend && ./.venv/bin/python -m pytest tests/services/test_strategy_miner_history.py tests/api/test_strategy_miner_history_endpoint.py -v
```

Expected: 全部 PASS (若有失敗表示 API 層假設被破壞, 進 Task 5 修)

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/strategy_miner_service.py backend/tests/services/test_strategy_miner_per_dim.py
git commit -m "refactor(miner): _generate_direction_picks per-dimension architecture"
```

---

## Task 5: API 加 `resonance_count` 欄位

**Files:**
- Modify: `backend/app/api/endpoints/strategy_miner.py`

動態計算「同 pick_date + stock_id + direction 有幾個 time_dimension」= resonance。

- [ ] **Step 1: 寫 helper function**

Add near top of `backend/app/api/endpoints/strategy_miner.py` (after imports, before router):

```python
def _build_resonance_map(picks: list) -> dict:
    """計算每 (pick_date, stock_id, direction) 的共鳴維度數量。

    回傳 {(pick_date, stock_id, direction): count}。
    """
    buckets: dict = {}
    for p in picks:
        key = (p.pick_date, p.stock_id, p.direction)
        buckets.setdefault(key, set()).add(p.time_dimension)
    return {k: len(v) for k, v in buckets.items()}
```

- [ ] **Step 2: 修改 `/picks/today` endpoint**

找 `/picks/today` endpoint (約 line 135)，在組裝回傳 payload 前:

```python
resonance_map = _build_resonance_map(picks)
```

並在每筆 pick 的 dict 加欄位:
```python
"resonance_count": resonance_map.get((p.pick_date, p.stock_id, p.direction), 1),
```

- [ ] **Step 3: 同樣修改 `/picks/history`**

在 line ~492 的 `/picks/history` 同步加 `resonance_count`。

- [ ] **Step 4: 手動驗證 API**

```bash
cd backend && ./.venv/bin/python main.py &
sleep 3
curl -s http://localhost:8000/strategy-miner/picks/today | python -m json.tool | head -40
kill %1
```

Expected: 每筆 pick 有 `"resonance_count": N` 欄位，N ∈ {1,2,3}。

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/endpoints/strategy_miner.py
git commit -m "feat(miner-api): add resonance_count to picks payload"
```

---

## Task 6: Rebuild Historical Picks 腳本

**Files:**
- Create: `backend/scripts/rebuild_picks_per_dim.py`

- [ ] **Step 1: 寫 rebuild 腳本**

Create `backend/scripts/rebuild_picks_per_dim.py`:

```python
"""Rebuild strategy_miner_picks under per-dim architecture.

流程:
1. (選項) 清空 strategy_miner_picks (依賴 Task 1 已備份)
2. 複用 backfill_picks_history_walkforward.py 的邏輯, 以新 service 跑 walk-forward

等同於:
    ./.venv/bin/python scripts/backfill_picks_history_walkforward.py --start 2025-09-01

但先 TRUNCATE 確保是乾淨重建, 不做合併 (避免 time_dimension 舊融合列混雜)。
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


def main():
    parser = argparse.ArgumentParser(description="Rebuild picks under per-dim architecture")
    parser.add_argument("--start", type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
                        default=date(2025, 9, 1))
    parser.add_argument("--interval", type=int, default=14)
    parser.add_argument("--no-truncate", action="store_true",
                        help="Skip TRUNCATE (只補洞, 不清空; 新舊架構混存後果自負)")
    args = parser.parse_args()

    from sqlalchemy import text
    from app.db.database import SessionLocal
    from app.models.strategy_miner_pick import StrategyMinerPick

    db = SessionLocal()
    try:
        if not args.no_truncate:
            cnt = db.query(StrategyMinerPick).count()
            logger.info(f"TRUNCATE strategy_miner_picks ({cnt} rows will be removed)")
            db.execute(text("TRUNCATE TABLE strategy_miner_picks RESTART IDENTITY"))
            db.commit()

        # 沿用 backfill_picks_history_walkforward 的主邏輯
        from scripts.backfill_picks_history_walkforward import _reoptimize, _generate_picks_for_range

        today = date.today()
        checkpoints = []
        d = args.start
        while d < today:
            checkpoints.append(d)
            d = d + timedelta(days=args.interval)
        if checkpoints[-1] < today:
            checkpoints.append(today)

        logger.info(f"規劃 {len(checkpoints)} 個 checkpoints")

        total_picks = 0
        for i, cp in enumerate(checkpoints):
            logger.info(f"=== Checkpoint {i+1}/{len(checkpoints)}: {cp} ===")
            _reoptimize(db, cp)
            range_start = cp
            range_end = checkpoints[i + 1] if i + 1 < len(checkpoints) else today + timedelta(days=1)
            added = _generate_picks_for_range(db, range_start, range_end)
            total_picks += added

        total = db.query(StrategyMinerPick).count()
        logger.info(f"完成: 新增 {total_picks}, 表總計 {total}")
    except Exception as e:
        logger.error(f"失敗: {e}", exc_info=True)
        sys.exit(1)
    finally:
        db.close()


if __name__ == '__main__':
    main()
```

- [ ] **Step 2: NAS 執行 rebuild (長時間, run_in_background)**

```bash
ssh chihhaolai@10.0.4.3 "sudo /usr/local/bin/docker exec alphaforge-backend python scripts/rebuild_picks_per_dim.py --start 2025-09-01"
```

Expected: 無錯誤退出，最後輸出 `完成: 新增 N, 表總計 N`。預期 N 顯著大於舊 1875 (三維獨立後應該 ~3000-5000 筆)。

- [ ] **Step 3: 驗證 rebuild 結果**

```bash
ssh chihhaolai@10.0.4.3 "sudo /usr/local/bin/docker exec alphaforge-backend python -c \"
from app.db.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
rows = db.execute(text('SELECT time_dimension, direction, COUNT(*), MIN(pick_date)::text, MAX(pick_date)::text FROM strategy_miner_picks GROUP BY time_dimension, direction ORDER BY time_dimension, direction')).all()
for r in rows: print(r)
db.close()
\""
```

Expected:
- 5d/long: ~100-300 筆 9/1~4/17
- 10d/long: ~100-300 筆 9/1~4/17
- 20d/long: ~100-300 筆 9/1~4/17 (原本只 7 筆)

- [ ] **Step 4: Commit**

```bash
git add backend/scripts/rebuild_picks_per_dim.py
git commit -m "feat(miner): rebuild_picks_per_dim.py per-dim walk-forward rebuild"
```

---

## Task 7: 前端 Preview Widget 加共鳴徽章

**Files:**
- Modify: `frontend/components/StrategyMinerPreview.tsx`

- [ ] **Step 1: Interface 加欄位**

在 `StrategyMinerPreview.tsx` 找 pick 型別宣告 (line ~16 / ~33)，加:

```typescript
resonance_count?: number  // 1~3, 同股當日在幾個維度推薦
```

- [ ] **Step 2: UI 加徽章**

找顯示 pick 的 JSX (line ~100 附近 `dimLabel`)，旁邊加:

```tsx
{pick.resonance_count && pick.resonance_count >= 2 && (
  <span className="ml-2 px-1.5 py-0.5 text-xs rounded bg-amber-900/40 text-amber-300">
    {pick.resonance_count}維共鳴
  </span>
)}
```

- [ ] **Step 3: 本地驗證**

```bash
cd frontend
INTERNAL_API_URL=http://localhost:8000 npm run dev
# 瀏覽器開 http://localhost:3000/alphaforge 看首頁 picks 是否顯示共鳴徽章
```

Expected: 若當日某股在三維都被推薦，該筆應顯示 `3維共鳴`。

- [ ] **Step 4: Commit**

```bash
git add frontend/components/StrategyMinerPreview.tsx
git commit -m "feat(ui): picks preview 加共鳴徽章"
```

---

## Task 8: 前端 Strategy 頁面 Tab 語意調整

**Files:**
- Modify: `frontend/pages/strategy.tsx`

tab 仍保留，但現在語意變「真該維度的 Top5」，並補共鳴徽章。

- [ ] **Step 1: pick 型別加 resonance_count**

strategy.tsx line ~165/~196 `time_dimension: string` 附近加:

```typescript
resonance_count?: number
```

- [ ] **Step 2: RecPickCard / Preview 區塊加徽章**

找 `RecPickCard` 或 pick 渲染處 (line ~60、~125、~270)，在維度 label 後加:

```tsx
{pick.resonance_count && pick.resonance_count >= 2 && (
  <span className="ml-1.5 px-1 py-0.5 text-xs rounded bg-amber-900/40 text-amber-300">
    {pick.resonance_count}維
  </span>
)}
```

- [ ] **Step 3: 移除「primary dim」誤導文案**

找 tooltip 或 label 若有寫「此股主要維度」等字樣，改為「此筆推薦的維度」。用 grep 搜:

```bash
cd frontend && grep -n "primary\|主要維度\|主維度" pages/strategy.tsx components/
```

逐一檢視並修正文案。

- [ ] **Step 4: 本地驗證 tab 切換**

dev server 已開。點開 strategy 頁，切換 5d/10d/20d tab:
- 每個 tab 顯示該維度獨立 Top5 (可能同一股在多個 tab 都出現)
- 共鳴徽章顯示正確

- [ ] **Step 5: 跑 type check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: No errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/pages/strategy.tsx
git commit -m "feat(ui): strategy 頁 tab 語意轉為 per-dim + 共鳴徽章"
```

---

## Task 9: 更新 Memory 與回顧

**Files:**
- Modify: `/Users/chihhaolai/.claude/projects/-Users-chihhaolai-Documents-GitHub-AlphaForge/memory/project_next_steps.md`

- [ ] **Step 1: 更新 memory**

在 project_next_steps.md 頂端新增段落:

```markdown
## 2026-04-18 — Per-dimension Picks 架構完成

`strategy_miner_picks` 從融合架構轉為三維度獨立。
- unique constraint: `(pick_date, stock_id, direction)` → `(pick_date, stock_id, direction, time_dimension)`
- `_generate_direction_picks` 改為 per-dim 獨立 Top5 (不再 combine)
- API 加 `resonance_count` 欄位 (同股當日幾個 dim 被推薦)
- 前端 tab 語意由 primary dim 變真獨立，加共鳴徽章
- Rebuild 結果: picks 1875 → <N> 筆，5d/20d long 歷史從稀少變完整

**Why:** 研究 (research_dimension_fairness.py) 按維度獨立驗證 IC，但生產融合導致研究結論無法持續驗證。改獨立架構讓維度級監控 (overfit/退化曲線) 有真實生產樣本。

**影響**: 全輸過濾改為 per-dim 觀察; UI 同股可能同天 3 筆 (共鳴徽章區分)。
```

- [ ] **Step 2: 更新 MEMORY.md 索引行**

改 `[project_next_steps.md]` 行的 hook 文案反映新進展。

- [ ] **Step 3: Commit**

```bash
git add /Users/chihhaolai/.claude/projects/-Users-chihhaolai-Documents-GitHub-AlphaForge/memory/
git commit -m "docs(memory): per-dim picks 架構完成紀錄"
```

---

## 驗收標準

所有 task 完成後:

1. **DB**: `pg_constraint` 顯示 `uq_strategy_miner_pick_v3`，無 v2
2. **資料**: `strategy_miner_picks` 三維度 long 都有 9/1~今日連續歷史 (每日不一定每維度都有，但不會像舊架構 20d 只剩 7 筆)
3. **API**: `/strategy-miner/picks/today` 回傳每筆帶 `resonance_count`
4. **UI**: 首頁 + 策略頁共鳴徽章可見，tab 切換顯示真獨立維度 picks
5. **測試**: `tests/services/test_strategy_miner_per_dim.py` 全 PASS，既有測試無 regression
6. **排程**: 隔日 scheduler 跑 `run_daily` 正常寫入新 picks (drop-in compatible)

---

## 風險與回退

**若 Task 4 重構出錯導致 service 壞掉**:
- 回退: `git revert <commit>` 即可
- DB 不受影響 (model 跟 constraint 都已切，但舊邏輯寫入會因 constraint 差異出錯)
- 緊急情況: 可先回退 model constraint 到 v2，但需同時 DROP v3 / ADD v2

**若 Task 6 rebuild 結果數量異常 (過多或過少)**:
- 備份表 `strategy_miner_picks_backup_20260418_pre_v3` 可復原:
  ```sql
  TRUNCATE strategy_miner_picks;
  INSERT INTO strategy_miner_picks (...) SELECT (...) FROM strategy_miner_picks_backup_20260418_pre_v3;
  ```
- 復原後 constraint 不相容，需先 DROP v3 / ADD v2

**前端 tab 切換出現同股同天重複**:
- 這是新架構的預期行為，可由使用者視角「同一股在多維度都入選」判讀
- 若需避免重複，UI 層可加 dedupe 但會損失資訊

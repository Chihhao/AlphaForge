# 勝率提升 + 放空訊號 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 提升 Strategy Miner 做多勝率並新增放空訊號，讓推薦品質超越買 0050 基準。

**Architecture:** 分兩階段：(1) 訊號強度過濾 + 放空訊號產生 (2) 回測進場價修正與策略淘汰。所有改動向下相容——舊資料 direction 預設 'long'。

**Tech Stack:** FastAPI, SQLAlchemy, Pandas/NumPy, Next.js/React/TypeScript

---

## File Structure

### Backend - Models (modify)
- `backend/app/models/alpha_signal_history.py` — 新增 direction 欄位
- `backend/app/models/strategy_miner_pick.py` — 新增 direction 欄位

### Backend - Services (modify)
- `backend/app/services/alpha_miner_service.py` — 新增放空訊號產生邏輯
- `backend/app/services/strategy_miner_service.py` — 訊號過濾器 + 放空回測 + pick 上限

### Backend - API (modify)
- `backend/app/api/endpoints/strategy_miner.py` — API 回傳新增 direction 欄位

### Backend - Scheduler (modify)
- `backend/app/core/scheduler.py` — save_today_signals 加入 direction 參數

### Frontend (modify)
- `frontend/components/StrategyMinerPreview.tsx` — 多/空顏色區分
- `frontend/pages/strategy.tsx` — PickCard 支援放空顯示

### Validation Scripts (modify)
- `backend/scripts/validate_vs_benchmark.py` — 加入過濾後勝率驗證

---

## Phase 1: 訊號過濾 + 放空訊號

### Task 1: DB Models — 新增 direction 欄位

**Files:**
- Modify: `backend/app/models/alpha_signal_history.py`
- Modify: `backend/app/models/strategy_miner_pick.py`

- [ ] **Step 1: alpha_signal_history 新增 direction**

在 AlphaSignalHistory model 新增：
```python
direction = Column(String(5), default='long')  # 'long' / 'short'
```
更新 unique constraint 加入 direction。

- [ ] **Step 2: strategy_miner_pick 新增 direction**

在 StrategyMinerPick model 新增：
```python
direction = Column(String(5), default='long')  # 'long' / 'short'
```
更新 unique constraint 加入 direction。

- [ ] **Step 3: 執行 DB migration**

用 ALTER TABLE 加欄位（SQLite 相容），設預設值 'long'。

- [ ] **Step 4: 驗證 import 成功**

```bash
cd backend && ./.venv/bin/python -c "from main import app; print('OK')"
```

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat(models): alpha_signal_history, strategy_miner_pick 新增 direction 欄位"
```

---

### Task 2: Strategy Miner — 訊號強度過濾器

**Files:**
- Modify: `backend/app/services/strategy_miner_service.py:162-167`

- [ ] **Step 1: 新增觸發數門檻過濾**

在 run_daily() 的排序前，計算每個維度的 trigger_count P70 門檻，過濾掉弱訊號。

- [ ] **Step 2: 新增勝率門檻**

只使用 win_rate_test >= 0.50 的維度最優參數。

- [ ] **Step 3: 改 pick 上限為 5**

`[:10]` → `[:5]`（做多上限 5 檔）

- [ ] **Step 4: 驗證 run_daily 可執行**

```bash
cd backend && ./.venv/bin/python -c "
from app.db.database import SessionLocal
from app.services.strategy_miner_service import StrategyMinerService
db = SessionLocal()
count = StrategyMinerService.run_daily(db)
print(f'Generated {count} picks')
db.close()
"
```

- [ ] **Step 5: Commit**

---

### Task 3: Alpha Miner — 放空訊號產生

**Files:**
- Modify: `backend/app/services/alpha_miner_service.py`

- [ ] **Step 1: 新增 get_today_signals 的 direction 參數**

在 get_today_signals() 新增 direction='long' 參數。direction='short' 時：
- 使用 ic < 0 的策略（反向預測力）
- 或使用 ic > 0 策略的 loss_rate 高的股票

- [ ] **Step 2: 新增 save_today_signals 的 direction 支援**

save_today_signals(db, dim, direction='long') — 寫入時帶入 direction 欄位。

- [ ] **Step 3: 驗證放空訊號可產生**

- [ ] **Step 4: Commit**

---

### Task 4: Strategy Miner — 放空回測與推薦

**Files:**
- Modify: `backend/app/services/strategy_miner_service.py`

- [ ] **Step 1: _simulate_entries 支援放空**

新增 direction 參數，放空時 TP/SL 反轉：
- 做多：return = (exit - entry) / entry
- 放空：return = (entry - exit) / entry

- [ ] **Step 2: run_all 支援放空維度**

DIMENSIONS 擴充，每個維度分 long/short 各自尋優。

- [ ] **Step 3: run_daily 產生放空推薦**

放空推薦上限 5 檔，與做多分開排序。

- [ ] **Step 4: 驗證回測與推薦**

- [ ] **Step 5: Commit**

---

### Task 5: Scheduler + API — 放空流程串接

**Files:**
- Modify: `backend/app/core/scheduler.py`
- Modify: `backend/app/api/endpoints/strategy_miner.py`

- [ ] **Step 1: Scheduler 新增放空訊號儲存**

17:45 的 save_today_signals 同時儲存 long 和 short。

- [ ] **Step 2: API 回傳 direction 欄位**

所有 picks 相關端點加入 direction。
active picks 的浮動損益計算支援放空反轉。

- [ ] **Step 3: 驗證 API**

- [ ] **Step 4: Commit**

---

### Task 6: Frontend — 多/空顯示

**Files:**
- Modify: `frontend/components/StrategyMinerPreview.tsx`
- Modify: `frontend/pages/strategy.tsx`

- [ ] **Step 1: StrategyMinerPreview 支援 direction**

加入方向 badge（做多綠色、放空紅色）。

- [ ] **Step 2: strategy.tsx PickCard 支援放空**

放空卡片的 TP/SL 文字與顏色反轉。

- [ ] **Step 3: Commit**

---

## Phase 2: 模型改良

### Task 7: 回測進場價改為隔日開盤價

**Files:**
- Modify: `backend/app/services/strategy_miner_service.py:488-506`

- [ ] **Step 1: _load_prices 同時載入 open 價格**
- [ ] **Step 2: _simulate_entries 改用隔日開盤價進場**
- [ ] **Step 3: 重跑 validate_vs_benchmark.py 驗證改善**
- [ ] **Step 4: Commit**

---

### Task 8: 驗證與重訓

- [ ] **Step 1: 執行 run_all 重訓**
- [ ] **Step 2: 跑 validate_vs_benchmark.py 對比勝率**
- [ ] **Step 3: 跑 validate_short.py 驗證放空勝率**
- [ ] **Step 4: Commit**

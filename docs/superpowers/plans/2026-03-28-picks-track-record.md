# Picks Track Record Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 strategy 頁面推薦清單上方新增可展開的「歷史推薦成績單」，讓使用者在跟單前看到系統過去的每筆推薦結果。

**Architecture:** 新增後端端點 `GET /strategy-miner/picks/concluded`（複用 `live-performance` 現有邏輯，改為回傳逐筆清單）；新增前端元件 `PicksTrackRecord.tsx`（自行 fetch 資料、懶載入、列展開）；在 `strategy.tsx` 插入此元件。不改動 DB schema。

**Tech Stack:** FastAPI / SQLAlchemy（後端），React / TypeScript / Tailwind CSS（前端）

---

## File Map

| 動作 | 檔案 | 職責 |
|------|------|------|
| Create | `backend/app/schemas/strategy_miner.py` | Pydantic schema：ConcludedPickItem、ConcludedPicksResponse |
| Create | `backend/tests/test_strategy_miner_concluded.py` | 端點測試 |
| Create | `frontend/components/PicksTrackRecord.tsx` | 成績單元件（自含資料 fetch） |
| Modify | `backend/app/api/endpoints/strategy_miner.py` | 新增 GET /picks/concluded 端點 |
| Modify | `frontend/pages/strategy.tsx` | import + 插入 PicksTrackRecord |

---

## Task 1：建立 Pydantic Schema

**Files:**
- Create: `backend/app/schemas/strategy_miner.py`

- [ ] **Step 1：建立 schema 檔案**

```python
# backend/app/schemas/strategy_miner.py
from pydantic import BaseModel
from typing import List
from datetime import date


class ConcludedPickItem(BaseModel):
    pick_date: date
    stock_id: str
    stock_name: str
    entry_price: float
    exit_reason: str          # take_profit | stop_loss | time_limit | settled
    return_pct: float
    days_held: int
    time_dimension: str
    buy_reasons: List[str]
    take_profit_pct: float
    stop_loss_pct: float
    hold_days_max: int


class ConcludedPicksResponse(BaseModel):
    items: List[ConcludedPickItem]
    total: int
```

- [ ] **Step 2：確認語法無誤**

```bash
cd backend && ./.venv/bin/python -c "from app.schemas.strategy_miner import ConcludedPicksResponse; print('ok')"
```

Expected output: `ok`

- [ ] **Step 3：Commit**

```bash
git add backend/app/schemas/strategy_miner.py
git commit -m "feat(schema): 新增 ConcludedPickItem / ConcludedPicksResponse"
```

---

## Task 2：撰寫失敗測試

**Files:**
- Create: `backend/tests/test_strategy_miner_concluded.py`

- [ ] **Step 1：建立測試檔案**

```python
# backend/tests/test_strategy_miner_concluded.py
import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_concluded_picks_returns_correct_shape():
    """回傳格式必須包含 items（list）和 total（int）"""
    resp = client.get("/strategy-miner/picks/concluded")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total" in data
    assert isinstance(data["items"], list)
    assert isinstance(data["total"], int)


def test_concluded_picks_each_item_has_required_fields():
    """每筆記錄必須包含所有必要欄位"""
    resp = client.get("/strategy-miner/picks/concluded")
    data = resp.json()
    if not data["items"]:
        pytest.skip("無已出場 picks，跳過欄位驗證")
    item = data["items"][0]
    for field in [
        "pick_date", "stock_id", "stock_name", "entry_price",
        "exit_reason", "return_pct", "days_held", "time_dimension",
        "buy_reasons", "take_profit_pct", "stop_loss_pct", "hold_days_max",
    ]:
        assert field in item, f"缺少欄位：{field}"


def test_concluded_picks_exit_reason_valid():
    """exit_reason 只能是 take_profit / stop_loss / time_limit / settled"""
    resp = client.get("/strategy-miner/picks/concluded")
    data = resp.json()
    valid = {"take_profit", "stop_loss", "time_limit", "settled"}
    for item in data["items"]:
        assert item["exit_reason"] in valid, f"無效 exit_reason: {item['exit_reason']}"


def test_concluded_picks_pagination():
    """limit=1&offset=0 應只回傳 1 筆，total 不變"""
    resp_all = client.get("/strategy-miner/picks/concluded?limit=100&offset=0")
    total = resp_all.json()["total"]
    if total < 2:
        pytest.skip("資料不足，跳過分頁測試")
    resp_page = client.get("/strategy-miner/picks/concluded?limit=1&offset=0")
    data = resp_page.json()
    assert len(data["items"]) == 1
    assert data["total"] == total


def test_concluded_picks_sorted_by_date_desc():
    """結果應按 pick_date 降序排列"""
    resp = client.get("/strategy-miner/picks/concluded?limit=100")
    items = resp.json()["items"]
    if len(items) < 2:
        pytest.skip("資料不足，跳過排序測試")
    dates = [i["pick_date"] for i in items]
    assert dates == sorted(dates, reverse=True)
```

- [ ] **Step 2：執行測試確認失敗（端點尚不存在）**

```bash
cd backend && ./.venv/bin/python -m pytest tests/test_strategy_miner_concluded.py -v
```

Expected: `FAILED` — `test_concluded_picks_returns_correct_shape` 應失敗（404 或端點不存在）

- [ ] **Step 3：Commit**

```bash
git add backend/tests/test_strategy_miner_concluded.py
git commit -m "test: 新增 /picks/concluded 端點測試（TDD 紅燈）"
```

---

## Task 3：實作後端端點

**Files:**
- Modify: `backend/app/api/endpoints/strategy_miner.py`

- [ ] **Step 1：在 strategy_miner.py 頂部補上 json import**

確認第 1~17 行的 import 區塊是否已有 `import json`，若無則加入：

```python
import json
```

（在 `from sqlalchemy import func, and_` 後方加入一行）

- [ ] **Step 2：在 `get_live_performance` 函式結尾後（第 342 行之後）插入新端點**

在 `@router.get("/picks/history")` 之前，插入下方完整函式：

```python
@router.get("/picks/concluded")
def get_concluded_picks(
    limit: int = 20,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    """已出場 picks 的逐筆成績單（停利 / 停損 / 到期 / 已結算）。

    與 live-performance 使用相同的去重與判斷邏輯，
    但回傳每筆明細而非彙總數字，並支援 limit/offset 分頁。
    """
    today = date.today()
    cutoff = today - timedelta(days=60)

    rows = (
        db.query(StrategyMinerPick)
        .filter(
            StrategyMinerPick.pick_date >= cutoff,
            StrategyMinerPick.pick_date < today,
        )
        .order_by(StrategyMinerPick.pick_date.desc())
        .all()
    )
    if not rows:
        return {"items": [], "total": 0}

    # 同股票只保留最早一筆（與 live-performance 邏輯一致）
    seen: dict = {}
    for p in rows:
        seen[p.stock_id] = p
    deduped = list(seen.values())

    stock_ids = [p.stock_id for p in deduped]
    price_map = _get_current_prices(db, stock_ids)

    concluded = []
    for p in deduped:
        entry = p.entry_price or 0
        current = price_map.get(p.stock_id, 0)
        if entry <= 0 or current <= 0:
            continue
        days_held = (today - p.pick_date).days
        float_pct = round((current - entry) / entry * 100, 2)

        if current >= entry * (1 + p.take_profit_pct):
            exit_reason = "take_profit"
        elif current <= entry * (1 - p.stop_loss_pct):
            exit_reason = "stop_loss"
        elif days_held > p.hold_days_max + 7:
            exit_reason = "settled"
        elif days_held >= p.hold_days_max:
            exit_reason = "time_limit"
        else:
            continue  # 持有中，跳過

        buy_reasons: list = []
        if p.buy_reasons:
            try:
                buy_reasons = json.loads(p.buy_reasons)
            except Exception:
                pass

        concluded.append({
            "pick_date": p.pick_date.isoformat(),
            "stock_id": p.stock_id,
            "stock_name": p.stock_name,
            "entry_price": entry,
            "exit_reason": exit_reason,
            "return_pct": float_pct,
            "days_held": days_held,
            "time_dimension": p.time_dimension or "10d",
            "buy_reasons": buy_reasons,
            "take_profit_pct": p.take_profit_pct,
            "stop_loss_pct": p.stop_loss_pct,
            "hold_days_max": p.hold_days_max,
        })

    concluded.sort(key=lambda x: x["pick_date"], reverse=True)
    total = len(concluded)
    return {"items": concluded[offset: offset + limit], "total": total}
```

- [ ] **Step 3：執行測試確認全部通過**

```bash
cd backend && ./.venv/bin/python -m pytest tests/test_strategy_miner_concluded.py -v
```

Expected:
```
PASSED test_concluded_picks_returns_correct_shape
PASSED test_concluded_picks_each_item_has_required_fields  (or SKIPPED)
PASSED test_concluded_picks_exit_reason_valid
PASSED test_concluded_picks_pagination                      (or SKIPPED)
PASSED test_concluded_picks_sorted_by_date_desc             (or SKIPPED)
```

- [ ] **Step 4：確認既有測試沒有壞掉**

```bash
cd backend && ./.venv/bin/python -m pytest -v
```

Expected: 所有測試 PASSED 或 SKIPPED，無 FAILED

- [ ] **Step 5：Commit**

```bash
git add backend/app/api/endpoints/strategy_miner.py
git commit -m "feat(api): 新增 GET /strategy-miner/picks/concluded 端點"
```

---

## Task 4：建立前端 PicksTrackRecord 元件

**Files:**
- Create: `frontend/components/PicksTrackRecord.tsx`

- [ ] **Step 1：建立元件檔案**

```tsx
// frontend/components/PicksTrackRecord.tsx
import { useState, useEffect } from 'react'
import api from '../lib/api'

interface ConcludedPick {
    pick_date: string
    stock_id: string
    stock_name: string
    entry_price: number
    exit_reason: 'take_profit' | 'stop_loss' | 'time_limit' | 'settled'
    return_pct: number
    days_held: number
    time_dimension: string
    buy_reasons: string[]
    take_profit_pct: number
    stop_loss_pct: number
    hold_days_max: number
}

interface LivePerf {
    trade_count: number
    win_rate: number | null
    avg_return: number | null
}

const EXIT_LABEL: Record<string, string> = {
    take_profit: '停利',
    stop_loss: '停損',
    time_limit: '到期',
    settled: '到期',
}

export default function PicksTrackRecord() {
    const [open, setOpen] = useState(false)
    const [livePerf, setLivePerf] = useState<LivePerf | null>(null)
    const [picks, setPicks] = useState<ConcludedPick[]>([])
    const [total, setTotal] = useState(0)
    const [offset, setOffset] = useState(0)
    const [loading, setLoading] = useState(false)
    const [expandedId, setExpandedId] = useState<string | null>(null)

    useEffect(() => {
        api.get('/strategy-miner/picks/live-performance')
            .then(r => setLivePerf(r.data))
            .catch(() => {})
    }, [])

    const load = async (newOffset: number) => {
        setLoading(true)
        try {
            const res = await api.get(
                `/strategy-miner/picks/concluded?limit=20&offset=${newOffset}`
            )
            if (newOffset === 0) {
                setPicks(res.data.items)
            } else {
                setPicks(prev => [...prev, ...res.data.items])
            }
            setTotal(res.data.total)
            setOffset(newOffset + 20)
        } finally {
            setLoading(false)
        }
    }

    const handleToggle = () => {
        if (!open && picks.length === 0) load(0)
        setOpen(v => !v)
    }

    const returnColor = (item: ConcludedPick) => {
        if (item.return_pct > 0) return 'text-emerald-400'
        if (item.exit_reason === 'stop_loss') return 'text-rose-400'
        return 'text-zinc-400'
    }

    const exitBadgeStyle = (reason: string) => {
        if (reason === 'take_profit')
            return 'bg-emerald-900/40 text-emerald-400 border-emerald-800/50'
        if (reason === 'stop_loss')
            return 'bg-rose-900/40 text-rose-400 border-rose-800/50'
        return 'bg-zinc-800/60 text-zinc-400 border-zinc-700/50'
    }

    const exitSymbol = (reason: string) =>
        reason === 'take_profit' ? ' ✓' : reason === 'stop_loss' ? ' ✗' : ''

    const tradeCount = livePerf?.trade_count ?? 0
    const winRate =
        livePerf?.win_rate != null
            ? `${(livePerf.win_rate * 100).toFixed(1)}%`
            : '—'
    const avgReturn =
        livePerf?.avg_return != null
            ? `${livePerf.avg_return > 0 ? '+' : ''}${livePerf.avg_return.toFixed(1)}%`
            : '—'

    return (
        <div className="bg-zinc-900/60 border border-zinc-800 rounded-2xl overflow-hidden">
            {/* ── Header ── */}
            <button
                onClick={handleToggle}
                className="w-full flex items-center justify-between px-4 py-3 hover:bg-zinc-800/40 transition-colors"
            >
                <div className="flex items-center gap-2">
                    <span className="text-xs font-bold text-zinc-400 uppercase tracking-widest">
                        歷史推薦成績
                    </span>
                    {tradeCount > 0 && (
                        <span className="text-[10px] font-mono text-zinc-500">
                            {tradeCount} 筆 · 勝率 {winRate} · 均 {avgReturn}
                        </span>
                    )}
                </div>
                <svg
                    viewBox="0 0 24 24"
                    width={14}
                    height={14}
                    className={`fill-zinc-500 transition-transform ${open ? 'rotate-180' : ''}`}
                >
                    <path d="M7,10L12,15L17,10H7Z" />
                </svg>
            </button>

            {/* ── Table ── */}
            {open && (
                <div className="border-t border-zinc-800">
                    {loading && picks.length === 0 && (
                        <div className="p-4 text-zinc-500 text-sm text-center">載入中...</div>
                    )}
                    {!loading && picks.length === 0 && (
                        <div className="p-4 text-zinc-500 text-sm text-center">
                            尚無已出場記錄
                        </div>
                    )}

                    {picks.map(item => {
                        const rowId = `${item.pick_date}-${item.stock_id}`
                        const isExpanded = expandedId === rowId
                        return (
                            <div
                                key={rowId}
                                className="border-b border-zinc-800/60 last:border-0"
                            >
                                {/* ── Row ── */}
                                <button
                                    onClick={() =>
                                        setExpandedId(isExpanded ? null : rowId)
                                    }
                                    className="w-full flex items-center justify-between px-4 py-2.5 hover:bg-zinc-800/30 transition-colors text-left"
                                >
                                    <div className="flex items-center gap-3 min-w-0">
                                        <span className="text-[10px] font-mono text-zinc-600 shrink-0">
                                            {item.pick_date.slice(5)}
                                        </span>
                                        <span className="text-sm text-zinc-200 truncate">
                                            {item.stock_name}
                                        </span>
                                        <span
                                            className={`text-[10px] px-1.5 py-0.5 rounded border shrink-0 ${exitBadgeStyle(item.exit_reason)}`}
                                        >
                                            {EXIT_LABEL[item.exit_reason]}
                                            {exitSymbol(item.exit_reason)}
                                        </span>
                                    </div>
                                    <span
                                        className={`text-sm font-mono font-bold shrink-0 ${returnColor(item)}`}
                                    >
                                        {item.return_pct > 0 ? '+' : ''}
                                        {item.return_pct.toFixed(1)}%
                                    </span>
                                </button>

                                {/* ── Expanded Detail ── */}
                                {isExpanded && (
                                    <div className="px-4 pb-3 bg-zinc-900/40 text-xs text-zinc-400 space-y-1.5">
                                        <div className="flex gap-3 flex-wrap">
                                            <span>
                                                入場{' '}
                                                <span className="text-zinc-200">
                                                    {item.entry_price.toFixed(1)}
                                                </span>
                                            </span>
                                            <span>
                                                持有{' '}
                                                <span className="text-zinc-200">
                                                    {item.days_held}
                                                </span>{' '}
                                                天
                                            </span>
                                            <span className="text-zinc-600">
                                                {item.time_dimension} 維度
                                            </span>
                                        </div>
                                        <div className="text-zinc-600">
                                            停利 +{(item.take_profit_pct * 100).toFixed(0)}% ／ 停損 -
                                            {(item.stop_loss_pct * 100).toFixed(0)}% ／ 最多{' '}
                                            {item.hold_days_max} 天
                                        </div>
                                        {item.buy_reasons.length > 0 && (
                                            <div className="flex flex-wrap gap-1 pt-0.5">
                                                {item.buy_reasons.map((r, i) => (
                                                    <span
                                                        key={i}
                                                        className="bg-zinc-800 text-zinc-400 px-1.5 py-0.5 rounded text-[10px]"
                                                    >
                                                        {r}
                                                    </span>
                                                ))}
                                            </div>
                                        )}
                                    </div>
                                )}
                            </div>
                        )
                    })}

                    {/* ── 顯示更多 ── */}
                    {picks.length < total && (
                        <button
                            onClick={() => load(offset)}
                            disabled={loading}
                            className="w-full py-2.5 text-xs text-zinc-500 hover:text-zinc-300 transition-colors disabled:opacity-50"
                        >
                            {loading
                                ? '載入中...'
                                : `顯示更多（${picks.length} / ${total}）`}
                        </button>
                    )}
                </div>
            )}
        </div>
    )
}
```

- [ ] **Step 2：型別檢查**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -20
```

Expected: 無錯誤（或只有與本元件無關的既有錯誤）

- [ ] **Step 3：Commit**

```bash
git add frontend/components/PicksTrackRecord.tsx
git commit -m "feat(ui): 新增 PicksTrackRecord 元件"
```

---

## Task 5：整合至 strategy.tsx

**Files:**
- Modify: `frontend/pages/strategy.tsx`

- [ ] **Step 1：在 import 區塊加入 PicksTrackRecord**

找到 `frontend/pages/strategy.tsx` 的 import 區塊（第 1~20 行附近），加入：

```typescript
import PicksTrackRecord from '../components/PicksTrackRecord'
```

（加在其他 component import 旁，例如 StrategyMinerPreview import 附近）

- [ ] **Step 2：插入元件**

找到第 856~858 行附近的這段 JSX 注釋：

```tsx
                {/* ── 明日建議買入 ──────────────────────────────────────── */}
```

在此注釋的**正上方**插入：

```tsx
                {/* ── 歷史推薦成績 ──────────────────────────────────────── */}
                <PicksTrackRecord />
```

- [ ] **Step 3：型別檢查**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -20
```

Expected: 無新增錯誤

- [ ] **Step 4：Commit**

```bash
git add frontend/pages/strategy.tsx
git commit -m "feat(ui): 在 strategy 頁插入歷史推薦成績單元件"
```

---

## 驗收標準

1. `GET /strategy-miner/picks/concluded` 回傳 `{"items": [...], "total": N}`
2. 所有後端測試通過（`pytest -v`）
3. strategy 頁「歷史推薦成績」區塊預設收合，顯示彙總數字
4. 展開後顯示逐筆清單，每列含日期、股名、出場原因、報酬
5. 點擊列展開顯示入場價、持有天數、買入理由
6. 「顯示更多」按鈕在 total > 20 時出現
7. 停利 ✓ emerald / 停損 ✗ rose / 到期正報酬 emerald / 到期負報酬 zinc

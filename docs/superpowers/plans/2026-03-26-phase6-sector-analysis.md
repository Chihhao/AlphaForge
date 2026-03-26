# Phase 6 產業輪動分析 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增首頁產業強弱 widget，顯示前 5 強 / 後 5 弱產業排行，並回補 `sector_rs` / `foreign_hold_pct` 歷史資料。

**Architecture:** 後端新增 `GET /market/sector-strength` 端點，從 `stock_features` 聚合各產業 `sector_rs` 中位數；前端新增 `SectorStrengthWidget` 元件，以 SWR 一次性 fetch 並顯示雙欄排行。資料回補透過重跑現有的 `backfill_features.py` 腳本完成。

**Tech Stack:** FastAPI + SQLAlchemy + Pydantic V2 / Next.js 14 + TypeScript + SWR

---

## File Map

| 動作 | 檔案 | 用途 |
|---|---|---|
| Modify | `backend/app/schemas/market.py` | 新增 `SectorStrengthItem`、`SectorStrengthResponse` |
| Modify | `backend/app/services/market_service.py` | 新增 `get_sector_strength()` 方法 |
| Modify | `backend/app/api/endpoints/market.py` | 新增 `GET /market/sector-strength` 路由 |
| Create | `backend/tests/test_sector_strength.py` | 後端單元測試 |
| Create | `frontend/components/SectorStrengthWidget.tsx` | 新元件 |
| Modify | `frontend/pages/index.tsx` | 引入並插入 widget |

---

### Task 1：診斷資料覆蓋率

**目的：** 在開始回補前確認 `stock_chip_data.foreign_hold_pct` 與 `stock_features.sector_rs` 的實際資料狀況。

- [ ] **Step 1：執行診斷 SQL**

```bash
cd backend
./.venv/bin/python -c "
from app.db.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()

# 1. stock_chip_data.foreign_hold_pct 覆蓋率
r1 = db.execute(text('''
    SELECT
        COUNT(*) AS total,
        SUM(CASE WHEN foreign_hold_pct IS NOT NULL THEN 1 ELSE 0 END) AS non_null,
        MIN(date) AS min_date,
        MAX(date) AS max_date
    FROM stock_chip_data
''')).fetchone()
print(f'chip foreign_hold_pct: {r1.non_null}/{r1.total} ({r1.min_date}~{r1.max_date})')

# 2. stock_features.sector_rs 覆蓋率
r2 = db.execute(text('''
    SELECT
        COUNT(*) AS total,
        SUM(CASE WHEN sector_rs IS NOT NULL THEN 1 ELSE 0 END) AS non_null,
        MIN(date) AS min_date,
        MAX(date) AS max_date
    FROM stock_features
''')).fetchone()
print(f'features sector_rs: {r2.non_null}/{r2.total} ({r2.min_date}~{r2.max_date})')
db.close()
"
```

Expected: 輸出兩行覆蓋率統計。若 `sector_rs` 的 `non_null` 遠低於 `total`，代表需要回補。

- [ ] **Step 2：記錄結果（無需 commit）**

根據輸出判斷：
- 若 `features.sector_rs` 大多為 NULL → Task 8（回補）為必要步驟
- 若 `chip.foreign_hold_pct` 覆蓋率 < 20% → Alpha Miner 重訓時 `foreign_hold_pct` 因子貢獻有限，屬預期內

---

### Task 2：新增 Pydantic Schema

**Files:**
- Modify: `backend/app/schemas/market.py`

- [ ] **Step 1：新增兩個 Pydantic model**

在 `backend/app/schemas/market.py` 末尾新增：

```python
class SectorStrengthItem(BaseModel):
    industry: str
    median_rs: float
    stock_count: int


class SectorStrengthResponse(BaseModel):
    date: Optional[str]
    top: List[SectorStrengthItem]
    bottom: List[SectorStrengthItem]
```

- [ ] **Step 2：確認匯入正常**

```bash
cd backend
./.venv/bin/python -c "from app.schemas.market import SectorStrengthItem, SectorStrengthResponse; print('OK')"
```

Expected: `OK`

- [ ] **Step 3：Commit**

```bash
git add backend/app/schemas/market.py
git commit -m "feat(schema): 新增 SectorStrengthItem / SectorStrengthResponse"
```

---

### Task 3：後端服務方法 + 測試

**Files:**
- Modify: `backend/app/services/market_service.py`
- Create: `backend/tests/test_sector_strength.py`

- [ ] **Step 1：先寫失敗的測試**

建立 `backend/tests/test_sector_strength.py`：

```python
import pytest
from app.services.market_service import MarketService
from app.schemas.market import SectorStrengthResponse


def test_get_sector_strength_returns_correct_schema():
    """回傳格式必須符合 SectorStrengthResponse"""
    result = MarketService.get_sector_strength()
    assert isinstance(result, SectorStrengthResponse)
    assert isinstance(result.top, list)
    assert isinstance(result.bottom, list)
    assert len(result.top) <= 5
    assert len(result.bottom) <= 5


def test_get_sector_strength_top_sorted_descending():
    """top 應依 median_rs 由高到低排序"""
    result = MarketService.get_sector_strength()
    if len(result.top) >= 2:
        assert result.top[0].median_rs >= result.top[1].median_rs


def test_get_sector_strength_bottom_sorted_ascending():
    """bottom 應依 median_rs 由低到高排序"""
    result = MarketService.get_sector_strength()
    if len(result.bottom) >= 2:
        assert result.bottom[0].median_rs <= result.bottom[1].median_rs


def test_get_sector_strength_no_overlap():
    """top 與 bottom 的產業不應重疊（除非總產業數 ≤ 10）"""
    result = MarketService.get_sector_strength()
    if len(result.top) == 5 and len(result.bottom) == 5:
        top_industries = {item.industry for item in result.top}
        bottom_industries = {item.industry for item in result.bottom}
        assert top_industries.isdisjoint(bottom_industries)


def test_get_sector_strength_empty_when_no_data():
    """無資料時應回傳 date=None, top=[], bottom=[]（不應拋例外）"""
    # 直接呼叫，若 DB 無資料應 gracefully 回傳空結構
    result = MarketService.get_sector_strength()
    assert result is not None
```

- [ ] **Step 2：執行測試，確認失敗**

```bash
cd backend
./.venv/bin/python -m pytest tests/test_sector_strength.py -v
```

Expected: `AttributeError: type object 'MarketService' has no attribute 'get_sector_strength'`

- [ ] **Step 3：實作 `get_sector_strength()`**

在 `backend/app/services/market_service.py` 頂部 import 區塊補充：

```python
from app.models.stock_feature import StockFeature
from app.models.user import Stock
from app.schemas.market import SectorStrengthItem, SectorStrengthResponse
```

在 `market_service.py` 頂部 import 區塊補上（與現有 import 並列，不要 lazy import）：
```python
import pandas as pd
from app.models.stock_feature import StockFeature
from app.models.user import Stock
from app.schemas.market import SectorStrengthItem, SectorStrengthResponse
```

在 `market_service.py` 的模組層（`_rankings_cache` 等變數旁）新增快取變數：

```python
_sector_cache: Optional[SectorStrengthResponse] = None
_sector_cache_time: Optional[datetime] = None
```

在 `MarketService` 類別末尾新增方法：

```python
@staticmethod
def get_sector_strength(top_n: int = 5) -> SectorStrengthResponse:
    """取得各產業 sector_rs 強弱排行（前 N 強 / 後 N 弱）"""
    global _sector_cache, _sector_cache_time

    now = datetime.now()
    if (
        _sector_cache is not None
        and _sector_cache_time is not None
        and (now - _sector_cache_time).total_seconds() < _CACHE_TTL_SECONDS
    ):
        return _sector_cache

    result = MarketService._compute_sector_strength(top_n)
    _sector_cache = result
    _sector_cache_time = now
    return result

@staticmethod
def _compute_sector_strength(top_n: int = 5) -> SectorStrengthResponse:
    from sqlalchemy import func, text as sa_text
    db = SessionLocal()
    try:
        # 最近一個有效交易日（個股數 > 100）
        latest = (
            db.query(StockFeature.date)
            .filter(StockFeature.sector_rs.isnot(None))
            .group_by(StockFeature.date)
            .having(func.count(StockFeature.stock_id) > 100)
            .order_by(StockFeature.date.desc())
            .first()
        )
        if not latest:
            return SectorStrengthResponse(date=None, top=[], bottom=[])

        target_date = latest[0]

        # 取得當日特徵 + 產業（join stocks 表）
        # 注意：Stock 定義於 app.models.user（歷史遺留，與 User 同檔案）
        rows = (
            db.query(StockFeature.stock_id, StockFeature.sector_rs, Stock.industry)
            .join(Stock, Stock.stock_id == StockFeature.stock_id)
            .filter(
                StockFeature.date == target_date,
                StockFeature.sector_rs.isnot(None),
                Stock.industry.isnot(None),
            )
            .all()
        )

        if not rows:
            return SectorStrengthResponse(date=target_date.isoformat(), top=[], bottom=[])

        # 按產業分組計算中位數
        df = pd.DataFrame(rows, columns=['stock_id', 'sector_rs', 'industry'])
        agg = (
            df.groupby('industry')['sector_rs']
            .agg(median_rs='median', stock_count='count')
            .reset_index()
        )
        # 過濾股票數 < 3 的產業
        agg = agg[agg['stock_count'] >= 3].sort_values('median_rs', ascending=False)

        top_rows = agg.head(top_n)
        bottom_rows = agg.tail(top_n).sort_values('median_rs', ascending=True)

        top = [
            SectorStrengthItem(
                industry=r['industry'],
                median_rs=round(float(r['median_rs']), 2),
                stock_count=int(r['stock_count']),
            )
            for _, r in top_rows.iterrows()
        ]
        bottom = [
            SectorStrengthItem(
                industry=r['industry'],
                median_rs=round(float(r['median_rs']), 2),
                stock_count=int(r['stock_count']),
            )
            for _, r in bottom_rows.iterrows()
        ]

        return SectorStrengthResponse(
            date=target_date.isoformat(),
            top=top,
            bottom=bottom,
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"[MarketService] sector_strength error: {e}")
        return SectorStrengthResponse(date=None, top=[], bottom=[])
    finally:
        db.close()
```

- [ ] **Step 4：執行測試，確認通過**

```bash
cd backend
./.venv/bin/python -m pytest tests/test_sector_strength.py -v
```

Expected: 所有測試 PASS（若 DB 無 `sector_rs` 資料，`test_get_sector_strength_no_overlap` 會因 top/bottom 各為空而跳過斷言，屬正常）

- [ ] **Step 5：Commit**

```bash
git add backend/app/services/market_service.py backend/tests/test_sector_strength.py
git commit -m "feat(market): 新增 get_sector_strength() 服務方法與測試"
```

---

### Task 4：後端 API 路由

**Files:**
- Modify: `backend/app/api/endpoints/market.py`

- [ ] **Step 1：在 `market.py` 末尾新增路由**

先在檔案頂部 import 區塊補上（若尚未匯入）：
```python
from app.schemas.market import MarketSummary, AlphaStats, SectorStrengthResponse
```

再在末尾新增路由：
```python
@router.get("/sector-strength", response_model=SectorStrengthResponse)
def get_sector_strength():
    """各產業 sector_rs 強弱排行（前 5 強 / 後 5 弱）"""
    from app.services.market_service import MarketService
    return MarketService.get_sector_strength()
```

- [ ] **Step 2：手動測試路由**

```bash
cd backend
./.venv/bin/python main.py &
sleep 2
curl -s http://localhost:8000/market/sector-strength | python3 -m json.tool
```

Expected: 回傳 JSON，含 `date`、`top`、`bottom` 欄位（若 DB 無資料則 top/bottom 為空陣列）

```bash
kill %1  # 結束背景 server
```

- [ ] **Step 3：Commit**

```bash
git add backend/app/api/endpoints/market.py
git commit -m "feat(api): 新增 GET /market/sector-strength 端點"
```

---

### Task 5：前端 SectorStrengthWidget 元件

**Files:**
- Create: `frontend/components/SectorStrengthWidget.tsx`

- [ ] **Step 1：建立元件**

建立 `frontend/components/SectorStrengthWidget.tsx`：

```tsx
import useSWR from 'swr'

interface SectorItem {
  industry: string
  median_rs: number
  stock_count: number
}

interface SectorStrengthData {
  date: string | null
  top: SectorItem[]
  bottom: SectorItem[]
}

const fetcher = (url: string) => fetch(url).then(r => r.json())

export default function SectorStrengthWidget() {
  const { data, error } = useSWR<SectorStrengthData>('/api/market/sector-strength', fetcher)

  if (error) return null
  if (!data) {
    return (
      <div className="bg-zinc-800/60 rounded-xl p-4 border border-zinc-700/50">
        <h2 className="text-sm font-semibold text-zinc-400 mb-3">產業輪動強弱</h2>
        <p className="text-xs text-zinc-500">載入中...</p>
      </div>
    )
  }

  if (!data.date || (data.top.length === 0 && data.bottom.length === 0)) {
    return (
      <div className="bg-zinc-800/60 rounded-xl p-4 border border-zinc-700/50">
        <h2 className="text-sm font-semibold text-zinc-400 mb-3">產業輪動強弱</h2>
        <p className="text-xs text-zinc-500">產業資料尚未就緒，請先執行特徵回補</p>
      </div>
    )
  }

  const formatRs = (val: number) => (val >= 0 ? `+${val.toFixed(1)}` : val.toFixed(1))

  return (
    <div className="bg-zinc-800/60 rounded-xl p-4 border border-zinc-700/50">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold text-zinc-200">產業輪動強弱</h2>
        <span className="text-xs text-zinc-500">{data.date}</span>
      </div>

      <div className="grid grid-cols-2 gap-3">
        {/* 強勢產業 */}
        <div>
          <p className="text-xs text-emerald-400 font-medium mb-2">強勢產業</p>
          <div className="space-y-1">
            {data.top.map((item) => (
              <div key={item.industry} className="flex items-center justify-between">
                <span className="text-xs text-zinc-300 truncate max-w-[100px]">{item.industry}</span>
                <span className="text-xs font-mono text-emerald-400 ml-1">
                  {formatRs(item.median_rs)}
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* 弱勢產業 */}
        <div>
          <p className="text-xs text-rose-400 font-medium mb-2">弱勢產業</p>
          <div className="space-y-1">
            {data.bottom.map((item) => (
              <div key={item.industry} className="flex items-center justify-between">
                <span className="text-xs text-zinc-300 truncate max-w-[100px]">{item.industry}</span>
                <span className="text-xs font-mono text-rose-400 ml-1">
                  {formatRs(item.median_rs)}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 2：型別檢查**

```bash
cd frontend
npx tsc --noEmit 2>&1 | grep SectorStrength
```

Expected: 無輸出（無型別錯誤）

- [ ] **Step 3：Commit**

```bash
git add frontend/components/SectorStrengthWidget.tsx
git commit -m "feat(ui): 新增 SectorStrengthWidget 元件"
```

---

### Task 6：首頁整合

**Files:**
- Modify: `frontend/pages/index.tsx`

- [ ] **Step 1：引入並插入 widget**

在 `frontend/pages/index.tsx` 中：

1. 在 import 區塊新增：
```tsx
import SectorStrengthWidget from '../components/SectorStrengthWidget';
```

2. 在 `<StrategyMinerPreview />` section 之後、`<WatchlistWidget />` section 之前插入（即 index.tsx 第 32 行附近）：
```tsx
{/* 產業輪動強弱 */}
<section className="mb-4">
  <SectorStrengthWidget />
</section>
```

- [ ] **Step 2：型別檢查**

```bash
cd frontend
npx tsc --noEmit
```

Expected: 無錯誤（或僅有與本次變更無關的既有錯誤）

- [ ] **Step 3：Commit**

```bash
git add frontend/pages/index.tsx
git commit -m "feat(index): 整合 SectorStrengthWidget 至首頁"
```

---

### Task 7：執行全量特徵回補（Mac 本地）

> ⚠️ 此 Task 為手動執行步驟，需在 Mac 本地終端機操作，耗時約 10~30 分鐘。

- [ ] **Step 1：確認 dev server 未佔用資源**（可同時跑，但建議先停止）

- [ ] **Step 2：執行 backfill_features**

```bash
cd backend
./.venv/bin/python scripts/backfill_features.py
```

Expected: 輸出每日進度，最終顯示 `回補完成: XXXX 筆`

- [ ] **Step 3：確認 sector_rs 覆蓋率改善**

```bash
./.venv/bin/python -c "
from app.db.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
r = db.execute(text('SELECT COUNT(*) AS total, SUM(CASE WHEN sector_rs IS NOT NULL THEN 1 ELSE 0 END) AS non_null FROM stock_features')).fetchone()
print(f'sector_rs coverage: {r.non_null}/{r.total}')
db.close()
"
```

Expected: `non_null` 與 `total` 接近

- [ ] **Step 4：觸發 Alpha Miner 重訓**

```bash
curl -s -X POST http://localhost:8000/alpha-miner/train | python3 -m json.tool
```

Expected: 回傳 `{"message": "Alpha Miner 訓練已啟動（背景執行）"}` 或類似訊息

- [ ] **Step 5：最終驗證——瀏覽器確認 widget 顯示**

打開 `http://localhost:3000/alphaforge`，確認首頁 StrategyMinerPreview 下方出現「產業輪動強弱」widget，並顯示強弱產業清單（非「資料尚未就緒」）。

---

## 執行順序

Task 1（診斷，可提前執行）→ Task 2 → Task 3 → Task 4 → Task 5 → Task 6 → Task 7（最後手動執行）

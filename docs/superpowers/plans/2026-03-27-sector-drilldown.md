# 產業 Drill-Down 實作計畫

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在首頁 SectorStrengthWidget 新增可點擊的產業 Accordion，展開後顯示該產業 Top 10 個股的 20 日漲幅排行。

**Architecture:** 新增一個後端端點 `GET /market/sector-stocks`，複用現有兩日收盤價計算邏輯，回傳指定產業的 Top N 個股；前端在 SectorStrengthWidget 中加入展開/收合互動，lazy load 個股資料並快取於元件 state。

**Tech Stack:** FastAPI, SQLAlchemy, Pandas, Next.js 14 (Pages Router), TypeScript, Axios, Tailwind CSS

---

## 檔案異動清單

| 動作 | 檔案 | 說明 |
|---|---|---|
| 修改 | `backend/app/schemas/market.py` | 新增 `SectorStockItem`, `SectorStocksResponse` |
| 修改 | `backend/app/services/market_service.py` | 新增快取變數 + `get_sector_stocks()` + `_compute_sector_stocks()` |
| 修改 | `backend/app/api/endpoints/market.py` | 新增 `GET /sector-stocks` 路由 |
| 新增 | `backend/tests/test_sector_stocks.py` | 後端測試 |
| 修改 | `frontend/components/SectorStrengthWidget.tsx` | 加入 Accordion 互動 |

---

## Task 1：新增後端 Schema

**Files:**
- Modify: `backend/app/schemas/market.py`

- [ ] **Step 1：在 market.py 末端新增兩個 class**

開啟 `backend/app/schemas/market.py`，在最後一行後新增：

```python
class SectorStockItem(BaseModel):
    stock_id: str
    name: str
    ret20: float


class SectorStocksResponse(BaseModel):
    industry: str
    date: Optional[str]
    stocks: List[SectorStockItem]
```

- [ ] **Step 2：確認語法正確**

```bash
cd backend && ./.venv/bin/python -c "from app.schemas.market import SectorStockItem, SectorStocksResponse; print('OK')"
```

Expected output: `OK`

- [ ] **Step 3：Commit**

```bash
git add backend/app/schemas/market.py
git commit -m "feat(schema): 新增 SectorStockItem / SectorStocksResponse"
```

---

## Task 2：後端 Service + 測試

**Files:**
- Modify: `backend/app/services/market_service.py`
- Create: `backend/tests/test_sector_stocks.py`

- [ ] **Step 1：先寫失敗測試**

建立 `backend/tests/test_sector_stocks.py`：

```python
import pytest
from app.services.market_service import MarketService
from app.schemas.market import SectorStocksResponse


def test_get_sector_stocks_returns_correct_schema():
    """回傳格式必須符合 SectorStocksResponse"""
    # 先取 sector-strength 找一個有效的產業名稱
    strength = MarketService.get_sector_strength()
    if not strength.top:
        pytest.skip("無產業資料，跳過")
    industry = strength.top[0].industry
    result = MarketService.get_sector_stocks(industry, top=10)
    assert isinstance(result, SectorStocksResponse)
    assert result.industry == industry
    assert isinstance(result.stocks, list)
    assert len(result.stocks) <= 10


def test_get_sector_stocks_sorted_descending():
    """個股應按 ret20 由高到低排序"""
    strength = MarketService.get_sector_strength()
    if not strength.top:
        pytest.skip("無產業資料，跳過")
    result = MarketService.get_sector_stocks(strength.top[0].industry)
    if len(result.stocks) >= 2:
        assert result.stocks[0].ret20 >= result.stocks[1].ret20


def test_get_sector_stocks_invalid_industry():
    """不存在的產業應回傳空清單，不拋例外"""
    result = MarketService.get_sector_stocks("不存在的產業_XXXX")
    assert isinstance(result, SectorStocksResponse)
    assert result.stocks == []


def test_get_sector_stocks_cache():
    """第二次呼叫應命中快取（同一產業，TTL 內）"""
    strength = MarketService.get_sector_strength()
    if not strength.top:
        pytest.skip("無產業資料，跳過")
    industry = strength.top[0].industry
    r1 = MarketService.get_sector_stocks(industry)
    r2 = MarketService.get_sector_stocks(industry)
    # 快取命中時回傳同一個物件（is）
    assert r1 is r2
```

- [ ] **Step 2：確認測試失敗（`get_sector_stocks` 尚未實作）**

```bash
cd backend && ./.venv/bin/python -m pytest tests/test_sector_stocks.py -v 2>&1 | head -20
```

Expected: `AttributeError: type object 'MarketService' has no attribute 'get_sector_stocks'`

- [ ] **Step 3：在 market_service.py 新增快取變數**

在檔案頂部找到 `_sector_cache_time` 所在行（約第 21 行），在其後新增：

```python
_sector_stocks_cache: Dict[str, "SectorStocksResponse"] = {}
_sector_stocks_cache_time: Dict[str, datetime] = {}
```

- [ ] **Step 4：更新 import（在 market_service.py 第 7 行）**

將：
```python
from app.schemas.market import RankingItem, MarketRankingResponse, SectorStrengthItem, SectorStrengthResponse
```
改為：
```python
from app.schemas.market import (
    RankingItem, MarketRankingResponse,
    SectorStrengthItem, SectorStrengthResponse,
    SectorStockItem, SectorStocksResponse,
)
```

- [ ] **Step 5：在 MarketService class 末端新增兩個方法**

在 `_compute_sector_strength()` 方法之後（約第 268 行之後）新增：

```python
    @staticmethod
    def get_sector_stocks(industry: str, top: int = 10) -> SectorStocksResponse:
        """取得指定產業的 Top N 個股（按 20 日漲幅降序），附 5 分鐘快取。"""
        global _sector_stocks_cache, _sector_stocks_cache_time
        now = datetime.now()
        if (
            industry in _sector_stocks_cache
            and industry in _sector_stocks_cache_time
            and (now - _sector_stocks_cache_time[industry]).total_seconds() < _CACHE_TTL_SECONDS
        ):
            return _sector_stocks_cache[industry]

        result = MarketService._compute_sector_stocks(industry, top)
        _sector_stocks_cache[industry] = result
        _sector_stocks_cache_time[industry] = now
        return result

    @staticmethod
    def _compute_sector_stocks(industry: str, top: int = 10) -> SectorStocksResponse:
        """查詢指定產業的個股 20 日報酬，回傳 Top N。"""
        from sqlalchemy import func
        import logging
        logger = logging.getLogger(__name__)
        db = SessionLocal()
        try:
            # 最近 21 個有效交易日
            latest_dates = (
                db.query(StockPrice.date)
                .filter(~StockPrice.stock_id.startswith("^"))
                .group_by(StockPrice.date)
                .having(func.count(StockPrice.stock_id) > 100)
                .order_by(StockPrice.date.desc())
                .limit(25)
                .all()
            )
            if len(latest_dates) < 21:
                return SectorStocksResponse(industry=industry, date=None, stocks=[])

            target_date = latest_dates[0][0]
            date_20d_ago = latest_dates[20][0]

            # 取得指定產業的個股清單與名稱
            stocks_in_industry = (
                db.query(Stock.stock_id, Stock.name, Stock.industry)
                .filter(Stock.industry == industry)
                .all()
            )
            if not stocks_in_industry:
                return SectorStocksResponse(
                    industry=industry, date=target_date.isoformat(), stocks=[]
                )

            stock_ids = [r.stock_id for r in stocks_in_industry]
            name_map = {r.stock_id: r.name for r in stocks_in_industry}

            # 取兩日收盤價
            prices = (
                db.query(StockPrice.stock_id, StockPrice.date, StockPrice.close)
                .filter(
                    StockPrice.date.in_([target_date, date_20d_ago]),
                    StockPrice.stock_id.in_(stock_ids),
                )
                .all()
            )
            price_dict = {(r.stock_id, r.date): float(r.close) for r in prices}

            # 計算 ret20 並排序
            records = []
            for sid in stock_ids:
                curr = price_dict.get((sid, target_date))
                prev = price_dict.get((sid, date_20d_ago))
                if curr is not None and prev is not None and prev > 0:
                    ret20 = round((curr - prev) / prev * 100, 2)
                    records.append({
                        'stock_id': sid,
                        'name': name_map.get(sid, sid),
                        'ret20': ret20,
                    })

            records.sort(key=lambda x: x['ret20'], reverse=True)
            top_records = records[:top]

            stocks = [
                SectorStockItem(
                    stock_id=r['stock_id'],
                    name=r['name'],
                    ret20=r['ret20'],
                )
                for r in top_records
            ]
            return SectorStocksResponse(
                industry=industry,
                date=target_date.isoformat(),
                stocks=stocks,
            )
        except Exception as e:
            logger.error(f"[MarketService] sector_stocks error: {e}")
            return SectorStocksResponse(industry=industry, date=None, stocks=[])
        finally:
            db.close()
```

- [ ] **Step 6：執行測試，確認全數通過**

```bash
cd backend && ./.venv/bin/python -m pytest tests/test_sector_stocks.py -v
```

Expected:
```
PASSED tests/test_sector_stocks.py::test_get_sector_stocks_returns_correct_schema
PASSED tests/test_sector_stocks.py::test_get_sector_stocks_sorted_descending
PASSED tests/test_sector_stocks.py::test_get_sector_stocks_invalid_industry
PASSED tests/test_sector_stocks.py::test_get_sector_stocks_cache
```

- [ ] **Step 7：確認既有測試不受影響**

```bash
cd backend && ./.venv/bin/python -m pytest tests/test_sector_strength.py -v
```

Expected: 全部 PASSED

- [ ] **Step 8：Commit**

```bash
git add backend/app/services/market_service.py backend/tests/test_sector_stocks.py
git commit -m "feat(market): 新增 get_sector_stocks() 與快取機制"
```

---

## Task 3：後端 API 端點

**Files:**
- Modify: `backend/app/api/endpoints/market.py`

- [ ] **Step 1：更新 market.py 的 import**

在 `backend/app/api/endpoints/market.py` 第 15 行，將：

```python
from app.schemas.market import MarketSummary, AlphaStats, SectorStrengthResponse
```

改為：

```python
from app.schemas.market import MarketSummary, AlphaStats, SectorStrengthResponse, SectorStocksResponse
```

- [ ] **Step 2：在檔案末端新增路由**

在 `get_sector_strength()` 路由後新增：

```python
@router.get("/sector-stocks", response_model=SectorStocksResponse)
def get_sector_stocks(industry: str, top: int = 10):
    """指定產業的個股 20 日漲幅排行（Top N）"""
    from app.services.market_service import MarketService
    return MarketService.get_sector_stocks(industry, top=min(top, 20))
```

- [ ] **Step 3：啟動後端確認端點存在**

```bash
cd backend && ./.venv/bin/python -c "
from app.api.endpoints.market import router
routes = [r.path for r in router.routes]
assert '/sector-stocks' in routes, f'Missing route. Got: {routes}'
print('Route OK')
"
```

Expected: `Route OK`

- [ ] **Step 4：Commit**

```bash
git add backend/app/api/endpoints/market.py
git commit -m "feat(api): 新增 GET /market/sector-stocks 端點"
```

---

## Task 4：前端 SectorStrengthWidget 改版

**Files:**
- Modify: `frontend/components/SectorStrengthWidget.tsx`

- [ ] **Step 1：用以下完整內容取代 SectorStrengthWidget.tsx**

```tsx
import React, { useEffect, useState, useCallback } from 'react'
import api from '../lib/api'

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

interface SectorStockItem {
  stock_id: string
  name: string
  ret20: number
}

const SectorIcon = () => (
  <svg viewBox="0 0 24 24" width={14} height={14} className="fill-current">
    <path d="M3,13H5V11H3V13M3,17H5V15H3V17M3,9H5V7H3V9M7,13H21V11H7V13M7,17H21V15H7V17M7,7V9H21V7H7Z" />
  </svg>
)

export default function SectorStrengthWidget() {
  const [data, setData] = useState<SectorStrengthData | null>(null)
  const [loading, setLoading] = useState(true)
  const [expandedIndustry, setExpandedIndustry] = useState<string | null>(null)
  const [stocksCache, setStocksCache] = useState<Map<string, SectorStockItem[]>>(new Map())
  const [loadingIndustry, setLoadingIndustry] = useState<string | null>(null)

  useEffect(() => {
    api.get('/market/sector-strength')
      .then(r => {
        setData(r.data)
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }, [])

  const handleIndustryClick = useCallback(async (industry: string) => {
    if (expandedIndustry === industry) {
      setExpandedIndustry(null)
      return
    }
    setExpandedIndustry(industry)
    if (stocksCache.has(industry)) return
    setLoadingIndustry(industry)
    try {
      const res = await api.get('/market/sector-stocks', { params: { industry, top: 10 } })
      setStocksCache(prev => new Map(prev).set(industry, res.data.stocks ?? []))
    } catch {
      setStocksCache(prev => new Map(prev).set(industry, []))
    } finally {
      setLoadingIndustry(null)
    }
  }, [expandedIndustry, stocksCache])

  const formatRs = (val: number) => (val >= 0 ? `+${val.toFixed(1)}` : val.toFixed(1))

  const renderStockList = (industry: string) => {
    const isLoading = loadingIndustry === industry
    const stocks = stocksCache.get(industry)
    if (isLoading) {
      return (
        <div className="mt-1 mb-2 pl-2 border-l border-zinc-700/60 space-y-1 py-1">
          {[0, 1, 2].map(i => (
            <div key={i} className="h-3 bg-zinc-700/40 rounded animate-pulse" />
          ))}
        </div>
      )
    }
    if (!stocks || stocks.length === 0) {
      return (
        <div className="mt-1 mb-2 pl-2 border-l border-zinc-700/60">
          <p className="text-[10px] text-zinc-500 py-1">無資料</p>
        </div>
      )
    }
    return (
      <div className="mt-1 mb-2 pl-2 border-l border-zinc-700/60 space-y-0.5 py-1">
        {stocks.map((s, idx) => (
          <div key={s.stock_id} className="flex items-center gap-1 text-[10px] font-mono">
            <span className="text-zinc-600 w-3 shrink-0">{idx + 1}</span>
            <span className="text-zinc-500 w-10 shrink-0">{s.stock_id}</span>
            <span className="text-zinc-300 flex-1 truncate">{s.name}</span>
            <span className={s.ret20 >= 0 ? 'text-emerald-400' : 'text-rose-400'}>
              {s.ret20 >= 0 ? `+${s.ret20.toFixed(1)}` : s.ret20.toFixed(1)}%
            </span>
          </div>
        ))}
      </div>
    )
  }

  const renderIndustryList = (items: SectorItem[], side: 'top' | 'bottom') => (
    <div>
      <p className={`text-xs font-medium mb-2 ${side === 'top' ? 'text-emerald-400' : 'text-rose-400'}`}>
        {side === 'top' ? '近20日漲幅居前' : '近20日漲幅居後'}
      </p>
      <div className="space-y-0.5">
        {items.map((item) => {
          const isExpanded = expandedIndustry === item.industry
          return (
            <div key={item.industry}>
              <div
                className="flex items-center justify-between cursor-pointer hover:opacity-75 transition-opacity py-0.5"
                onClick={() => handleIndustryClick(item.industry)}
              >
                <span className={`text-xs text-zinc-300 truncate max-w-[100px] ${isExpanded ? 'underline decoration-dotted underline-offset-2' : ''}`}>
                  {item.industry}
                </span>
                <span className={`text-xs font-mono ml-1 ${side === 'top' ? 'text-emerald-400' : 'text-rose-400'}`}>
                  {formatRs(item.median_rs)}
                </span>
              </div>
              {isExpanded && renderStockList(item.industry)}
            </div>
          )
        })}
      </div>
    </div>
  )

  if (loading) {
    return (
      <div className="bg-zinc-900/60 border border-white/10 rounded-2xl px-4 py-3">
        <div className="flex justify-between items-center mb-3 pb-2 border-b border-zinc-800/40">
          <span className="text-amber-400 text-sm font-bold flex items-center gap-1.5">
            <SectorIcon />
            產業輪動強弱
          </span>
        </div>
        <p className="text-xs text-zinc-500">載入中...</p>
      </div>
    )
  }

  if (!data || !data.date || (data.top.length === 0 && data.bottom.length === 0)) {
    return (
      <div className="bg-zinc-900/60 border border-white/10 rounded-2xl px-4 py-3">
        <div className="flex justify-between items-center mb-3 pb-2 border-b border-zinc-800/40">
          <span className="text-amber-400 text-sm font-bold flex items-center gap-1.5">
            <SectorIcon />
            產業輪動強弱
          </span>
        </div>
        <p className="text-xs text-zinc-500">產業資料尚未就緒，請先執行特徵回補</p>
      </div>
    )
  }

  return (
    <div className="bg-zinc-900/60 border border-white/10 rounded-2xl px-4 py-3">
      <div className="flex justify-between items-center mb-3 pb-2 border-b border-zinc-800/40">
        <span className="text-amber-400 text-sm font-bold flex items-center gap-1.5">
          <SectorIcon />
          產業輪動強弱
        </span>
        <span className="text-zinc-400 text-[10px] font-mono font-normal">{data.date}</span>
      </div>

      <div className="grid grid-cols-2 gap-3">
        {renderIndustryList(data.top, 'top')}
        {renderIndustryList(data.bottom, 'bottom')}
      </div>
    </div>
  )
}
```

- [ ] **Step 2：型別檢查**

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep -i "SectorStrength\|sector" || echo "No type errors"
```

Expected: `No type errors`

- [ ] **Step 3：Commit**

```bash
git add frontend/components/SectorStrengthWidget.tsx
git commit -m "feat(ui): SectorStrengthWidget 新增產業 drill-down accordion"
```

---

## Task 5：整合驗收

- [ ] **Step 1：執行所有後端測試**

```bash
cd backend && ./.venv/bin/python -m pytest tests/test_sector_stocks.py tests/test_sector_strength.py -v
```

Expected: 全部 PASSED，共 9 tests

- [ ] **Step 2：手動驗收清單**

啟動後端（`cd backend && ./.venv/bin/python main.py`）與前端（`cd frontend && INTERNAL_API_URL=http://localhost:8000 npm run dev`），開啟 `http://localhost:3000/alphaforge`，確認：

1. 首頁的「產業輪動強弱」Widget 正常顯示（強弱各 5 個產業）
2. 點擊強勢產業名稱 → 展開 Top 10 個股清單，漲幅為 emerald 綠色
3. 點擊弱勢產業名稱 → 展開 Top 10 個股清單，跌幅為 rose 紅色
4. 再次點擊已展開的產業 → 清單收合
5. 點擊另一個產業 → 前一個自動收合，新的展開
6. 重複點擊同一產業（第二次）→ Network tab 無新請求（cache 命中）
7. 首頁初始載入 → Network tab 無 `/market/sector-stocks` 請求

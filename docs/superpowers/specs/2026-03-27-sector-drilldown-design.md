# 產業強弱 Drill-Down 設計文件

**日期：** 2026-03-27
**範圍：** Phase 6 延伸——SectorStrengthWidget 新增個股展開功能

---

## 背景

首頁 `SectorStrengthWidget` 已顯示強弱各 5 個產業與其 20 日報酬中位數。使用者看到「半導體最強」後，沒有辦法直接得知該產業內哪些個股值得研究。本功能補足這個缺口。

Alpha Miner 已有 `sector_rs` 因子（5 個組合策略），不需要再擴充因子庫。

---

## 設計目標

- 點擊產業名稱，在 Widget 內展開該產業 Top 10 個股（按 20 日漲幅排序）
- 不新增頁面，不跳頁
- 首頁載入維持輕量（lazy load）

---

## 後端

### 新端點

```
GET /market/sector-stocks?industry={名稱}&top={N}
```

| 參數 | 型別 | 預設 | 說明 |
|---|---|---|---|
| `industry` | `str` | 必填 | 產業名稱，如 `半導體` |
| `top` | `int` | `10` | 最多 20 |

### 回應 Schema（新增至 `backend/app/schemas/market.py`）

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

### 計算邏輯

複用 `_compute_sector_strength()` 的現有兩日收盤價邏輯：
1. 取最近兩個有效交易日（個股數 > 100）
2. 計算 `ret20 = (curr - prev) / prev * 100`
3. 過濾指定 `industry`
4. 按 `ret20` 降序取 Top N
5. 從 `Stock.name` 取得股票名稱

### 快取

`get_sector_stocks()` 維護獨立的 module-level dict 快取：`_sector_stocks_cache: Dict[str, SectorStocksResponse]`，key 為產業名稱，TTL 同樣 5 分鐘。不與 `sector-strength` 共用底層資料（保持獨立，實作更簡單）。

### 實作位置

- Schema：`backend/app/schemas/market.py`
- Service：`backend/app/services/market_service.py`（新增 `get_sector_stocks()` 靜態方法）
- Endpoint：`backend/app/api/endpoints/market.py`（新增路由）

---

## 前端

### 元件修改：`SectorStrengthWidget.tsx`

**State 新增：**
```typescript
const [expandedIndustry, setExpandedIndustry] = useState<string | null>(null)
const [stocksCache, setStocksCache] = useState<Map<string, SectorStockItem[]>>(new Map())
const [loadingIndustry, setLoadingIndustry] = useState<string | null>(null)
```

**互動邏輯：**
1. 點擊產業名稱 → 若已展開則收合（`expandedIndustry = null`）；若未展開則：
   - 若 cache 有資料：直接展開
   - 若 cache 無資料：呼叫 API，顯示 loading，回應後寫入 cache 並展開
2. 同時只展開一個產業（切換時自動關閉前一個）

**展開後 UI：**
```
  #1  2330  台積電    +12.5%
  #2  2303  聯電       +8.2%
  ...
```
- 正報酬：`text-emerald-400`；負報酬：`text-rose-400`；零值：`text-zinc-400`
- 字體：`text-xs font-mono`
- Loading 狀態：3 行 skeleton（`bg-zinc-700/40 animate-pulse`）

**產業名稱樣式：**
- 加上 `cursor-pointer hover:text-amber-300 transition-colors`
- 展開中的產業名稱底線標示（`underline decoration-dotted`）

**元件大小預估：** 現有 108 行 → 完成後約 180–200 行（符合 300 行限制）

---

## 不在範圍內

- 不跳頁、不新增頁面
- 不顯示 `sector_rs`（只顯示 `ret20`）
- 不顯示「查看更多」（固定 Top 10）
- 不修改 Alpha Miner 因子庫

---

## 驗收條件

1. 點擊強勢/弱勢產業名稱，展開 Top 10 個股清單
2. 再次點擊同一產業，清單收合
3. 點擊另一產業，前一個自動收合、新的展開
4. 同一產業第二次點擊不重複打 API（cache 命中）
5. 個股漲幅正負配色正確（emerald / rose）
6. 首頁初始載入無額外請求（lazy）

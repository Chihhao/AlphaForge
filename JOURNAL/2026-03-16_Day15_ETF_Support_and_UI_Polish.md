# AlphaForge 學習日誌 - Day 15
**日期**：2026-03-16
**主題**：ETF 個股頁支援 + UI 細節打磨（持有期標籤、X 軸修復、書本 icon）

---

## 學習重點 (The "Why")

### 1. ETF 為什麼沒有基本面資料？

0050 查詢後基本面區塊全部顯示 `---`。原因：TWSE 估值 API（`/exchangeReport/BWIBBU_d`）只回傳上市**普通股**的 PE/PB/ROE，ETF 不在其中，所以 `stock_fundamentals` 資料表根本沒有 ETF 的記錄。

**解法**：在 `get_stock_quote()` 中，先呼叫 `yfinance.Ticker.info`，判斷 `quoteType == 'ETF'`。若為 ETF，改從 yfinance 填入：

| 欄位 | yfinance 來源 | 說明 |
|------|-------------|------|
| `pe_ratio` | `trailingPE` | ETF 的成分股加權 PE |
| `yield_rate` | `dividendYield` | 年化殖利率（已是百分比值） |
| `total_assets` | `totalAssets` | 基金規模（元），前端除以 1e8 轉換為億 |
| `fund_family` | `fundFamily` | 英文基金公司名稱 |
| `fundamental_updated_at` | `datetime.utcnow()` | 即時查詢時間 |

**重要細節**：`dividendYield` 在 yfinance 裡對台股 ETF 回傳的是百分比值（如 `1.68` 代表 1.68%），不是小數（不是 `0.0168`）。這與美股 ETF 的回傳格式不同，要特別注意。

### 2. 前端如何判斷一支股票是 ETF？

不依賴字串判斷（如「股票代號 0 開頭」），而是看後端回傳的 `total_assets` 是否有值：

```tsx
if (quote?.total_assets != null) {
  // ETF 模式：顯示基金規模、基金公司
} else {
  // 股票模式：顯示營收、EPS 年增率
}
```

同時，ETF 沒有意義的欄位（`股價淨值比`、`權益報酬率`）用條件渲染隱藏，避免 `---` 造成誤解。

### 3. 基金公司名稱中文化

yfinance 回傳英文名稱（`Yuanta Securities Inv Trust Co., Ltd`），在手機上會被截斷。建立前端對照表 `FUND_FAMILY_MAP`：

```tsx
const FUND_FAMILY_MAP: Record<string, string> = {
  'Yuanta': '元大投信',
  'Cathay': '國泰投信',
  'Fubon': '富邦投信',
  // ... 12 家主要投信
}
```

用 `includes()` 做模糊比對，找不到時 fallback 顯示原始英文名稱。這是「最小可行解」——不用維護完整 DB，只需涵蓋常見 ETF 發行商。

### 4. X 軸標籤重疊的根本原因

K 線圖右側出現 `3/3`、`3/16` 重疊。根本原因：原本為了「確保最新一筆永遠顯示」加了一個自訂 HTML overlay（`lastLabelRef`），它疊加在 lightweight-charts 原生 X 軸標籤上，當最後一筆恰好在自動 tick 位置附近時就會重疊。

**解法**：直接移除自訂 overlay，完全信任 lightweight-charts 的內建標籤管理（它本身就有防重疊邏輯）。

**教訓**：不要繞過 library 的機制自己實作，library 的原生行為往往更健壯。

### 5. APScheduler 排程補漏問題

（昨日延伸）容器在 17:05 才啟動，所有已排程的任務（15:00、15:30、16:30、17:00）一律不補跑。APScheduler `BackgroundScheduler` 是 in-process 排程，沒有「錯過任務重跑」的機制。

**這次影響**：盤後資料未自動同步，Alpha Miner 訓練資料仍是 3/12 的舊資料。
**解法**：手動 `docker exec -d` 執行補資料腳本 + POST `/alpha-miner/train`。

另外修正了 `retrain_alpha_miner` 的排程 bug：原本只呼叫 `invalidate_cache()`（清記憶體），但沒有刪除 DB 快照，導致每次重啟後 `get_strategies()` 找到今日快照就直接回傳，永遠不重訓。

```python
def retrain_alpha_miner(db):
    db.execute(sa_delete(AlphaMinerSnapshot))  # 必須先刪 DB 快照
    db.commit()
    AlphaMinerService.invalidate_cache()
    AlphaMinerService.get_strategies(db)       # 觸發重訓
```

---

## 開發成果

### 後端

**`schemas/stock.py`**：`StockQuote` 新增兩個選填欄位：
```python
total_assets: Optional[float] = None   # ETF 基金規模（元）
fund_family: Optional[str] = None      # ETF 基金公司（英文）
```

**`services/stock_service.py`**：`get_stock_quote()` ETF 分支：
- 偵測 `info['quoteType'] == 'ETF'`
- 填入 pe/yield/total_assets/fund_family/fundamental_updated_at
- 跳過 DB 查詢（ETF 不在 stock_fundamentals 表中）

### 前端

**`pages/stock/[id].tsx`**：
- 新增 `FUND_FAMILY_MAP` + `formatFundFamily()` 函式（12 家投信）
- 基本面區塊三欄：ETF 時隱藏 PB/ROE，第三欄換成「基金規模(億)」+「基金公司」
- ETF 顯示「基本面資料更新：{今日日期}」

**`components/TVChart.tsx`**：
- 移除 `lastLabelRef` 自訂 overlay 與相關邏輯
- 清除 unused import `Logical`

**`components/Layout.tsx`**：
- 隱藏右上角書本 icon 按鈕

### 訊號頁與策略頁持有期標籤（承昨日）

- 訊號頁：股票名稱與代號併為同一行，持有期標籤（5日後/10日後/30日後）置於觸發膠囊左側
- 策略頁：MobileCard 加入 `dimLabel` prop，置於「顯著/不顯著」badge 左側

---

## 遇到的問題與解法

### ETF 基金公司英文名稱被截斷
**原因**：`Yuanta Securities Inv Trust Co., Ltd` 在手機寬度下超出容器。
**解法**：前端 `FUND_FAMILY_MAP` 對照表轉中文簡稱，找不到時 fallback 英文。

### X 軸標籤右側重疊（3/3 與 3/16）
**原因**：自訂 `lastLabelRef` HTML overlay 與 lightweight-charts 原生 tick 標籤位置衝突。
**解法**：刪除整個 overlay 機制，交由 library 管理。

### chart section 底部 gap 問題
**狀況**：原本 chart section 有 `p-4` 底部 padding，圖表下方出現空白。改成 `pb-0` 後兩個 section border 黏在一起像粗線。
**決定**：維持原本 `p-4`，保留視覺上的適當間距。UI 設計有時候「沒有問題」比「改了反而更難看」更重要。

---

## 今日部署記錄

- Commit `e5c38e8`：訊號頁與策略頁持有期標籤
- Commit `6b5f620`：ETF 支援 + X 軸修復 + 書本 icon 隱藏

---

## 接下來可以做的方向

- **Phase 6**：外資持股比例變化因子（與單日買賣超不同，需要 TWSE 持股統計 API）
- **Phase 6**：產業相對強度（需建立 TWSE 產業代碼對照表）
- **訊號準確率追蹤**：記錄每天訊號，30 日後回測實際漲跌
- **ETF 追蹤指數顯示**：yfinance `info['category']` 目前對台股 ETF 回傳 None，需另尋資料源

---

## 今日心得

> 「今天的工作以『補洞』為主：ETF 沒資料、標籤重疊、UI 細節。
>
> ETF 支援讓我思考一個問題：同樣是 `get_stock_quote()` 的呼叫，輸入 2330 和 0050 應該回傳相同結構但不同語意的資料。與其在前端做大量的條件判斷，不如讓後端在 schema 層面就設計好『股票有哪些欄位、ETF 有哪些欄位』。這次的做法是共用 `StockQuote`，用 `total_assets` 是否有值來區分 ETF，算是夠用但不夠優雅的解。
>
> X 軸標籤重疊的修復也給了一個教訓：過去加 `lastLabelRef` overlay 是為了解決『最後一筆標籤不顯示』的問題，但這個問題可能根本不存在，或是用更小的改動就能解決。當我們為了修一個問題加了額外機制，卻引入了新問題，這時最好的做法通常是刪除那個機制、重新信任底層 library。」

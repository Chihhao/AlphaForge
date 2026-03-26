# Phase 6：產業輪動分析 設計文件

**日期**：2026-03-26
**範疇**：資料回補（B）+ 首頁產業強弱 Widget（A）

---

## 背景

Alpha Miner 的因子庫中，`sector_rs`（產業相對強度）、`foreign_hold_pct`（外資持股比率）、`foreign_hold_chg_5d`（外資持股5日變化）三個 Phase 6 因子雖已定義於程式碼，但：

1. `stock_features` 歷史資料中這些欄位可能多為 NULL（從未全量回補）
2. 前端沒有任何產業輪動的視覺化呈現

本 Phase 6 目標：補齊資料 + 新增首頁產業強弱 widget。

---

## Section 1：資料層

### 1.1 診斷

執行 SQL 查詢，分兩層統計：
1. `stock_chip_data.foreign_hold_pct`：歷史日期覆蓋率（這是來源資料，NULL 在此層才是根本問題）
2. `stock_features` 中 `sector_rs`、`foreign_hold_pct` 的 NULL 比率與日期覆蓋範圍

### 1.2 foreign_hold_pct 覆蓋率決策

- 若 `stock_chip_data.foreign_hold_pct` 歷史覆蓋率 ≥ 80%：直接進入回補步驟
- 若 < 80%：降級——`foreign_hold_pct` 與 `foreign_hold_chg_5d` 在此次 Alpha Miner 重訓中標記為資料不足，以 `foreign_net_buy` 作為代理因子（不補爬，TWSE 歷史持股比率端點可能不支援歷史查詢）

### 1.3 全量回補

在 Mac 本地執行：

```bash
cd backend
./.venv/bin/python scripts/backfill_features.py
```

`feature_service.backfill()` 已支援 `sector_rs`（`Stock.industry` 分組）與 `foreign_hold_pct`（從 `stock_chip_data` 帶入）的計算，重跑即可。

### 1.4 Alpha Miner 重訓

`backfill_features` 完成後，在 Mac 本地透過 API 觸發重訓：

```
POST /alpha-miner/train
```

（排程器 `scheduler.py` 每日 17:10 亦會自動觸發）

---

## Section 2：後端 API

### 端點

```
GET /market/sector-strength
```

**參數**：無（預設回傳最近一個交易日）

**實作位置**：
- `backend/app/api/endpoints/market.py`（新增路由）
- `backend/app/services/market_service.py`（新增 `get_sector_strength()` 方法）
- `backend/app/schemas/market.py`（新增 `SectorStrengthItem`、`SectorStrengthResponse` Pydantic model）

**邏輯**：
1. 查詢 `stock_features` 最近一個有效交易日——定義為「當日 `stock_id` 數量 > 100」（與 `market_service.py` 既有慣例一致，避免資料品質差的日期）
2. Join `stocks` 表取得每股的 `industry`
3. 按 `industry` 分組，計算各產業的 `sector_rs` 中位數與股票數
4. 過濾掉 `industry` 為 NULL 或 `stock_count < 3` 的產業
5. 排序，取前 5 強（median_rs 最高）與後 5 弱（median_rs 最低）
6. 採用 in-memory 快取（與既有 market_service 一致），TTL 5 分鐘

**回傳格式**：

```json
{
  "date": "2026-03-26",
  "top": [
    { "industry": "半導體", "median_rs": 8.42, "stock_count": 45 },
    { "industry": "電子零組件", "median_rs": 6.21, "stock_count": 38 }
  ],
  "bottom": [
    { "industry": "航運", "median_rs": -5.13, "stock_count": 12 },
    { "industry": "紡織", "median_rs": -4.31, "stock_count": 9 }
  ]
}
```

**錯誤處理**：若無有效資料，回傳 `{ "date": null, "top": [], "bottom": [] }`，前端顯示「資料尚未就緒」。

---

## Section 3：前端 Widget

### 元件

**檔案**：`frontend/components/SectorStrengthWidget.tsx`（預估 ≤ 120 行）

**首頁整合**：`frontend/pages/index.tsx`，插入 `StrategyMinerPreview` 下方

### UI 規格

- 標題：「產業輪動強弱」+ 右側顯示資料日期
- 雙欄佈局：左欄「強勢產業」/ 右欄「弱勢產業」，各 5 筆
- 強勢用 `emerald-400` 文字，弱勢用 `rose-400` 文字
- 數字為 `median_rs`（%），顯示格式：`+8.4` / `-5.1`
- 背景：`bg-zinc-800/60`，配合全站玻璃擬態風格
- 產業名稱為純文字，不可點擊（`signals.tsx` 產業篩選器不在本 phase 範疇內）
- 資料用 SWR 一次性 fetch（無 `refreshInterval`，因 `sector_rs` 為每日更新，盤中輪詢無意義）

### 無資料狀態

顯示灰色文字「產業資料尚未就緒，請先執行特徵回補」。

---

## 實作順序

1. 診斷資料覆蓋率（SQL 查詢）
2. 在 Mac 本地執行 `backfill_features.py` 全量回補
3. 後端新增 `GET /market/sector-strength` 端點
4. 前端新增 `SectorStrengthWidget` 元件
5. 首頁整合 widget
6. 在 Mac 本地執行 Alpha Miner 重訓

---

## 不在範疇內

- 補爬 `foreign_hold_pct` 歷史資料（TWSE 端點限制）
- 產業獨立頁面 `/sector`
- 熱力圖視覺化
- `signals.tsx` 的產業篩選器（widget 中產業名稱不可點擊）

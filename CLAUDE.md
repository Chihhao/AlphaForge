# CLAUDE.md

本文件為 Claude Code (claude.ai/code) 在此專案中工作時的指引。

## 專案概述

AlphaForge 是一個台灣股市分析與模擬交易平台，定位為股票新手的學習型工具。結合量化分析（技術指標、基本面數據）與教育元件，將專業術語以「白話文」方式呈現。

## 開發指令

### 後端 (FastAPI / Python)
```bash
cd backend
./.venv/bin/python main.py                    # 啟動開發伺服器 (port 8000)
./.venv/bin/pip install -r requirements.txt    # 安裝依賴
./.venv/bin/python scripts/seed_market_data.py # 填充本地資料庫（近期數據）
./.venv/bin/python scripts/backfill_prices.py  # 回補歷史 OHLCV 數據
./.venv/bin/python scripts/backfill_features.py    # 計算每日指標快照
./.venv/bin/python scripts/backfill_fundamentals.py # 同步基本面數據
```

### 前端 (Next.js 14 / TypeScript)
```bash
cd frontend
npm install                                           # 安裝依賴
INTERNAL_API_URL=http://localhost:8000 npm run dev     # 啟動開發伺服器 (port 3000)
npm run build                                         # 正式環境建置
npm run lint                                          # ESLint 檢查
npm run clean                                         # 清除 .next 快取
```

**重要**：前端網址必須包含 `/alphaforge` 子路徑（由 `next.config.js` 中的 `basePath` 設定）。存取網址：`http://localhost:3000/alphaforge`。

### Docker
```bash
docker-compose up -d          # 啟動前後端服務
docker-compose up -d --build  # 重新建置並啟動
./start_dev.sh                # 本地開發啟動器（清理 port、啟動雙服務）
./deploy.sh                   # NAS 部署（互動式選單）
```

### NAS 部署流程（重要）
1. `git commit` 本地變更
2. 等待 **Synology Drive 同步**（約 1~2 分鐘）——NAS 透過 Synology Drive 同步 Mac 的本地資料夾，不是 git pull
3. 執行 `echo "3" | ./deploy.sh` 或直接執行 `./deploy.sh` 選擇項目：
   - `1` 僅更新前端
   - `2` 僅更新後端
   - `3` 前後端全更新（最常用）
   - `4` 強制重建（套件有變動時）

> **若 deploy 失敗顯示 CACHED**：代表 Synology Drive 尚未同步完成，等候後再重試。

> **⚠️ 絕對不要直接用 `docker build` 部署前端**：前端需要 `NEXT_PUBLIC_API_URL=/alphaforge/api` build arg，直接執行 `docker build` 不會帶入此參數，導致前端 API 請求路徑錯誤，頁面無法顯示。一律透過 `./deploy.sh` 或 `docker-compose build` 部署。

### 測試
```bash
cd backend && ./.venv/bin/python -m pytest                    # 執行所有後端測試
cd backend && ./.venv/bin/python -m pytest tests/test_file.py # 執行單一測試檔
```

## 架構

### 後端：服務層模式 (Service Layer Pattern)
```
API 端點 (backend/app/api/endpoints/)
    → 服務層 (backend/app/services/)     # 商業邏輯
    → 資料模型 (backend/app/models/)     # SQLAlchemy ORM
    → 資料驗證 (backend/app/schemas/)    # Pydantic
```

核心服務：
- `stock_service.py` — 股票報價、技術指標、K 線數據
- `market_service.py` — 排行榜與市場廣度分析
- `screener_service.py` — 多因子選股篩選，搭配日期快取
- `fundamental_service.py` — 從 TWSE 與 MOPS API 同步 PE/PB/ROE
- `feature_service.py` — 每日預計算指標快照（StockFeature 表，Alpha Miner 基礎）
- `market_data_crawler.py` — TWSE/TPEx 每日數據抓取
- `indicator_service.py` — 技術指標計算（MA、RSI、KD、MACD、布林通道）

背景排程透過 APScheduler（`backend/app/core/scheduler.py`）：每日 15:30 與 17:00 同步市場數據，17:05 計算特徵指標。

### 前端：頁面 + 元件
```
pages/
    index.tsx          — 儀表板（MarketSummary + StrategyScreener + SystemConsole）
    stock/[id].tsx     — 個股詳情（圖表與基本面）
    portfolio.tsx      — 投資組合管理
    trading.tsx        — 模擬交易
    strategy.tsx       — 策略開發
```

API 呼叫透過 `/api/*` 路由，由 Next.js rewrites（`next.config.js`）代理轉發至後端。

### 資料庫 (SQLite — `backend/test.db`)
核心資料表：
- `stock_prices` — 每日 OHLCV，索引 `(stock_id, date)`
- `stock_fundamentals` — 每檔股票最新估值快照（PE、PB、殖利率、ROE、EPS）
- `stock_features` — 每日預計算指標快照（20+ 指標），唯一索引 `(stock_id, date)`
- `stock_monthly_revenue` / `stock_quarterly_eps` — 歷史財務數據
- `screener_cache` — 篩選結果快取（JSON，以日期為 key）

### 數據流
1. **資料抓取**：APScheduler 觸發 → TWSE/TPEx/MOPS API → `stock_prices`、`stock_fundamentals`、營收/EPS 表
2. **特徵儲存**：`feature_service.py` 讀取價格與基本面 → 向量化計算 → `stock_features` 表
3. **選股篩選**：`screener_service.py` 套用多因子條件 → 快取 `StrategyResult` 清單
4. **前端呈現**：元件輪詢 `/api/*` → Next.js 代理 → FastAPI 後端

## 語言

所有回覆一律使用**繁體中文**。

## 重要慣例

### 僅實作被要求的項目
不主動新增未被要求的功能，這是本專案的首要開發原則。

### 向量化運算
所有技術指標計算（MA、RSI、KD、MACD、布林通道）必須使用 Pandas/NumPy 的向量化運算，禁止使用 Python 迴圈進行批次數值計算。

### 教育型 Markdown 微語法
用於 `glossary.json` 與 `EducationalHint` 元件：
- `**關鍵字**` → 亮金色粗體（中性強調）
- `++正向字++` → 翠綠色粗體（多頭訊號）
- `--負向字--` → 玫瑰紅粗體（空頭訊號）

### UI 設計
- 深色玻璃擬態主題：背景使用 `bg-gray-800` / `zinc-900`
- 顏色語意：金色 = 強調/提示，綠色 = 僅限多頭/正向，紅色 = 僅限空頭/負向
- 元件程式碼保持在 300 行以內

### API 代理
前端呼叫 `/api/*`，由 Next.js rewrites 轉發至 `${INTERNAL_API_URL}/*`。本地開發設定 `INTERNAL_API_URL=http://localhost:8000`，Docker 環境預設為 `http://alphaforge-backend:8000`。

### 時區
所有數據使用 `Asia/Taipei` 時區。

### 參考技能索引 (Skills)
需要時主動讀取對應的 SKILL.md 取得詳細指引。

| 技能 | 路徑 | 用途 |
|---|---|---|
| `fastapi-pro` | `.agent/skills/fastapi-pro/` | FastAPI 非同步 API、SQLAlchemy 2.0、Pydantic V2 |
| `nextjs-app-router-patterns` | `.agent/skills/nextjs-app-router-patterns/` | Next.js 14+ App Router、SSR/SSG、Server Components |
| `backtesting-frameworks` | `.agent/skills/backtesting-frameworks/` | 回測系統設計、避免前視偏差與倖存者偏差 |
| `data-storytelling` | `.agent/skills/data-storytelling/` | 數據敘事、報表視覺化、儀表板設計 |
| `seo-content-planner` | `.agent/skills/seo-content-planner/` | SEO 內容策略與主題規劃 |
| `docker-nas-ops-helper` | `.agent/skills/docker-nas-ops-helper/` | Synology NAS Docker 部署與運維 |
| `ui-ux-pro-max` | `~/.claude/skills/ui-ux-pro-max/` | UI/UX 設計資料庫（配色、字體、風格，可用腳本查詢） |

### 除錯
- Next.js 404 無限重整：執行 `npm run clean` 後重啟開發伺服器。原因為 `.next` 快取在 build 與 dev 同時執行時衝突。
- API 文件：`http://localhost:8000/docs`（Swagger UI）
- 系統事件：查看 `SystemEvent` 資料表或 `GET /market/system-events`
- 理解介面時優先閱讀原始碼，避免頻繁啟動瀏覽器查看 API docs。

# TW Stock 168 - Frontend

台灣股市分析與模擬交易平台的前端應用

## 技術堆疊

- **框架**: Next.js 14
- **UI**: React 18
- **樣式**: Tailwind CSS
- **圖表**: Recharts
- **HTTP 客戶端**: Axios

## 快速開始

### 1. 安裝依賴

```bash
cd frontend
npm install
```

### 2. 啟動開發伺服器

```bash
npm run dev
```

應用將在 `http://localhost:3000` 啟動

### 3. 生產構建

```bash
npm run build
npm start
```

## 目錄結構

```
frontend/
├── pages/              # Next.js 頁面路由
│   ├── index.tsx       # 首頁
│   ├── trading.tsx     # 模擬交易頁面
│   ├── portfolio.tsx   # 投資組合分析
│   └── stock/[id].tsx  # 股票詳情頁面
├── components/         # React 組件
│   ├── StockSearch.tsx
│   └── StockCard.tsx
├── styles/            # 全局樣式
├── public/            # 靜態資源
└── package.json
```

## 功能概覽

### 📊 首頁 (Home)
- 股票搜索功能
- 熱門股票卡片展示
- 快速導航到各功能區

### 📈 股票詳情 (Stock Detail)
- K 線圖表展示（支援多時間週期）
- 技術指標（MA, 布林通道, RSI, MACD, KD）
- 買賣下單功能

### 💰 模擬交易 (Trading)
- 帳戶資訊展示
- 持股組合管理
- 訂單紀錄查詢

### 📊 投資組合分析 (Portfolio)
- 資產配置圖表
- 績效統計資訊
- 詳細持股清單

## 後續開發

- [ ] 連接後端 API
- [ ] 即時數據更新
- [ ] 使用者認證系統
- [ ] 實時推播通知
- [ ] 更詳細的技術分析圖表

## 環境變數配置

在 `.env.local` 中配置後端 API 地址：

```
NEXT_PUBLIC_API_URL=http://localhost:8000
```

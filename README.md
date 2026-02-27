# AlphaForge

台灣股市分析與模擬交易平台。

## 🚀 本地開發與測試指南

為了確保前後端連動正常，請依序執行以下步驟：

### 1. 後端啟動 (FastAPI)

1. 進入後端目錄：
   ```bash
   cd backend
   ```
2. 啟動虛擬環境並執行伺服器：
   ```bash
   # 直接使用虛擬環境中的 Python 執行
   ./.venv/bin/python main.py
   ```
   * 預設 API 網址：`http://localhost:8000`
   * 健康檢查網址：`http://localhost:8000/health`

### 2. 前端啟動 (Next.js)

1. 進入前端目錄：
   ```bash
   cd frontend
   ```
2. 啟動開發伺服器 (需指定 API Proxy 位址)：
   ```bash
   INTERNAL_API_URL=http://localhost:8000 npm run dev
   ```
   * 預設開發網址：`http://localhost:3000/alphaforge`

> [!IMPORTANT]
> **注意 Subpath**：由於專案設定了 `basePath`，訪問前端時網址後面必須加上 `/alphaforge`。

### 3. 功能驗證
* 訪問 [http://localhost:3000/alphaforge](http://localhost:3000/alphaforge) 並確認股票報價 (如台積電 2330) 有正常顯示數據 (非 $0.00)。

---

## ☁️ 遠端部署 (NAS)
關於如何部署至 Synology NAS，請參閱 [docs/deployment-sop.md](docs/deployment-sop.md)。

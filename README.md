# AlphaForge

台灣股市分析與模擬交易平台。

## 💡 專案核心理念：學習型工具 (Learning-Oriented)

AlphaForge 不僅是一個股市分析平台，更是一個專為**股票新手**設計的學習工具。我們的目標是將專業的股市術語與數據「白話文化」，讓使用者透過實作與觀察，逐步建立投資直覺。

### 核心特色
- **專業術語白話文**：在複雜的技術指標（如 RSI, BIAS）旁提供情境式的解釋，告訴你「這個數字代表什麼意思？」以及「新手應該注意什麼？」。
- **視覺化型態辨識**：自動識別常見的 K 線型態（如：紅三兵、三隻烏鴉、吞噬型態），並標註在圖表上，幫助使用者在實際案例中學習。
- **教育中心思維**：重點不在於顯示龐大的數字，而在於將規則程式化，轉化為直覺的買賣建議與教育提示。

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

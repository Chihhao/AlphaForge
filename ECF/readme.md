# 🏆 台股分析系統 專家版 (即時版) - 系統分析報告

## 📌 系統簡介
本系統為一套基於純前端技術打造的「台股分析系統專家版」，無需依賴後端資料庫，直接透過前端向各大開源或免費金融 API 獲取即時與歷史股市數據。系統提供強大的技術分析、籌碼分析、基本面數據與 K 線特徵識別功能，為股票投資者提供全方位的分析工具。

## 🛠 技術棧 (Tech Stack)
* **前端核心**：HTML5, CSS3, Vanilla JavaScript (ES6+ 包含 `async`/`await` 非同步處理)
* **圖表繪製**：[Chart.js](https://www.chartjs.org/) 搭配 `chartjs-plugin-annotation` 進行豐富的圖表與註解繪製
* **字體圖標**：使用 Google Fonts (`Noto Sans TC`, `JetBrains Mono`)
* **網路請求**：使用原生 `fetch` API，並搭配多個 CORS 代理伺服器（如 `corsproxy.io`, `cors-anywhere` 等）解決跨網域請求限制
* **架構**：單檔全端 (Single-file Application，程式碼超過 2.9 萬行)，所有樣式 (CSS) 及邏輯 (JS) 皆封裝於單一 HTML 檔案中。

## 📊 核心功能 (Core Features)

### 1. 進階技術指標庫
* **趨勢指標**：移動平均線 (SMA/EMA)、MACD、DMI (動向指數)、CCI。
* **震盪指標**：RSI (相對強弱指標)、KD 值 (隨機指標)。
* **通道與能量區間**：布林通道 (Bollinger Bands)、OBV (能量潮)。
* **進階分析**：費波那契回撤 (Fibonacci Retracement)、艾略特波浪理論 (Elliott Wave) 偵測、自動計算短期/中長期支撐與壓力位。

### 2. K 線型態自動識別 (Candlestick Pattern Recognition)
* 內建多種自動 K 線組合偵測：十字線 (Doji)、吞噬形態 (Engulfing)、晨星/夜星 (Morning/Evening Star)、紅三兵/黑三鴉、吊人線、鎚子線等。
* 自動標註跳空缺口 (Gaps) 以及異常 K 線分析。

### 3. 多面向籌碼與基本面分析
* **三大法人買賣超**：整合外資、投信、自營商的籌碼面分析。
* **信用交易分析**：融資融券餘額動態圖表。
* **營收表現**：企業每月營收長條圖、營收年月增率動態圖表分析。

### 4. 資料來源與跨市場支援
* **支援市場**：涵蓋 **上市 (TWSE)**、**上櫃 (TPEx)** 及 **ETF** 商品查詢。
* **多元串接**：即時報價、歷史資料與新聞來源包含 Yahoo Finance API、台灣證券交易所 (TWSE) OpenAPI、櫃買中心 (TPEx) API、Goodinfo! 台灣股市資訊網、CMoney 等。
* 支援個股深入分析與相關財經新聞外部連結。

### 5. 使用者體驗與輔助工具
* **自選股管理 (Watchlist)**：使用者可以建立並追蹤自己的專屬自選名單，包含即時報價更新。
* **個股比較 (Compare)**：提供不同股票之間的技術線圖並排比較功能。
* **匯出與分享**：支援匯出為 Excel 數據、PDF 報表導出，以及複製報告內容與下載分析後的 K 線圖功能。

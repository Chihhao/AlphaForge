# 🚀 ECF (專家版) 核心資產移植計畫

這份文件記錄了自豪的純前端分析系統 [ECF (Taiwan Stock Analyzer)](../ECF/taiwan-stock-analyzer(60).html) 中，可以被萃取並移植到 AlphaForge 全市場量化引擎的 4 大核心亮點。我們將把 ECF 強大的「交易智慧（數學公式、經驗法則）」整合進 AlphaForge 高效的「資料庫與 Pandas 極速引擎」之中。

## 💡 1. 豐富的 K 線型態自動識別 (Candlestick Patterns)

ECF 內建了非常強大的「K 線型態偵測」邏輯。
*   **來源技術**：ECF 使用 JavaScript 土法煉鋼運算（包含判斷實體棒長度、影線比例等）。
*   **移植計畫**：
    *   **轉換為向量化運算**：將這些偵測數學公式，翻譯成 Python 的 Pandas 向量化運算矩陣。
    *   **模組化**：寫進 AlphaForge 的 `IndicatorService` (或獨立為 `PatternService`)。
*   **目標成效**：能在幾秒鐘內，掃描全市場 1950 檔股票，快速篩選出「今天出現了『晨星』或『紅三兵』攻擊訊號」的個股，化為獨家選股策略。
*   **待移植型態（包含但不限於）**：紅三兵、黑三鴉、十字線、吞噬型態、晨星、夜星、鎚子線、吊人線等。

## 💡 2. 進階技術指標算法庫

除了已有的 MA (均線) 與 Bias (乖離率)，ECF 包含了非常完整且經市場驗證的指標算法。
*   **來源技術**：前端 JavaScript 計算各種震盪與趨勢指標。
*   **移植計畫**：
    *   **擴充 `IndicatorService`**：使用 Pandas / pandas-ta 或 TA-Lib 原生支援，重製並對齊 ECF 的參數設定。
    *   **進階策略實作**：重構出費波那契回撤 (Fibonacci Retracement) 與艾略特波浪理論 (Elliott Wave) 偵測的 Python 版本。
*   **目標成效**：建立更多維度的高階選股模組，例如「布林通道極度壓縮後突破」、「MACD 底背離搭配量增」等高勝率策略。

## 💡 3. 多元資料爬蟲邏輯 (Data Sources)

ECF 為了不依賴單一後端，串接了極為豐富的外部資料源（包含了籌碼面、基本面資料）。
*   **來源技術**：前端 Fetch API 搭配 CORS Proxy 呼叫各站台的隱藏 API。
*   **移植計畫**：
    *   **逆向工程 API**：觀察 ECF 原始碼中呼叫 API 的 headers 與 payload 組成方式（例如：Yahoo Finance, Goodinfo!, CMoney, TWSE/TPEx 等）。
    *   **整合自動化爬蟲**：把這些抓取邏輯收編進 AlphaForge 的 `MarketDataCrawler` 之中。
*   **目標成效**：透過每日排程，偷偷且穩定地幫本地資料庫擴充最新的基本面 (營收、EPS) 或籌碼面核心數據 (三大法人買賣超、融資券增減)，不再需要人工匯入資料。

## 💡 4. 圖表註解與 UI 體驗 (Chart UX)

ECF 在分析圖表上具備極佳的視覺化巧思，例如自動繪製支撐/壓力線、形態學註解跟「缺口 (Gaps)」標示。
*   **來源技術**：利用 Chart.js 搭配 annotation plugin，在 Canvas 自訂渲染。
*   **移植計畫**：
    *   **Lightweight-charts 標記系統**：將這些圖表渲染技巧轉換為 Next.js 環境中 `lightweight-charts` 的 Markers / Plugins 或 Price Lines 功能。
    *   **結合後端訊號**：讓後端負責計算「支撐壓力位」與「缺口價格」，透過 API 傳給前端，前端只負責乾淨地渲染出來。
*   **目標成效**：讓 AlphaForge 儀表板中的個股詳情頁圖表擁有不遜於 ECF 的專家級分析視覺，同時保持現代化 Web App 的流暢體驗。

---

**📌 執行備註**：
這些計畫可以分階段 (Phases) 逐步執行，並整合於未來的系統擴充路線圖中。首要目標仍是先確保 AlphaForge 的基礎歷史資料庫與選股引擎 (Phase C) 能以最完美、最快的方式運行。

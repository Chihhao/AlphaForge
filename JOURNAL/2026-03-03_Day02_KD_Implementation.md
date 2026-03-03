# 🚀 AlphaForge 學習日誌 - Day 02
**日期**：2026-03-03
**主題**：KD 指標計算引擎實作 & 知識庫建構

---

## 🧠 今日學習重點 (The "How")

### 1. 從數學公式到可執行代碼
昨天我們拆解了 KD 的數學原理，今天我們將它**轉化為 Python 程式碼**。
- **Rolling Window**：使用 `pandas.rolling(window=9)` 實現「過去 9 天的最高/最低」滾動計算。
- **遞迴平滑**：KD 的 K、D 值無法用向量化一步計算，必須用 `for` 迴圈逐日遞迴。
- **初始值處理**：前 8 天（不足 9 天的窗口）輸出 `NaN`，K/D 初始值設為 50。

### 2. 邊界情況處理
- **平盤情況**：當 `High == Low` 時，RSV 分母為 0，需特殊處理（填入 50）。
- **數據不足**：抓取 3 個月的數據確保 KD 計算有足夠的基底。

---

## 🏗️ 開發成果

### ✅ 後端：KD 計算引擎
- `backend/app/logic/indicators/kd.py` — 核心計算函式
- `backend/app/services/indicator_service.py` — 服務層（串接數據與計算）
- `backend/app/schemas/indicator.py` — API 響應模型
- `backend/app/api/endpoints/indicators.py` — REST API 端點
  - `GET /indicators/kd/{stock_id}` — 取得 KD 歷史數據
  - `GET /indicators/kd/{stock_id}/status` — 取得當前狀態與交叉訊號

### ✅ 後端：名詞解釋知識庫 (Glossary)
- `backend/app/data/glossary.json` — 知識庫 JSON 檔案
- `backend/app/services/glossary_service.py` — 名詞查詢服務
- `backend/app/api/endpoints/glossary.py` — REST API 端點
  - `GET /glossary/` — 取得全部名詞
  - `GET /glossary/{entry_id}` — 取得單一名詞
  - `GET /glossary/search?q=關鍵字` — 搜尋名詞
  - `GET /glossary/category/{category}` — 分類過濾

### ✅ 測試驗證
- 上升趨勢：K=90.62, D=84.46 → 正確反映超買區域
- 下降趨勢：K=10.72, D=20.65 → 正確反映低估區域
- 平盤情況：K=50, D=50 → 零分母無報錯
- 交叉訊號偵測邏輯正常

---

## 🕵️ 技術洞察 (Technical Insights)

### 💡 為什麼 KD 必須用遞迴而不能用向量化？
```
K_today = 1/3 * RSV_today + 2/3 * K_yesterday
```
每一天的 K 值取決於「昨天的 K 值」，形成鏈式依賴。
這和 RSI 的指數移動平均類似，是技術指標中常見的「狀態依賴型」計算模式。

### 💡 Glossary JSON 的設計哲學
- **結構化 + 自由文本**：JSON 提供搜尋與分類功能，Markdown 內文提供富文本排版。
- **LaTeX 公式支援**：讓金融量化中不可或缺的數學公式能優雅呈現。
- **漸進式遷移**：初期用 JSON 快速迭代，未來可無痛遷移至資料庫。

---

## 🛠️ Day 3 計畫
- [x] 串接真實台股數據，驗證 KD 計算結果與 Yahoo Finance 一致。
- [x] 前端開發 KD 指標視覺化組件（位階儀表板、超買超賣色彩回饋）。
- [x] 在前端串接 Glossary API，實現「點擊名詞查看解釋」互動功能。

---

## 💭 今日心得
> 「程式碼是知識的沉澱。當你把 RSV 公式寫成 Code 時，你就永遠掌握了這個市場規律的量化方法。今天我們不只理解了 KD，更建立了一套可以計算任何指標的架構。」

# 📱 AlphaForge 學習日誌 - Day 10b
**日期**：2026-03-11
**主題**：Stock 頁面手機版 UI 全面優化與技術面信號卡

---

## 🧠 今日學習重點 (The "Why")

### 1. 手機版 UI 設計原則
- **邊緣到邊緣 (Edge-to-Edge)**：手機螢幕寸土寸金，卡片不應有圓角與左右 padding，讓內容貼滿寬度。
- **負邊距技巧**：在有 `p-4` padding 的容器內，對子元素加 `-mx-4` 可讓它突破父容器貼滿邊緣，同時保留上下間距。
- **單線分隔**：卡片之間避免 `border-y` + `mb-px` 的雙線問題，改用 `border-b` + `mb-0`，相鄰卡片只會看到一條分隔線。

### 2. 「零件 vs 勝率」的產品哲學
- 舊的「主圖指標/副圖指標」列出 MA20、MA50、布林上下軌等原始數字，對新手毫無意義。
- 重新設計為「技術面信號」卡：數字加上白話判斷（如「站上 MA20 +2.3%」、「超買區，注意回檔」），符合 AlphaForge 的教育定位。
- **核心原則**：給 User 詮釋，不給 User 零件。

### 3. API 跨裝置存取問題
- **根本原因**：`NEXT_PUBLIC_API_URL=http://localhost:8000` 是瀏覽器端直接呼叫，手機的 `localhost` 指向手機本身，不是 Mac，所以失敗。
- **解法**：改為區網 IP `http://10.0.4.59:8000`，手機與 Mac 都能直連後端。
- **Next.js rewrite 的陷阱**：basePath `/alphaforge` 會讓 rewrite source 自動加上前綴，導致 `/api/*` 無法匹配，proxy 從來沒有生效過。

---

## 🏗️ 開發成果

### ✅ Stock 頁面手機版貼邊佈局
- 容器移除左右 padding：`px-4` → `px-0 sm:px-4`
- 所有卡片：`rounded-lg` → `rounded-none sm:rounded-lg`，`border` → `border-b border-x-0 sm:border`
- 卡片間距：`mb-4` → `mb-0 sm:mb-6`（手機用 border-b 作分隔）
- K 線圖貼邊：容器加 `-mx-4 sm:mx-0`，圖表貼滿螢幕寬

### ✅ Header 精簡
- 移除「股票代號：」文字，代號改為小字 inline
- 移除「庫存/市值」欄位
- 統計欄改 4 欄，水平分隔線加 `-mx-4` 貼邊
- 字體調整：名稱 `text-2xl sm:text-4xl`，數值 `text-lg sm:text-xl`

### ✅ K 線圖體驗優化
- 預設頻率：`15m` → `1d`（日線）
- 頻率選擇器與副圖選擇器合併為同一行，節省空間
- 按鈕文字精簡：「成交量」→「量」

### ✅ 基本面區塊重構
- 移除「基本面大腦」標題與 badge
- 手機改 `grid-cols-2 md:grid-cols-3`
- 標籤改純中文：PE → 本益比、PB → 股價淨值比、ROE → 權益報酬率、殖利率 → 現金殖利率

### ✅ 技術面信號卡（新）
舊的兩張數字卡（主圖指標 + 副圖指標）合併為一張訊號卡，4 個指標各有判斷：

| 指標 | 邏輯 |
|:---|:---|
| 均線位階 | 價格 vs MA20，顯示百分比偏離 |
| RSI | 分四段：超賣/偏弱/偏強/超買，各有顏色與說明 |
| 布林通道 | 計算價格在通道內的相對位置 (0-100%) |
| KD 指標 | 沿用原有 KDIndicator，保留金叉/死叉/超買/超賣邏輯 |

顏色語意：紅 = 偏多、綠 = 偏空、琥珀 = 警告、青色 = 超賣機會

### ✅ Glossary 新增條目
- `pe-ratio`：本益比 (Price-to-Earnings)，含公式與同產業比較說明
- `pb-ratio`：股價淨值比 (Price-to-Book)，含適用股種說明
- `dividend-yield`：現金殖利率，含填息觀念與假高殖利率警告
- `roe-indicator`：標題改為 ROE (Return on Equity)，內文第一句說明中文全名

### ✅ 維運修復
- CORS 白名單新增 `http://10.0.4.59:3000`，支援手機開發測試
- `.env.local` 更新 `NEXT_PUBLIC_API_URL=http://10.0.4.59:8000`
- `~/.zshrc` 新增 `alias claude-dev="claude --dangerously-skip-permissions"`
- 部署至 NAS（前後端全更新）

---

## 🛠️ 下一步計畫
- [ ] **Alpha Miner Phase 2**：實作 `BacktestService`，計算技術訊號的歷史勝率
- [ ] **技術面信號卡升級**：加入「此訊號過去 X 次，勝率 Y%」
- [ ] **圖表 Markers**：在 K 線圖上標記訊號觸發點（Day 11-12）

---

## 💭 今日心得
> 「今天花了大量時間磨 UI，但每一個改動都有明確的目的：讓新手在手機上也能舒適地看懂一支股票的全貌。
>
> 最有收穫的是把技術指標從『數字清單』改為『訊號判斷』——這不只是 UI 改動，而是產品哲學的落地：AlphaForge 的責任是幫使用者詮釋數據，而不是把原始數據丟給他們自己解讀。
>
> 另外解決了手機連線問題，讓未來的行動開發測試更順暢。Next.js basePath + rewrite 的陷阱值得記住。」

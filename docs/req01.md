# 📋 需求規格與設計文件：K 線圖實施物理索引 (Strict Physical Indexing)

## 1. 核心目標
為解決 `lightweight-charts` 在非交易時段產生的長距離跳空與指標水平連線問題，將圖表的 X 軸從「線性時間軸」切換為「離散索引軸」。

## 2. 技術架構
### A. 資料解耦 (Data Decoupling)
後端或前端處理資料時，不再將 Unix Timestamp 直接作為 `time` 欄位傳遞給序列，而是改用純數字序列。
- `uniqueData[0].time = 0`
- `uniqueData[1].time = 1`
- `uniqueData[N].time = N`

### B. 時間映射表 (Time Mapping Table)
維護一個物理索引對真實時間的映射關係，用於 X 軸標籤 (Ticks) 與滑鼠懸停 (Tooltip) 的顯示。
- **映射結構**：`map[index] = original_timestamp`
- **實作成效**：即便索引是連續的，使用者看到的標籤依然是 `09:00`, `13:30` 等。

### C. 縮放手感優化
為保持 LWC 的流暢手感，將索引放大一個固定常數（如 `index * 3600`），騙過 LWC 的縮放阻尼引擎。

## 3. 實施步驟
### 第一階段：前端資料轉換 ([id].tsx)
- [ ] 修改 `fetchData` 邏輯。
- [ ] 將 `isIntraday` 模式下的 `time` 欄位強制設為資料陣列的 index。
- [ ] 保留 `originalTime` 欄位供 TVChart 使用。

### 第二階段：圖表組件渲染 (TVChart.tsx)
- [ ] 更新 `timeFormatter`：根據 `dataRef.current[time]` 抓取 `originalTime` 並格式化。
- [ ] 更新 `tickMarkFormatter`：實施相同的解析邏輯。
- [ ] **視覺清理**：
    - 隱藏 `priceLineVisible` 消除水平虛線。
    - 隱藏 `lastValueVisible` 減少視覺雜訊。

### 第三階段：指標對齊
- [ ] 確保 RSI 與 Bias 的 `setData` 是根據主圖的連續 index 生成。
- [ ] 關閉指標的 `priceLineVisible`。

## 4. 預期成效
1. **零跳空**：無論跨夜或跨週末，K 棒完全緊密貼合。
2. **無橫線**：RSI 指標在斷點處會自然過渡或中斷，不會拉出一條長橫線。
3. **專業感**：畫面比例與專業交易軟體（如 TradingView 專業版）一致。

---
description: 股票圖表 (Lightweight-charts) 時區處理規範
---

# 股票圖表時區處理規範 (Taipei Time UTC+8)

當在 AlphaForge 中開發股市相關圖表時，為了確保全球使用者看到的都是 **台北交易時間 (09:00 - 13:30)**，必須遵循以下時區處理規範，以避免「時區地獄 (Timezone Hell)」。

## 核心問題
`lightweight-charts` 會自動將 UNIX Timestamp 加上使用者瀏覽器的當地時差。例如，台北 09:00 的數據，在倫敦使用者眼裡會變成 01:00。

## 解決方案 (強制格式器)
不要在數據層級 (Data Parsing) 試圖偏移 timestamp，這會導致數據排序與邏輯混亂。正確的做法是在 **圖表顯示層級 (Component Level)** 進行強制偏移格式化。

### 1. 數據層 (frontend/pages/stock/[id].tsx)
數據層應維持純粹的 UTC 或原始 Timestamp，不進行任何偏移運算。

```tsx
const data = (kd.data || []).map((r: any) => ({
  time: Math.floor(new Date(r.date).getTime() / 1000) as any,
  open: r.open,
  // ... 其他數據
}));
```

### 2. 圖表組件層 (frontend/components/TVChart.tsx)
在 `createChart` 的設定中，同時針對「十字線提示盒 (Tooltip)」與「X 軸標籤 (Tick Marks)」進行 +8 小時的強制格式化。

```tsx
const chart = createChart(container, {
    // ... 其他配置
    localization: {
        // 強制提示盒 (Tooltip) 顯示台北時間
        timeFormatter: (time: Time) => {
            if (typeof time === 'number') {
                const date = new Date((time + 8 * 3600) * 1000);
                return date.toISOString().slice(11, 16); // 輸出 "09:00"
            }
            return String(time);
        },
    },
    timeScale: {
        // 強制 X 軸標籤顯示台北時間
        tickMarkFormatter: (time: Time) => {
            if (typeof time === 'number') {
                const date = new Date((time + 8 * 3600) * 1000);
                return date.toISOString().slice(11, 16);
            }
            return String(time);
        },
    },
});
```

## 注意事項
- **優先使用 Formatter**：這是在地化顯示最穩定、最安全的方法。
- **避免 Wall Clock Hack**：不要試圖製造一個「假 UTC 日期」，這在多時差環境下非常不穩定。
- **ISO 8601**：後端傳回的日期字串必須包含時區資訊 (例如 `+08:00`)，以確保 `new Date()` 解析出的數值一致。

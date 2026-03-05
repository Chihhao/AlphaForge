---
description: 前端開發環境操作規範，避免 .next 快取衝突導致網頁異常
---

# 前端開發環境操作規範

## ⚠️ 核心原則：永遠不要在 `dev` 運行時執行 `build`

Next.js 的 `npm run dev` 和 `npm run build` 共用同一個 `.next/` 目錄。
同時執行兩者會導致編譯產物互相覆蓋，引發 500 Internal Server Error。

## ✅ 驗證代碼正確性的正確方式

當需要驗證前端代碼是否能正確編譯時，**不要**執行 `npm run build`。請改用以下方式：

### 方式一：依賴 Dev Server 的即時回饋（推薦）
`npm run dev` 本身就會在你修改檔案時即時編譯並報告錯誤。
如果 dev server 沒有報錯，代碼就是正確的。

// turbo
1. 用 `curl -I http://localhost:3000/alphaforge` 檢查是否回傳 200 OK

### 方式二：僅做型別檢查（安全）
如果只需要確認 TypeScript 型別是否正確：

// turbo
1. `cd frontend && npx tsc --noEmit`

### 方式三：如果真的需要 build（罕見）
只有在以下情況才需要 build：
- 準備正式部署到 NAS
- 使用者明確要求驗證生產環境

步驟：
1. 先停止 `npm run dev`
2. `npm run clean` 清除舊的 `.next/`
3. `npm run build`
4. 驗證完成後，重新啟動 `npm run dev`

## 🔧 發生快取衝突時的修復步驟

如果不幸發生了 `.next/` 快取衝突（症狀：500 Internal Server Error、missing required error components）：

1. 停止正在運行的 `npm run dev`（在終端機按 Ctrl+C）
// turbo
2. `cd frontend && npm run clean`
// turbo
3. `cd frontend && INTERNAL_API_URL=http://localhost:8000 npm run dev`

## 📋 每次修改前端代碼前的 Checklist

- [ ] 確認 `npm run dev` 是否正在運行
- [ ] 修改檔案後，觀察終端機是否有編譯錯誤
- [ ] 用 curl 或瀏覽器確認頁面是否正常載入
- [ ] **絕對不要**在 dev 期間執行 `npm run build` 或 `npm run clean`

# AlphaForge 專案開發規則

這些規則定義了 AlphaForge 專案的技術標準、架構與開發流程，AI 應始終遵循。

## 🛠 技術棧 (Technology Stack)

- **前端 (Frontend)**: Next.js (TypeScript), Tailwind CSS.
  - **重要**: 前端路徑有 `basePath` 設定，存取網址必須包含 `/alphaforge`。
- **啟動指令**: `INTERNAL_API_URL=http://localhost:8000 npm run dev`
  - **最佳實踐**: 強烈建議在**獨立終端機**視窗中保持執行 `npm run dev`，這能確保最穩定的 HMR (熱更新) 且避免背景程序衝突。
  - **清理指令**: 若遇到 404 異常重整，請執行 `npm run clean` 後再重啟。
  - **啟動指令**: `./.venv/bin/python main.py`
  - **預設網址**: `http://localhost:8000`
- **數據交換**: 前端透過 Axios 與後端 API 通訊，需透過環境變數指定 API URL。

## 📂 專案結構與路徑

- **前端目錄**: `/frontend`
- **後端目錄**: `/backend`
- **文件目錄**: `/docs`
- **NAS 部署目錄**: `/volume1/homes/chihhaolai/Drive/Documents_Mac_Lai/GitHub/AlphaForge`

## 🚀 部署流程 (Deployment)

AlphaForge 部署於 Synology NAS，採用 Docker 容器化技術。

- **同步方式**: 使用 Synology Drive 自動雙向同步 Mac 與 NAS 之間的程式碼。
- **部署指令 (在 NAS 執行)**:
  - **更新前端**: `env DOCKER_BUILDKIT=1 COMPOSE_DOCKER_CLI_BUILD=1 sudo -E docker-compose up -d --build frontend`
  - **更新後端**: `sudo docker-compose up -d --build backend`
- **反向代理**: 使用 NAS 內建的反向代理將 `junesnow39.synology.me` (HTTPS) 指向 `http://localhost:3001`。

## 💡 開發原則

1. **學習型工具**: 保持「白話文」風格，將複雜數據轉化為易懂的教育提示。
2. **優先局部更新**: 除非變動套件 (`package.json`, `requirements.txt`)，否則應使用局部更新指令以節省 build 時間。
3. **路徑一致性**: 確保所有 API 調用與連結都考慮到 `/alphaforge` 這個 subpath。

## 🐛 常見除錯與測試經驗 (Debugging & Testing)

1. **Next.js 404 無限重整 (Missing required error components)**:
   - **原因**: 當背景同時執行 `npm run dev` (熱更新) 與 `npm run build` 時，Next.js 的 `.next` 快取資料夾會發生讀寫衝突與錯亂，導致找不到必要的編譯檔案。
   - **解法**: 必須徹底清除快取。
     ```bash
     cd frontend
     killall -9 node     # 砍掉所有卡死的 Node 程序
     rm -rf .next        # 刪除損壞的快取資料夾
     npm run dev &       # 重新啟動乾淨的開發伺服器
     ```
     然後在瀏覽器手動重新整理網頁即可恢復。

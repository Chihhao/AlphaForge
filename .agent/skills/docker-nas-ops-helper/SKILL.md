---
name: docker-nas-ops-helper
description: 專屬於 AlphaForge 在 Synology NAS 環境下的 Docker 運維與自動化部署指南。
---
# AlphaForge NAS 部署與運維指南

此 Skill 定義了 AlphaForge 在 Synology NAS 環境下的標準部署流程、加速技巧以及常見故障故障排除。

## 🚀 部署核心概念

1.  **自動同步**：開發環境 (Mac) 與 NAS 透過 **Synology Drive** 雙向同步。儲存檔案後，NAS 端即刻更新。
2.  **分離部署**：修改前端就單獨更新 frontend 容器，修改後端則更新 backend。
3.  **加速快取**：利用 Docker BuildKit 與快取掛載，避免重複下載套件。

## 💻 快速部署指令 (SSH 連線 NAS 後執行)

**專案目錄**: `/volume1/homes/chihhaolai/Drive/Documents_Mac_Lai/GitHub/AlphaForge`

### 1. 更新前端 (UI/CSS/TSX 改動)
```bash
export PATH=/usr/local/bin:$PATH
env DOCKER_BUILDKIT=1 COMPOSE_DOCKER_CLI_BUILD=1 sudo -E docker-compose up -d --build frontend
```

### 2. 更新後端 (API/Python 邏輯改動)
```bash
sudo docker-compose up -d --build backend
```

### 3. 套件變動 (新增 npm 或 pip 套件)
```bash
# 前端套件更新
sudo docker-compose build --no-cache frontend && sudo docker-compose up -d frontend

# 後端套件更新
sudo docker-compose build --no-cache backend && sudo docker-compose up -d backend
```

---

## 🔍 Synology NAS 特有問題故障排除

### 🚨 下載編譯報錯：`Type error: Cannot find type definition file for '@eaDir'`

**問題原因**:
NAS 會自動在所有目錄生成 `@eaDir` 元數據資料夾。Next.js 的編譯器會誤將其視為 TypeScript 類型定義庫並嘗試解析，導致編譯失敗。

**解決方案**:
1.  **Dockerfile 清理**：在 `npm run build` 前加入強力清理指令。
    ```dockerfile
    RUN find . -name "@eaDir" -type d -exec rm -rf {} + || true
    ```
2.  **配置過濾**：
    -   `.dockerignore`: 加入 `**/@eaDir`
    -   `tsconfig.json`: `exclude` 列表加入 `**/@eaDir`

### 🌐 網路與反向代理
-   **反向代理**: 確認 `junesnow39.synology.me` 指向 `http://localhost:3001`。
-   **SSL**: 憑證過期請至 `DSM 控制台 > 安全性 > 憑證` 更新。
-   **連線不安全**: 確保反向代理已勾選 **HSTS**。
-   **CORS**: 後端 `config.py` 的 `BACKEND_CORS_ORIGINS` 需包含 `https://junesnow39.synology.me`。

### 🗄️ API 回傳 500 Internal Server Error 排查 SOP

**排查步驟**（按順序）：
1.  **查看容器日誌**：
    ```bash
    export PATH=/usr/local/bin:$PATH
    sudo docker logs alphaforge-backend --tail 50
    ```
2.  **確認容器是否在運行**：
    ```bash
    sudo docker ps -a | grep alphaforge
    ```
3.  **常見原因**（依發生頻率排序）：

#### 原因 1：`requirements.txt` 遺漏套件
**症狀**: 日誌出現 `ModuleNotFoundError: No module named 'xxx'`。
**原因**: 本地 venv 手動裝了套件但忘了加到 `requirements.txt`，Docker 建置時不會自動安裝。
**解法**: 將套件加入 `requirements.txt`，然後用 `--no-cache` 重建：
```bash
sudo docker-compose build --no-cache backend && sudo docker-compose up -d backend
```

#### 原因 2：資料庫 Volume 掛載路徑不一致
**症狀**: 日誌出現 `資料庫中無加權指數數據` 或類似資料查詢失敗的訊息。
**原因**: `docker-compose.yml` 掛載的 `.db` 檔案與程式碼中 `DATABASE_URL` 設定的不同。
**當前正確設定**:
-   `config.py` 預設 `DATABASE_URL` = `sqlite:///./test.db`
-   `docker-compose.yml` volume 掛載必須對應：`./backend/test.db:/app/test.db`
-   **注意**：不要掛載 `stock_data.db`（歷史遺留空檔案，已無用途）。

#### 原因 3：NAS 上 `sudo` 找不到 `docker`
**症狀**: `sudo: docker: command not found`。
**解法**: 在 SSH 指令前加 `export PATH=/usr/local/bin:$PATH`。

## 🚨 重置大法 (核彈指令)
若發生容器卡死或 Port 衝突：
```bash
sudo docker-compose down
sudo docker-compose build --no-cache
sudo docker-compose up -d
```

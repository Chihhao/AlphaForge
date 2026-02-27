# AlphaForge 專案開發與部署進度紀錄 (已更名)

## 部署目標
將全端專案（React/Next.js 前端 + Python FastAPI 後端）部署至家用 Synology NAS 伺服器，並於區域網路內提供服務。

## 目前完成進度 (至 2026-02-27)

### 1. Docker 環境容器化 (完成)
- **前端 (Next.js)**：建立 `frontend/Dockerfile`，使用 Node 18 Alpine 映像檔，設定生產環境打包與靜態靜態生成。
- **後端 (FastAPI)**：建立 `backend/Dockerfile`，使用 Python 3.11 Slim 映像檔，定義套件安裝與 uvicorn 啟動指令。
- **Docker Compose**：建立 `docker-compose.yml` 將前後端服務整合。
  - 後端運行於 `8000` 端口，並掛載 SQLite 資料庫 (`stock_data.db`) 確保資料持久化。
  - 前端運行於 `3001` 端口，設定關聯性 (`depends_on: backend`)。

### 2. Synology NAS 遠端設定 (完成)
- **SSH 連線**：成功確認經由區域網路 (`10.0.4.3`) 以 `chihhaolai` 帳號遠端連線 NAS。
- **背景自動化權限**：為了解決自動化部署腳本遇到 `sudo` 會被密碼互動阻斷的問題，已在 NAS 上設定 `/etc/sudoers.d/chihhaolai`，賦予帳號執行 `sudo` 權限時的免密碼通行 (NOPASSWD)。這使未來任何部署更新與日誌檢查皆能自動化進行。

### 3. 障礙排除與架構調優 (完成)
在此階段排除了關鍵問題，確保數據正常顯示與專案品牌一致性：

#### A. 專案正式更名 (Rename to AlphaForge)
- **內容**：將原專案「TW-STOCK-168」全域更名為 **AlphaForge**，包含前後端代碼、配置檔、Docker 映像檔名稱及 UI 顯示。
- **目的**：提升品牌辨識度，確立專案核心定位。

#### B. 後端套件缺失 (ModuleNotFoundError)
- **問題**：後端容器啟動後，因缺少台灣股市串接套件 `twstock` 導致一接收請求即崩潰。
- **解法**：修改 `backend/requirements.txt` 加入 `twstock`，並重新 Build 後端映像檔。

#### C. 跨網域資源共用 (CORS) 阻擋
- **問題**：後端 API 伺服器預設的安全名單 (CORS Origins) 僅允許 `localhost`，導致透過 NAS IP (`10.0.4.3`) 存取時被阻擋。
- **解法**：修改 `backend/app/core/config.py`，將 `http://10.0.4.3:3001` 與 `https://junesnow39.synology.me` 加入允許清單。

#### D. 前端 Next.js API 網址綁定問題
- **問題**：Next.js 在 Build 階段會進行靜態優化，導致環境變數無法動態適應 NAS 環境。
- **解法**：改用動態探測機制，讓前端自動根據當前網址發送 API 請求。

### 4. 外網存取與 SSL 安全加密 (完成)
- **DDNS 設定**：透過 `junesnow39.synology.me` 網域提供外網存取能力。
- **HTTPS/SSL 憑證**：成功申請並安裝 **Let's Encrypt** 憑證。
- **反向代理 (Reverse Proxy)**：配置 NAS 內建反向代理，將外部 HTTPS (443) 流量轉換為內部的 Docker 流量，徹底解決 `ERR_CERT_AUTHORITY_INVALID` 錯誤。

## 階段性成果
- ✅ 全站支援 **HTTPS 安全連線**，網址列顯示安全鎖頭。
- ✅ 完成專案品牌化重構（Renaming）。
- ✅ 支援手機或電腦透過外網域名穩定存取 K 線圖。

---

## 下一步建議規劃
1. **反向代理與網域配置 (Reverse Proxy & DDNS)**：
   - 透過 Synology 內建的登入入口設定，將 `chihhaolai.synology.me` 等 DDNS 免費網域綁定至 `3001` 端口，並自動申請 Let's Encrypt 免費憑證，達成外網 HTTPS 安全連線。
2. **前後端資料快取與優化**：
   - 針對首頁或熱門股票實作 Redis 或記憶體快取，降低頻繁存取 `twstock` 與外部資料源的延遲情況。

# AlphaForge 快速部署標準作業流程 (SOP)

這份文件記錄了將修改過的 AlphaForge 程式碼部署至 Synology NAS 的最快、最標準流程。遵循此流程，日常的小修改最快可以在 **30 秒 ～ 1 分鐘** 內完成上線。

## 部署核心概念

1. **程式碼同步**：目前你的開發環境 (Mac) 與 NAS 伺服器之間，已經透過 **Synology Drive** 進行了自動雙向同步。這意味著：你只要在 Mac 上儲存檔案，NAS 上就已經有最新程式碼了！**不需要 git pull，也不需要 FTP 複製。**
2. **善用 Docker 快取**：只要你沒有去修改 `package.json` (前端加套件) 或 `requirements.txt` (後端加套件)，重新打包的過程會利用快取，瞬間完成。
3. **分離前後端更新**：前端改了就只更新前端，不需要動到後端。

## 💻 NAS 伺服器環境配置 (初次設定時使用)

為了確保部署順利，請確認 NAS 上已完成以下設定：

1. **SSH 權限**：於 DSM 控制台開啟 SSH 服務。
2. **免密碼 sudo**：為了讓 Docker 指令自動化執行，已設定 `/etc/sudoers.d/chihhaolai` 檔案，賦予帳號執行 `sudo` 時無需輸入密碼 (`NOPASSWD`)。
3. **目錄結構**：專案位於 `/volume1/homes/chihhaolai/Drive/Documents_Mac_Lai/GitHub/AlphaForge`。

---

## 🚀 情況一：只有修改「前端」程式碼 (最常見)
當你調整了 UI 介面、圖表樣式、或元件等 (`frontend` 目錄下的 `.ts`, `.tsx`, `.css`)：

1. **儲存檔案**：在 VSCode 儲存修改，確認 Mac 上的 Synology Drive 已同步。
2. **連線 NAS**：開啟 Mac 終端機，SSH 登入 NAS：
   ```bash
   ssh chihhaolai@10.0.4.3
   ```
3. **進入專案目錄**：
   ```bash
   cd /volume1/homes/chihhaolai/Drive/Documents_Mac_Lai/GitHub/AlphaForge
   ```
4. **設定環境變數**(DSM 的 Docker 路徑問題)：
   ```bash
   export PATH=/usr/local/bin:$PATH
   ```
5. **🔥 秒速重構與重啟前端**：
   ```bash
   sudo docker-compose up -d --build frontend
   ```
   > **說明**：這行指令會「只針對」frontend 進行重構。如果只有程式碼改動，Docker 會直接命中 1~8 步的快取，只需數十秒鐘跑 `npm run build`，然後無縫重啟。

---

## 🚀 情況二：只有修改「後端」程式碼
當你修改了 API 邏輯、Python 檔案 (`backend` 目錄下的 `.py`)：

1. **儲存檔案並確認同步。**
2. **連線 NAS 並進入目錄** (同情況一的第 2, 3, 4 步)。
3. **🔥 秒速重構與重啟後端**：
   ```bash
   sudo docker-compose up -d --build backend
   ```
   > **說明**：同樣只更新後端。如果沒改 `requirements.txt`，幾秒鐘內就會替換新程式並重啟 `uvicorn`。

---

## ⚠️ 情況三：新增/移除了 NPM 或 Python 套件 (耗時較長)
只有當你執行了 `npm install xxx` 或修改了 `requirements.txt` 時才需要這麼做。

1. 修改後儲存，並確認同步。
2. 連線 NAS 並進入目錄。
3. 執行指令：
   ```bash
   # 若為前端套件變動 (此時無法用快取，會重新 npm install)
   sudo docker-compose build --no-cache frontend
   sudo docker-compose up -d frontend

   # 若為後端套件變動 (會重新下載 Python 大套件，需 10~15 分鐘)
   sudo docker-compose build --no-cache backend
   sudo docker-compose up -d backend
   ```

---
 
 ## 🔐 情況四：SSL 憑證與外網存取維護 (HTTPS)
 
 目前 AlphaForge 已支援 HTTPS 安全連線。若遇到連線「不安全」或憑證過期，請依序檢查：
 
 1. **憑證更新**： Let's Encrypt 通常會自動更新，但若失效，請至 DSM `控制台 > 安全性 > 憑證` 手動點選「重做」或重新申請。
 2. **反向代理檢查**： 若無法連線，請檢查 `控制台 > 登入入口 > 進階 > 反向代理伺服器`，確保 `junesnow39.synology.me` 正確指向內部的 `http://localhost:3001`。
 3. **HSTS 安全性**： 在反向代理設定中勾選「HSTS」，可以強迫瀏覽器始終使用 HTTPS 連線。
 
 ---
 
 ## 🚨 遇到問題時的「重置大法」
**!! 除非換了綁定 IP、遇到網路錯誤等底層問題，否則請不要輕易使用 !!**

如果容器出現靈異現象、各種 Port 衝突，才需要把整個 Docker 網路與層級砍掉重建：
```bash
# 1. 停止並完全刪除所有相關容器 (會斷線數分鐘)
sudo docker-compose down

# 2. 徹底重新打包 (非常耗時，後端可能需要 15 分鐘以上)
sudo docker-compose build --no-cache

# 3. 重新在背景啟動所有服務
sudo docker-compose up -d
```
> 今天我們花這麼久的時間，就是因為我們執行了這個核彈級的 `docker-compose down` 與 `--no-cache` 指令。以後請多多使用「情況一」的局部更新指令！

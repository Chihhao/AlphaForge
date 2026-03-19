# SQLite → PostgreSQL 遷移實作計畫

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 將 NAS 生產環境的資料庫從 SQLite 換成 PostgreSQL，解決 HDD 上 SQLite 查詢極慢（COUNT 需 13 秒）的問題，同時保留本地開發繼續使用 SQLite。

**Architecture:** 新增 postgres Docker 服務於 docker-compose.yml，透過 `DATABASE_URL` env var 切換，後端程式碼幾乎不需修改（SQLAlchemy ORM 已抽象化）。本地 dev 維持 SQLite，NAS production 使用 PostgreSQL。資料以一次性遷移腳本從 SQLite 搬移至 PostgreSQL。

**Tech Stack:** PostgreSQL 15, psycopg2-binary, SQLAlchemy 2.0, pandas（chunked insert 搬移資料）

---

## 檔案異動總覽

| 動作 | 檔案 | 說明 |
|---|---|---|
| 修改 | `backend/requirements.txt` | 加入 `psycopg2-binary` |
| 修改 | `docker-compose.yml` | 加入 postgres 服務，移除 SQLite volume |
| 修改 | `backend/app/db/database.py` | 移除 StaticPool（PostgreSQL 不需要） |
| 新增 | `backend/.env.nas` | NAS 生產環境的 DATABASE_URL 範本 |
| 新增 | `backend/scripts/migrate_sqlite_to_pg.py` | 資料遷移腳本 |

---

## Task 1：後端加入 PostgreSQL 驅動

**Files:**
- Modify: `backend/requirements.txt`

- [ ] **Step 1：加入 psycopg2-binary**

在 `requirements.txt` 末尾加入：
```
psycopg2-binary
```

- [ ] **Step 2：本地安裝確認**

```bash
cd backend
./.venv/bin/pip install psycopg2-binary
```
Expected: Successfully installed psycopg2-binary-x.x.x

- [ ] **Step 3：Commit**

```bash
git add backend/requirements.txt
git commit -m "feat(deps): 加入 psycopg2-binary 支援 PostgreSQL"
```

---

## Task 2：更新 docker-compose.yml

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1：修改 docker-compose.yml**

將原本內容改為：

```yaml
version: '3.8'

services:
  postgres:
    image: postgres:15-alpine
    container_name: alphaforge-postgres
    restart: unless-stopped
    environment:
      - POSTGRES_DB=alphaforge
      - POSTGRES_USER=alphaforge
      - POSTGRES_PASSWORD=alphaforge_secret
      - TZ=Asia/Taipei
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports:
      - "5432:5432"

  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile
    container_name: alphaforge-backend
    restart: unless-stopped
    ports:
      - "8000:8000"
    env_file:
      - ./backend/.env
    environment:
      - TZ=Asia/Taipei
      - DATABASE_URL=postgresql://alphaforge:alphaforge_secret@postgres:5432/alphaforge
    depends_on:
      - postgres

  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
      args:
        NEXT_PUBLIC_API_URL: /alphaforge/api
    container_name: alphaforge-frontend
    restart: unless-stopped
    ports:
      - "3001:3000"
    environment:
      - TZ=Asia/Taipei
      - NEXT_PUBLIC_API_URL=/alphaforge/api
      - INTERNAL_API_URL=http://backend:8000
    depends_on:
      - backend

volumes:
  postgres_data:
```

> **注意**：`DATABASE_URL` 設在 `environment`（會覆蓋 `.env` 的設定），本地 `.env` 維持 `sqlite:///./test.db` 不動。

- [ ] **Step 2：Commit**

```bash
git add docker-compose.yml
git commit -m "feat(infra): 加入 PostgreSQL 服務，移除 SQLite volume"
```

---

## Task 3：清理 database.py

**Files:**
- Modify: `backend/app/db/database.py`

目前 `database.py` 的 SQLite 條件判斷已正確（非 sqlite 時不套用 `StaticPool` 和 `check_same_thread`），**無需修改**。但 PostgreSQL 應啟用連線池，確認設定正確：

- [ ] **Step 1：確認 database.py 現況**

```bash
cat backend/app/db/database.py
```

確認 `engine` 建立時已有：
```python
connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {},
poolclass=StaticPool if "sqlite" in settings.DATABASE_URL else None,
```

PostgreSQL 時兩個條件都是 `{}` / `None`，SQLAlchemy 預設使用 QueuePool（5 連線），已足夠。**不需要額外修改。**

---

## Task 4：建立資料遷移腳本

**Files:**
- Create: `backend/scripts/migrate_sqlite_to_pg.py`

- [ ] **Step 1：建立遷移腳本**

```python
"""
migrate_sqlite_to_pg.py
───────────────────────
將 SQLite (test.db) 的所有資料一次性搬移至 PostgreSQL。
必須在 PostgreSQL 已啟動、且後端已執行過一次 Base.metadata.create_all 後執行。

使用方法（在 backend 目錄下）：
  PG_URL="postgresql://alphaforge:alphaforge_secret@localhost:5432/alphaforge" \
  ./.venv/bin/python scripts/migrate_sqlite_to_pg.py
"""
from __future__ import annotations
import os
import sys
import logging
import pandas as pd
from sqlalchemy import create_engine, text, inspect

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

CHUNK_SIZE = 10_000  # 每批 insert 筆數

SQLITE_URL = os.getenv("SQLITE_URL", "sqlite:///./test.db")
PG_URL = os.getenv("PG_URL", "")

if not PG_URL:
    logger.error("請設定 PG_URL 環境變數")
    sys.exit(1)

# 大表優先、有外鍵依賴的表排後
TABLE_ORDER = [
    "stocks",
    "users",
    "stock_prices",
    "stock_fundamentals",
    "stock_monthly_revenue",
    "stock_quarterly_eps",
    "stock_chip_data",
    "stock_features",
    "stock_ai_analysis",
    "alpha_miner_snapshot",
    "alpha_signal_history",
    "screener_cache",
    "system_events",
    "portfolios",
    "positions",
    "transactions",
    "watchlist_items",
]


def migrate():
    sqlite_engine = create_engine(SQLITE_URL)
    pg_engine = create_engine(PG_URL)

    inspector = inspect(sqlite_engine)
    existing_tables = set(inspector.get_table_names())

    for table in TABLE_ORDER:
        if table not in existing_tables:
            logger.info(f"[{table}] 不存在，跳過")
            continue

        # 確認 PG 表已存在
        with pg_engine.connect() as conn:
            exists = conn.execute(
                text("SELECT to_regclass(:t)"), {"t": f"public.{table}"}
            ).scalar()
            if exists is None:
                logger.warning(f"[{table}] PostgreSQL 中不存在，跳過（請先啟動後端建表）")
                continue

        # 計算總筆數
        with sqlite_engine.connect() as conn:
            total = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
        logger.info(f"[{table}] 開始遷移，共 {total:,} 筆")

        if total == 0:
            logger.info(f"[{table}] 無資料，跳過")
            continue

        # 分批讀取與寫入
        inserted = 0
        for chunk_df in pd.read_sql(f"SELECT * FROM {table}", sqlite_engine, chunksize=CHUNK_SIZE):
            chunk_df.to_sql(
                table, pg_engine,
                if_exists="append",
                index=False,
                method="multi",
            )
            inserted += len(chunk_df)
            logger.info(f"  [{table}] {inserted:,}/{total:,} 筆")

        logger.info(f"[{table}] ✅ 完成")

    logger.info("所有資料遷移完成！")


if __name__ == "__main__":
    migrate()
```

- [ ] **Step 2：Commit**

```bash
git add backend/scripts/migrate_sqlite_to_pg.py
git commit -m "feat(scripts): 新增 SQLite → PostgreSQL 資料遷移腳本"
```

---

## Task 5：本地驗證（使用 Docker 跑 PostgreSQL）

在部署 NAS 前，先在本地用 Docker 測試整套流程。

- [ ] **Step 1：本地啟動 PostgreSQL**

```bash
docker run -d \
  --name alphaforge-pg-test \
  -e POSTGRES_DB=alphaforge \
  -e POSTGRES_USER=alphaforge \
  -e POSTGRES_PASSWORD=alphaforge_secret \
  -p 5432:5432 \
  postgres:15-alpine
```

- [ ] **Step 2：啟動後端（指向本地 PostgreSQL）**

```bash
cd backend
DATABASE_URL="postgresql://alphaforge:alphaforge_secret@localhost:5432/alphaforge" \
  ./.venv/bin/python main.py
```

Expected: 後端正常啟動，SQLAlchemy 自動建立所有資料表（`create_all`），log 中看到 PostgreSQL 連線。

- [ ] **Step 3：執行遷移腳本（搬移少量資料驗證）**

```bash
cd backend
SQLITE_URL="sqlite:///./test.db" \
PG_URL="postgresql://alphaforge:alphaforge_secret@localhost:5432/alphaforge" \
  ./.venv/bin/python scripts/migrate_sqlite_to_pg.py
```

Expected: 各資料表逐筆完成，最後顯示「所有資料遷移完成！」

- [ ] **Step 4：驗證 API**

```bash
# 基本健康檢查
curl http://localhost:8000/health

# 確認股票資料存在
curl "http://localhost:8000/stocks/2330" | python3 -m json.tool

# 確認 Alpha Miner 快照載入
curl "http://localhost:8000/alpha-miner/strategies" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'策略數: {len(d[\"strategies\"])}')"
```

- [ ] **Step 5：清理測試容器**

```bash
docker stop alphaforge-pg-test && docker rm alphaforge-pg-test
```

---

## Task 6：NAS 部署

- [ ] **Step 1：確認 Synology Drive 已同步**

等待本地 git commit 同步至 NAS（約 1~2 分鐘）。

- [ ] **Step 2：強制重建（加入新套件）**

```bash
echo "4" | ./deploy.sh
# 或直接 SSH：
ssh chihhaolai@10.0.4.3 "export PATH=/usr/local/bin:\$PATH && cd /volume1/homes/chihhaolai/Drive/Documents-mac-m1/GitHub/AlphaForge && sudo /usr/local/bin/docker-compose build --no-cache && sudo /usr/local/bin/docker-compose up -d"
```

> **注意**：此時 postgres 容器會啟動，backend 會嘗試連線 PostgreSQL 並建立空資料表。

- [ ] **Step 3：確認後端正常啟動**

```bash
curl http://10.0.4.3:8000/health
```
Expected: `{"status":"healthy",...}`

- [ ] **Step 4：執行資料遷移（在 NAS backend 容器內）**

NAS 上的 SQLite 路徑需確認。先找到：

```bash
ssh chihhaolai@10.0.4.3 "sudo /usr/local/bin/docker exec alphaforge-backend ls /app/*.db 2>/dev/null || echo '無 SQLite 檔案'"
```

> **若 SQLite 已不在容器內**（因移除了 volume mount），需先將 NAS 上的 `test.db` 複製進容器，或直接在 NAS 主機上執行腳本。

遷移方式（從 NAS 主機執行，直連兩個 DB）：

```bash
ssh chihhaolai@10.0.4.3 "sudo /usr/local/bin/docker exec alphaforge-backend sh -c '
SQLITE_URL=sqlite:////volume1/homes/chihhaolai/Drive/Documents-mac-m1/GitHub/AlphaForge/backend/test.db \
PG_URL=postgresql://alphaforge:alphaforge_secret@postgres:5432/alphaforge \
python scripts/migrate_sqlite_to_pg.py
'"
```

> `stock_features` 有 140 萬筆，預計需要 10~20 分鐘。

- [ ] **Step 5：驗證 NAS API**

```bash
curl http://10.0.4.3:8000/health
curl "http://10.0.4.3:8000/alpha-miner/training-progress"
```

- [ ] **Step 6：觸發 Alpha Miner 重訓**

```bash
curl -X POST http://10.0.4.3:8000/alpha-miner/train
```

確認 `current/total` 在幾分鐘內開始跑（不再卡 0/0 超過 10 分鐘）。

- [ ] **Step 7：執行訊號歷史回填**

```bash
ssh chihhaolai@10.0.4.3 "sudo /usr/local/bin/docker exec alphaforge-backend python scripts/backfill_signal_history.py --days 45"
```

---

## 回滾方案

若 PostgreSQL 有問題，回滾步驟：

1. 將 `docker-compose.yml` 中 backend 的 `DATABASE_URL` 環境變數移除（恢復用 `.env` 的 SQLite）
2. 重新加入 SQLite volume mount：`- ./backend/test.db:/app/test.db`
3. 重新部署

---

## 預期效果

| 指標 | SQLite (HDD) | PostgreSQL |
|---|---|---|
| COUNT(*) 查詢 | 13.4 秒 | < 0.5 秒 |
| 訓練資料載入 | 10~15 分鐘 | 30~60 秒 |
| Alpha Miner 重訓總時間 | 20~30 分鐘 | 5~10 分鐘 |

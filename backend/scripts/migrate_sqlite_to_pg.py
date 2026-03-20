"""
migrate_sqlite_to_pg.py
───────────────────────
將 SQLite (test.db) 的所有資料一次性搬移至 PostgreSQL。
必須在 PostgreSQL 已啟動、且後端已執行過一次 Base.metadata.create_all 後執行。

使用方法（在 backend 容器內）：
  SQLITE_URL=sqlite:////app/test.db \
  PG_URL=postgresql://alphaforge:alphaforge_secret@postgres:5432/alphaforge \
  python scripts/migrate_sqlite_to_pg.py
"""
from __future__ import annotations
import os
import sys
import logging
import pandas as pd
from sqlalchemy import create_engine, text, inspect, types as sa_types

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

CHUNK_SIZE = 5_000  # 每批 insert 筆數（保守設定，避免記憶體壓力）

SQLITE_URL = os.getenv("SQLITE_URL", "sqlite:////app/test.db")
PG_URL = os.getenv("PG_URL", "postgresql://alphaforge:alphaforge_secret@postgres:5432/alphaforge")

# 按依賴順序排列（主表優先，有外鍵的表排後）
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
    logger.info(f"SQLite 中共有資料表：{sorted(existing_tables)}")

    total_inserted = 0

    for table in TABLE_ORDER:
        if table not in existing_tables:
            logger.info(f"[{table}] SQLite 中不存在，跳過")
            continue

        # 確認 PG 表已存在（後端啟動時 create_all 會建立）
        with pg_engine.connect() as conn:
            exists = conn.execute(
                text("SELECT to_regclass(:t)"), {"t": f"public.{table}"}
            ).scalar()
            if exists is None:
                logger.warning(f"[{table}] PostgreSQL 中尚未建表，跳過（請確認後端已啟動）")
                continue

        # 確認 PG 表是否已有資料（冪等保護）
        with pg_engine.connect() as conn:
            pg_count = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
            if pg_count > 0:
                logger.info(f"[{table}] PostgreSQL 已有 {pg_count:,} 筆，跳過（避免重複）")
                continue

        # 計算 SQLite 總筆數
        with sqlite_engine.connect() as conn:
            total = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()

        if total == 0:
            logger.info(f"[{table}] 無資料，跳過")
            continue

        # 取得 PostgreSQL 各欄位型別，用於 Boolean 轉換
        pg_bool_cols = set()
        with pg_engine.connect() as conn:
            col_rows = conn.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name=:t AND data_type='boolean'"
            ), {"t": table}).fetchall()
            pg_bool_cols = {r[0] for r in col_rows}

        logger.info(f"[{table}] 開始遷移，共 {total:,} 筆..." +
                    (f"（Boolean 欄位：{pg_bool_cols}）" if pg_bool_cols else ""))

        inserted = 0
        for chunk_df in pd.read_sql(f"SELECT * FROM {table}", sqlite_engine, chunksize=CHUNK_SIZE):
            # SQLite 把 Boolean 存成 0/1 整數，需轉成 Python bool 才能寫入 PG Boolean 欄位
            for col in pg_bool_cols:
                if col in chunk_df.columns:
                    chunk_df[col] = chunk_df[col].astype(bool)
            chunk_df.to_sql(
                table, pg_engine,
                if_exists="append",
                index=False,
                method="multi",
            )
            inserted += len(chunk_df)
            pct = round(inserted / total * 100)
            logger.info(f"  [{table}] {inserted:,}/{total:,} ({pct}%)")

        total_inserted += inserted
        logger.info(f"[{table}] ✅ 完成 ({inserted:,} 筆)")

    logger.info(f"\n{'='*50}")
    logger.info(f"遷移完成！共搬移 {total_inserted:,} 筆資料")
    logger.info(f"{'='*50}")


if __name__ == "__main__":
    migrate()

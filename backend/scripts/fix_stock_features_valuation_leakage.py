"""一次性 fix: 重寫 stock_features 的 pb_ratio / yield_rate 用 stock_valuation_daily
(historical by date) 取代既有 latest snapshot 值。

對齊 memory `feedback_data_correctness_first`: 歷史資料錯則所有研究結論失效。

只動 pb_ratio / yield_rate 兩欄。roe / revenue_yoy / rev_surprise / rev_accel 留第二階段。

Usage (從 backend/ 目錄):
    ./.venv/bin/python -m scripts.fix_stock_features_valuation_leakage
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

from sqlalchemy import create_engine, text


def _load_db_url() -> str:
    env = Path(__file__).resolve().parents[1] / ".env"
    for line in env.read_text().splitlines():
        line = line.strip()
        if line.startswith("DATABASE_URL="):
            return line.split("=", 1)[1]
    raise RuntimeError("DATABASE_URL not in backend/.env")


def main() -> int:
    db_url = _load_db_url()
    engine = create_engine(db_url, pool_pre_ping=True)

    with engine.begin() as conn:
        # 先看資料範圍
        r = conn.execute(text("""
            SELECT
              (SELECT MIN(date) FROM stock_valuation_daily) AS svd_min,
              (SELECT MAX(date) FROM stock_valuation_daily) AS svd_max,
              (SELECT COUNT(*) FROM stock_valuation_daily) AS svd_rows
        """)).fetchone()
        print(f"stock_valuation_daily: {r.svd_rows} rows, {r.svd_min} → {r.svd_max}")

        # 先看修改前 sample (2330 close 對應 pb_ratio)
        before = conn.execute(text("""
            SELECT date, pb_ratio, yield_rate
            FROM stock_features
            WHERE stock_id = '2330' AND date IN ('2025-06-02', '2025-09-01', '2026-01-02', '2026-05-13')
            ORDER BY date
        """)).fetchall()
        print("BEFORE 2330 sample:")
        for row in before:
            print(f"  {row.date}: pb={row.pb_ratio}, yield={row.yield_rate}")

        # 跑 UPDATE: stock_features.pb_ratio / yield_rate ← stock_valuation_daily 對齊 (sid, date)
        result = conn.execute(text("""
            UPDATE stock_features sf
            SET pb_ratio = svd.pb_ratio,
                yield_rate = svd.yield_rate
            FROM stock_valuation_daily svd
            WHERE sf.stock_id = svd.stock_id
              AND sf.date = svd.date
              AND sf.date >= :start
              AND sf.date <= :end
        """), {"start": r.svd_min, "end": r.svd_max})
        print(f"UPDATE affected: {result.rowcount} rows")

        # 修改後 sample
        after = conn.execute(text("""
            SELECT date, pb_ratio, yield_rate
            FROM stock_features
            WHERE stock_id = '2330' AND date IN ('2025-06-02', '2025-09-01', '2026-01-02', '2026-05-13')
            ORDER BY date
        """)).fetchall()
        print("AFTER 2330 sample:")
        for row in after:
            print(f"  {row.date}: pb={row.pb_ratio}, yield={row.yield_rate}")

        # 確認 distinct values 從 1 變多
        r2 = conn.execute(text("""
            SELECT stock_id,
                   COUNT(DISTINCT pb_ratio) AS pb_distinct,
                   COUNT(DISTINCT yield_rate) AS yield_distinct,
                   COUNT(*) AS rows
            FROM stock_features
            WHERE stock_id IN ('2330', '2317', '2454')
              AND date BETWEEN :start AND :end
            GROUP BY stock_id
        """), {"start": r.svd_min, "end": r.svd_max}).fetchall()
        print("distinct values (should be > 1 now):")
        for row in r2:
            print(f"  {row.stock_id}: pb_distinct={row.pb_distinct}, yield_distinct={row.yield_distinct}, rows={row.rows}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

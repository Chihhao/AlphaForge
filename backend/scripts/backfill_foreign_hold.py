"""
外資持股比率補填腳本（輕量版）
================================
只針對 stock_chip_data 中 foreign_hold_pct 為 NULL 的日期，
呼叫 TWSE MI_QFIIS API 取得外資持股比率，直接 UPDATE 欄位。

優點：
- 不做 DELETE，不重寫整天資料，DB 負擔極低
- 每天獨立 session，不會因 idle timeout 斷線
- 只補缺失欄位，不影響其他籌碼資料

用法：
    python scripts/backfill_foreign_hold.py
    python scripts/backfill_foreign_hold.py --start-date 2024-03-21
"""
import argparse
import logging
import os
import sys
import time
from datetime import date

sys.path.insert(0, os.getcwd())

from sqlalchemy import text
from app.db.database import SessionLocal, engine, Base
from app.services.chip_data_crawler import fetch_twse_foreign_holding

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def get_missing_dates(start_date: date) -> list:
    """查詢 stock_chip_data 中有資料但 foreign_hold_pct 為 NULL 的交易日"""
    db = SessionLocal()
    try:
        rows = db.execute(text("""
            SELECT DISTINCT date FROM stock_chip_data
            WHERE foreign_hold_pct IS NULL
            AND date >= :start_date
            ORDER BY date
        """), {"start_date": start_date}).fetchall()
        return [r[0] for r in rows]
    finally:
        db.close()


def update_foreign_hold_for_date(target_date: date) -> int:
    """取得單日外資持股比率並 UPDATE 到 stock_chip_data"""
    holding_df = fetch_twse_foreign_holding(target_date)
    if holding_df.empty:
        return 0

    db = SessionLocal()
    try:
        updated = 0
        for _, row in holding_df.iterrows():
            stock_id = str(row["stock_id"]).strip()
            pct = row.get("foreign_hold_pct")
            if not stock_id or pct is None:
                continue
            result = db.execute(text("""
                UPDATE stock_chip_data
                SET foreign_hold_pct = :pct
                WHERE stock_id = :sid AND date = :dt
                  AND foreign_hold_pct IS NULL
            """), {"pct": float(pct), "sid": stock_id, "dt": target_date})
            updated += result.rowcount
        db.commit()
        return updated
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description="外資持股比率補填腳本")
    parser.add_argument("--start-date", type=str, default="2024-03-21",
                        help="補填起始日期 YYYY-MM-DD（預設 2024-03-21）")
    args = parser.parse_args()

    start_d = date.fromisoformat(args.start_date)

    logger.info("=" * 55)
    logger.info("  外資持股比率補填啟動")
    logger.info(f"  查詢 {start_d} 之後 foreign_hold_pct IS NULL 的日期")
    logger.info("=" * 55)

    missing = get_missing_dates(start_d)
    logger.info(f"  找到 {len(missing)} 個缺失日期，開始補填...")

    total_updated = 0
    skipped = 0

    for i, d in enumerate(missing, 1):
        try:
            count = update_foreign_hold_for_date(d)
            if count == 0:
                skipped += 1
                logger.info(f"  [{i}/{len(missing)}] {d} — 無資料或已填入，跳過")
            else:
                total_updated += count
                logger.info(f"  [{i}/{len(missing)}] {d} — 更新 {count} 筆")
        except Exception as e:
            logger.error(f"  [{i}/{len(missing)}] {d} — 失敗: {e}")
        time.sleep(1.5)  # 友善爬蟲

    logger.info("=" * 55)
    logger.info(f"  補填完成！總計更新 {total_updated:,} 筆，跳過 {skipped} 天")
    logger.info("=" * 55)


if __name__ == "__main__":
    main()

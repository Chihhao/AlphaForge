"""
AlphaForge 籌碼資料批量回補腳本 (Chip Data Backfill)
=====================================================
用法:
    python scripts/backfill_chip.py [--days 60] [--start-date YYYY-MM-DD] [--end-date YYYY-MM-DD]

說明:
    從 TWSE/TPEx 抓取三大法人買賣超與融資融券餘額，逐日寫入 stock_chip_data 表。
    受限於官方 API，每次請求之間加入 2 秒延遲（友善爬蟲）。

注意:
    - TWSE/TPEx 籌碼 API 通常只保留最近 1~2 年資料，更早的資料可能無法取得。
    - 週末 / 假日會回傳空資料，腳本會自動跳過。
"""
import argparse
import logging
import os
import sys
import time
from datetime import date, timedelta

sys.path.insert(0, os.getcwd())

from app.db.database import SessionLocal, Base, engine
from app.models.stock_chip_data import StockChipData
from app.services.chip_data_crawler import sync_daily_chip_data

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="AlphaForge 籌碼資料回補腳本")
    parser.add_argument("--days",       type=int, default=60,  help="往前回補天數（預設 60）")
    parser.add_argument("--start-date", type=str,               help="開始日期 YYYY-MM-DD")
    parser.add_argument("--end-date",   type=str,               help="結束日期 YYYY-MM-DD（預設今日）")
    args = parser.parse_args()

    # 建立資料表（若尚未建立）
    Base.metadata.create_all(bind=engine)

    end_d   = date.fromisoformat(args.end_date)   if args.end_date   else date.today()
    start_d = date.fromisoformat(args.start_date) if args.start_date else end_d - timedelta(days=args.days)

    logger.info("=" * 55)
    logger.info("  AlphaForge 籌碼回補啟動")
    logger.info(f"  範圍: {start_d} ~ {end_d}")
    logger.info("=" * 55)

    db = SessionLocal()
    total_inserted = 0
    skipped = 0

    try:
        current = start_d
        while current <= end_d:
            # 跳過週末
            if current.weekday() >= 5:
                current += timedelta(days=1)
                continue

            result = sync_daily_chip_data(db, current)
            inserted = result.get("inserted", 0)
            status   = result.get("status", "")

            if status == "no_data":
                skipped += 1
                logger.info(f"  {current} — 無資料（非交易日或尚未發佈），已跳過")
            else:
                total_inserted += inserted
                logger.info(f"  {current} — 寫入 {inserted} 筆")

            current += timedelta(days=1)
            time.sleep(2)  # 友善爬蟲：每日間隔 2 秒

    except KeyboardInterrupt:
        logger.warning("使用者中斷，已儲存至中斷前的進度。")
    except Exception as e:
        logger.error(f"回補失敗: {e}", exc_info=True)
        sys.exit(1)
    finally:
        db.close()

    logger.info("=" * 55)
    logger.info(f"  回補完成！總計寫入 {total_inserted:,} 筆，跳過 {skipped} 天")
    logger.info("=" * 55)


if __name__ == "__main__":
    main()

"""
TAIFEX 選擇權 PCR 批量回補腳本
==============================
用法:
    cd backend
    ./.venv/bin/python scripts/backfill_pcr.py [--days 30] [--start-date YYYY-MM-DD]

說明:
    從 TAIFEX 抓取台指選擇權 Put/Call Ratio，逐日寫入 market_pcr 表。
    每次請求間隔 2 秒（友善爬蟲）。

注意:
    - TAIFEX 只提供近期資料，約最近 1~2 年，更早的日期可能回傳空白。
    - 週末自動跳過，已存在的日期自動跳過（冪等）。
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.database import SessionLocal, Base, engine
from app.models.market_pcr import MarketPCR
from app.services.taifex_pcr_crawler import fetch_taifex_pcr

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

DELAY_SECONDS = 2  # 每次請求間隔（秒）


def main():
    parser = argparse.ArgumentParser(description="AlphaForge PCR 回補腳本")
    parser.add_argument("--days",       type=int, default=30,  help="往前回補天數（預設 30）")
    parser.add_argument("--start-date", type=str,              help="開始日期 YYYY-MM-DD")
    parser.add_argument("--end-date",   type=str,              help="結束日期 YYYY-MM-DD（預設今日）")
    args = parser.parse_args()

    Base.metadata.create_all(bind=engine)

    end_d   = date.fromisoformat(args.end_date)   if args.end_date   else date.today()
    start_d = date.fromisoformat(args.start_date) if args.start_date else end_d - timedelta(days=args.days)

    logger.info("=" * 55)
    logger.info("  AlphaForge PCR 回補啟動")
    logger.info(f"  範圍: {start_d} ~ {end_d}")
    logger.info("=" * 55)

    db = SessionLocal()
    written = 0
    skipped_exists = 0
    skipped_nodata = 0

    try:
        current = start_d
        while current <= end_d:
            # 跳過週末
            if current.weekday() >= 5:
                current += timedelta(days=1)
                continue

            # 已存在則跳過
            exists = db.query(MarketPCR).filter(MarketPCR.date == current).first()
            if exists:
                skipped_exists += 1
                current += timedelta(days=1)
                continue

            result = fetch_taifex_pcr(current)
            if result is None:
                skipped_nodata += 1
            else:
                db.add(MarketPCR(
                    date=result["date"],
                    put_oi=result["put_oi"],
                    call_oi=result["call_oi"],
                    pcr=result["pcr"],
                ))
                db.commit()
                written += 1

            current += timedelta(days=1)
            time.sleep(DELAY_SECONDS)

    except KeyboardInterrupt:
        logger.info("使用者中斷，已寫入的資料保留。")
    except Exception as e:
        logger.error(f"回補失敗: {e}", exc_info=True)
        sys.exit(1)
    finally:
        db.close()

    logger.info("=" * 55)
    logger.info(f"  回補完成：寫入 {written} 筆 / 已存在跳過 {skipped_exists} 筆 / 無資料跳過 {skipped_nodata} 筆")
    logger.info("=" * 55)


if __name__ == "__main__":
    main()

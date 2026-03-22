"""
ETF 申贖張數批量回補腳本
=========================
用法:
    cd backend
    ./.venv/bin/python scripts/backfill_etf_flows.py [--days 60] [--start-date YYYY-MM-DD]

說明:
    從 TWSE 抓取 ETF 申購/買回受益單位數，逐日寫入 etf_flows 表。
    預設追蹤 0050（元大台灣50）。

注意:
    - TWSE ETF 資料通常保留近 1~2 年，更早的日期可能無資料。
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
from app.models.etf_flow import ETFFlow
from app.services.etf_flow_crawler import fetch_etf_flow, ETF_TARGETS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

DELAY_SECONDS = 1  # 每次請求間隔（秒）


def main():
    parser = argparse.ArgumentParser(description="AlphaForge ETF 申贖回補腳本")
    parser.add_argument("--days",       type=int, default=60,  help="往前回補天數（預設 60）")
    parser.add_argument("--start-date", type=str,              help="開始日期 YYYY-MM-DD")
    parser.add_argument("--end-date",   type=str,              help="結束日期 YYYY-MM-DD（預設今日）")
    args = parser.parse_args()

    Base.metadata.create_all(bind=engine)

    end_d   = date.fromisoformat(args.end_date)   if args.end_date   else date.today()
    start_d = date.fromisoformat(args.start_date) if args.start_date else end_d - timedelta(days=args.days)

    logger.info("=" * 55)
    logger.info("  AlphaForge ETF 申贖回補啟動")
    logger.info(f"  範圍: {start_d} ~ {end_d}")
    logger.info(f"  追蹤 ETF: {ETF_TARGETS}")
    logger.info("=" * 55)

    db = SessionLocal()
    written = 0
    skipped_exists = 0
    skipped_nodata = 0

    try:
        for etf_id in ETF_TARGETS:
            logger.info(f"--- 開始處理 {etf_id} ---")
            current = start_d
            while current <= end_d:
                if current.weekday() >= 5:
                    current += timedelta(days=1)
                    continue

                exists = (
                    db.query(ETFFlow)
                    .filter(ETFFlow.etf_id == etf_id, ETFFlow.date == current)
                    .first()
                )
                if exists:
                    skipped_exists += 1
                    current += timedelta(days=1)
                    continue

                result = fetch_etf_flow(etf_id, current)
                if result is None:
                    skipped_nodata += 1
                else:
                    db.add(ETFFlow(**result))
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

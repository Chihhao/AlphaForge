"""
全球指數歷史回補腳本
==================
用法: python scripts/backfill_global_index.py [--years 3]

從 yfinance 抓取 S&P500, NASDAQ, 費半, VIX, 美元指數的歷史收盤資料，
寫入 global_index 表。每日排程也可用此腳本更新最近資料。
"""
import argparse
import logging
import os
import sys
from datetime import date, timedelta

import pandas as pd
import yfinance as yf
from sqlalchemy import delete

sys.path.insert(0, os.getcwd())
from app.db.database import SessionLocal, Base, engine
from app.models.global_index import GlobalIndex

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

TICKERS = {
    "^GSPC": "sp500",
    "^IXIC": "nasdaq",
    "^SOX":  "sox",
    "^VIX":  "vix",
    "DX-Y.NYB": "dxy",
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--years", type=int, default=3)
    parser.add_argument("--days", type=int, default=None, help="只抓最近 N 天（日更用）")
    args = parser.parse_args()

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    start = date.today() - timedelta(days=args.days if args.days else args.years * 365)
    end = date.today()

    logger.info(f"回補全球指數: {start} ~ {end}")
    total = 0

    for ticker, index_id in TICKERS.items():
        logger.info(f"  抓取 {index_id} ({ticker})...")
        try:
            data = yf.download(ticker, start=str(start), end=str(end + timedelta(days=1)), progress=False)
        except Exception as e:
            logger.warning(f"  {index_id} 下載失敗: {e}")
            continue

        if data.empty:
            logger.warning(f"  {index_id} 無資料")
            continue

        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)

        data = data[["Close"]].dropna().copy()
        data["change_pct"] = data["Close"].pct_change() * 100
        data = data.iloc[1:]  # 第一天沒有 change_pct

        records = []
        for dt, row in data.iterrows():
            records.append(GlobalIndex(
                index_id=index_id,
                date=dt.date(),
                close=round(float(row["Close"]), 4),
                change_pct=round(float(row["change_pct"]), 4),
            ))

        if records:
            # 刪除已存在的再寫入
            db.execute(
                delete(GlobalIndex).where(
                    GlobalIndex.index_id == index_id,
                    GlobalIndex.date >= start,
                )
            )
            db.bulk_save_objects(records)
            db.commit()
            total += len(records)
            logger.info(f"  {index_id}: {len(records)} 筆")

    db.close()
    logger.info(f"完成！總計 {total} 筆")


if __name__ == "__main__":
    main()

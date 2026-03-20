"""
seed_industry.py — 一次性填入 stocks 表的 industry 欄位

使用 twstock 的 codes 字典取得產業分類（group），
批次更新 stocks 表，每 500 筆 commit 一次。
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

try:
    import twstock
except ImportError:
    logger.error("twstock 未安裝，請先執行：pip install twstock")
    sys.exit(1)

from app.db.database import SessionLocal
from app.models.user import Stock


def seed_industry():
    db = SessionLocal()
    try:
        stocks = db.query(Stock).all()
        logger.info(f"共 {len(stocks)} 筆股票待處理")

        updated = 0
        not_found = []
        batch_size = 500

        for i, stock in enumerate(stocks):
            code_info = twstock.codes.get(stock.stock_id)
            if code_info is None:
                not_found.append(stock.stock_id)
                continue

            group = getattr(code_info, 'group', None)
            if group:
                stock.industry = group
                updated += 1

            if (i + 1) % batch_size == 0:
                db.commit()
                logger.info(f"進度：{i + 1}/{len(stocks)}，已更新 {updated} 筆")

        db.commit()

        logger.info(f"完成！更新 {updated} 筆產業分類")
        if not_found:
            logger.warning(f"以下 {len(not_found)} 個 stock_id 在 twstock 中找不到：{not_found[:20]}")

    finally:
        db.close()


if __name__ == "__main__":
    seed_industry()

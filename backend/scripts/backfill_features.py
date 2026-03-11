"""
AlphaForge 特徵庫批量回補腳本 (Feature Backfill)
==============================================
用法:
    python scripts/backfill_features.py [--years 3] [--start-date YYYY-MM-DD]

說明:
    直接調用 FeatureService 對資料庫中的價格數據進行向量化指標計算，
    並存入 stock_features 表中。這是一個純計算任務，不需連網。
"""
import argparse
import sys
import os
import logging
from datetime import date, timedelta

# 設定 path 以存取 app 模組
sys.path.insert(0, os.getcwd())

from app.db.database import SessionLocal, Base, engine
from app.services.feature_service import FeatureService
from app.models.stock_feature import StockFeature

# 設定日誌
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

def main():
    parser = argparse.ArgumentParser(description="AlphaForge 特徵庫批量回補腳本")
    parser.add_argument("--years", type=int, default=3, help="回補年數 (預設 3)")
    parser.add_argument("--start-date", type=str, help="開始日期 (YYYY-MM-DD)")
    parser.add_argument("--end-date", type=str, help="結束日期 (YYYY-MM-DD)")
    args = parser.parse_args()

    # 確保表已建立
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        end_d = date.today()
        if args.end_date:
            end_d = date.fromisoformat(args.end_date)
            
        if args.start_date:
            start_d = date.fromisoformat(args.start_date)
        else:
            start_d = end_d - timedelta(days=args.years * 365)

        logger.info("=" * 50)
        logger.info("🚀 AlphaForge 特徵庫回補啟動")
        logger.info(f"   範圍: {start_d} ~ {end_d}")
        logger.info("=" * 50)

        # 呼叫服務層的回補邏輯
        total = FeatureService.backfill(db, start_d, end_d)

        logger.info("=" * 50)
        logger.info(f"✅ 回補完成！總計寫入 {total:,} 筆特徵紀錄")
        logger.info("=" * 50)

    except Exception as e:
        logger.error(f"❌ 回補失敗: {e}", exc_info=True)
        sys.exit(1)
    finally:
        db.close()

if __name__ == "__main__":
    main()

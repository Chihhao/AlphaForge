from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import logging

from app.services.stock_sync_service import StockSyncService
from app.services.market_data_crawler import MarketDataCrawler
from app.services.fundamental_service import FundamentalService
from app.db.database import SessionLocal

# 設置日誌
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()

def run_with_db(task_func):
    """輔助函數：執行任務並正確關閉資料庫會話"""
    db = SessionLocal()
    try:
        task_func(db)
    except Exception as e:
        logger.error(f"Error executing scheduled task: {e}")
    finally:
        db.close()

        # --- 第一梯次：15:00 初步同步 (收盤後第一時間) ---
        scheduler.add_job(
            lambda: run_with_db(FundamentalService.sync_twse_valuation),
            trigger=CronTrigger(hour=15, minute=0),
            id="sync_valuation_preliminary",
            name="Preliminary fundamental valuation sync",
            replace_existing=True
        )
        scheduler.add_job(
            lambda: run_with_db(FundamentalService.sync_mops_revenue),
            trigger=CronTrigger(hour=15, minute=0),
            id="sync_revenue_preliminary",
            name="Preliminary monthly revenue sync",
            replace_existing=True
        )
        scheduler.add_job(
            lambda: run_with_db(FundamentalService.sync_mops_performance),
            trigger=CronTrigger(hour=15, minute=0),
            id="sync_performance_preliminary",
            name="Preliminary performance sync",
            replace_existing=True
        )

        # 每日下午 3:30 執行市場行情
        scheduler.add_job(
            lambda: MarketDataCrawler.sync_daily_market_data(),
            trigger=CronTrigger(hour=15, minute=30),
            id="sync_market_data_daily",
            name="Daily market data synchronization from TWSE/TPEx",
            replace_existing=True
        )

        # --- 第二梯次：17:00 最終確認更新 (確保所有官方統計已入庫) ---
        scheduler.add_job(
            lambda: run_with_db(FundamentalService.sync_twse_valuation),
            trigger=CronTrigger(hour=17, minute=0),
            id="sync_valuation_final",
            name="Final fundamental valuation sync",
            replace_existing=True
        )
        scheduler.add_job(
            lambda: run_with_db(FundamentalService.sync_mops_revenue),
            trigger=CronTrigger(hour=17, minute=0),
            id="sync_revenue_final",
            name="Final monthly revenue sync",
            replace_existing=True
        )
        scheduler.add_job(
            lambda: run_with_db(FundamentalService.sync_mops_performance),
            trigger=CronTrigger(hour=17, minute=0),
            id="sync_performance_final",
            name="Final performance sync",
            replace_existing=True
        )
        
        scheduler.start()
        logger.info("Scheduler started and daily sync job added.")

def stop_scheduler():
    """停止定時任務"""
    if scheduler.running:
        scheduler.shutdown()
        logger.info("Scheduler stopped.")

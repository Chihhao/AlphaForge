from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import logging

from app.services.stock_sync_service import StockSyncService

# 設置日誌
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()

def start_scheduler():
    """啟動定時任務"""
    if not scheduler.running:
        # 每天下午 2:30 執行 (台股收盤後數據更新完畢)
        scheduler.add_job(
            StockSyncService.sync_all_stocks,
            trigger=CronTrigger(hour=14, minute=30),
            id="sync_stocks_daily",
            name="Daily stock data synchronization",
            replace_existing=True
        )
        
        # 也可以添加一個啟動時立即運行的任務（可選，通常第一次運行時手動觸發比較好）
        # scheduler.add_job(StockSyncService.sync_all_stocks, id="sync_stocks_on_start")
        
        scheduler.start()
        logger.info("Scheduler started and daily sync job added.")

def stop_scheduler():
    """停止定時任務"""
    if scheduler.running:
        scheduler.shutdown()
        logger.info("Scheduler stopped.")

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import logging
import time

from app.services.stock_sync_service import StockSyncService
from app.services.market_data_crawler import MarketDataCrawler
from app.services.fundamental_service import FundamentalService
from app.services.screener_service import ScreenerService
from app.services.feature_service import FeatureService
from app.services.chip_data_crawler import sync_daily_chip_data
from app.services.alpha_miner_service import AlphaMinerService
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

def start_scheduler():
    """啟動定時任務並設定任務"""
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
        lambda: run_with_db(lambda _: MarketDataCrawler.sync_daily_market_data()),
        trigger=CronTrigger(hour=15, minute=30),
        id="sync_market_data_daily",
        name="Daily market data synchronization from TWSE/TPEx",
        replace_existing=True
    )

    # 每日下午 3:35 同步加權指數 (^TWII) — MarketDataCrawler 只同步個股，^TWII 需獨立從 yfinance 更新
    scheduler.add_job(
        lambda: run_with_db(lambda db: StockSyncService.sync_stock_data(db, "^TWII", days=5)),
        trigger=CronTrigger(hour=15, minute=35),
        id="sync_taiex_daily",
        name="Daily TAIEX (^TWII) sync via yfinance",
        replace_existing=True
    )

    # --- 第二梯次：17:00 最終確認更新 (確保所有官方統計已入庫) ---
    def _sync_with_retry(func, db, name: str, max_retries: int = 3, retry_delay: int = 300):
        """執行單一同步任務，失敗時最多重試 max_retries 次，間隔 retry_delay 秒。"""
        for attempt in range(1, max_retries + 1):
            try:
                func(db)
                return True
            except Exception as e:
                logger.error(f"[Scheduler] {name} failed (attempt {attempt}/{max_retries}): {e}")
                if attempt < max_retries:
                    logger.info(f"[Scheduler] Retrying {name} in {retry_delay}s...")
                    time.sleep(retry_delay)
        logger.error(f"[Scheduler] {name} gave up after {max_retries} attempts.")
        return False

    def final_sync_task(db):
        _sync_with_retry(FundamentalService.sync_twse_valuation, db, "sync_twse_valuation")
        _sync_with_retry(FundamentalService.sync_tpex_valuation, db, "sync_tpex_valuation")
        _sync_with_retry(FundamentalService.sync_mops_revenue, db, "sync_mops_revenue")
        _sync_with_retry(FundamentalService.sync_mops_performance, db, "sync_mops_performance")
        FundamentalService.update_volume_avg(db)
        ScreenerService.invalidate_cache()
        ScreenerService.get_screener_results()
        logger.info("Final daily sync and cache invalidation completed.")

    scheduler.add_job(
        lambda: run_with_db(final_sync_task),
        trigger=CronTrigger(hour=17, minute=0),
        id="sync_final_batch",
        name="Final daily fundamental sync batch",
        replace_existing=True
    )

    # --- 第三梯次：16:30 抓取籌碼資料（三大法人 + 融資融券）---
    # 籌碼資料通常在 16:00~16:30 後才發佈
    scheduler.add_job(
        lambda: run_with_db(lambda db: sync_daily_chip_data(db)),
        trigger=CronTrigger(hour=16, minute=30),
        id="sync_chip_data_daily",
        name="Daily chip data sync (institutional + margin)",
        replace_existing=True
    )

    # --- 16:40 抓取選擇權 PCR ---
    scheduler.add_job(
        lambda: run_with_db(lambda db: __import__('app.services.taifex_pcr_crawler', fromlist=['sync_pcr']).sync_pcr(db, days_back=3)),
        trigger=CronTrigger(hour=16, minute=40),
        id="sync_pcr_daily",
        name="Daily TAIFEX PCR sync",
        replace_existing=True
    )

    # --- 第四梯次：17:05 計算每日特徵快照 (Alpha Miner 數據基礎) ---
    # 需在籌碼資料寫入後執行，確保籌碼欄位可以合入
    scheduler.add_job(
        lambda: run_with_db(lambda db: FeatureService.compute_daily(db)),
        trigger=CronTrigger(hour=17, minute=5),
        id="compute_daily_features",
        name="Daily feature store computation",
        replace_existing=True
    )

    # --- 第五梯次：17:10 Alpha Miner 重訓（特徵計算完成後）---
    def retrain_alpha_miner(db):
        from sqlalchemy import delete as sa_delete
        from app.models.alpha_miner_snapshot import AlphaMinerSnapshot
        db.execute(sa_delete(AlphaMinerSnapshot))
        db.commit()
        AlphaMinerService.invalidate_cache()
        AlphaMinerService.get_strategies(db)  # 觸發背景重訓

    scheduler.add_job(
        lambda: run_with_db(retrain_alpha_miner),
        trigger=CronTrigger(hour=17, minute=10),
        id="retrain_alpha_miner",
        name="Daily Alpha Miner retrain",
        replace_existing=True
    )

    # --- 第六梯次：17:45 儲存今日訊號至歷史記錄（延後確保重訓完成）---
    # Alpha Miner 重訓於 17:10 啟動，需 20-40 分鐘；save_today_signals 內部亦有等待邏輯
    scheduler.add_job(
        lambda: run_with_db(lambda db: [
            AlphaMinerService.save_today_signals(db, dim)
            for dim in ["5d", "10d", "30d"]
        ]),
        trigger=CronTrigger(hour=17, minute=45),
        id="save_signal_history",
        name="Save today alpha signals to history",
        replace_existing=True
    )

    # --- 第七梯次：17:50 回填已到期訊號的實際報酬 ---
    scheduler.add_job(
        lambda: run_with_db(AlphaMinerService.update_signal_returns),
        trigger=CronTrigger(hour=17, minute=50),
        id="update_signal_returns",
        name="Backfill actual returns for expired signals",
        replace_existing=True
    )

    # --- 第八梯次：18:00 Strategy Miner 每日推薦生成 ---
    def run_strategy_miner(db):
        from app.services.strategy_miner_service import StrategyMinerService
        StrategyMinerService.run_daily(db)

    scheduler.add_job(
        lambda: run_with_db(run_strategy_miner),
        trigger=CronTrigger(hour=18, minute=0),
        id="strategy_miner_daily",
        name="Strategy Miner daily picks generation",
        replace_existing=True
    )

    # --- 第九梯次：每週日 06:00 Strategy Miner 參數重新尋優 ---
    # 每週重算一次 18 組參數的 Sharpe 尋優（訓練集累積新資料）
    def run_strategy_miner_optimize(db):
        from app.services.strategy_miner_service import StrategyMinerService
        logger.info("[Scheduler] 開始週期性 Strategy Miner 參數尋優…")
        StrategyMinerService.run_all(db)
        StrategyMinerService.run_daily(db)
        logger.info("[Scheduler] Strategy Miner 參數尋優完成")

    scheduler.add_job(
        lambda: run_with_db(run_strategy_miner_optimize),
        trigger=CronTrigger(day_of_week='sun', hour=6, minute=0),
        id="strategy_miner_weekly_optimize",
        name="Strategy Miner weekly parameter optimization",
        replace_existing=True
    )

    scheduler.start()
    logger.info("Scheduler started and daily sync job added.")

def stop_scheduler():
    """停止定時任務"""
    if scheduler.running:
        scheduler.shutdown()
        logger.info("Scheduler stopped.")

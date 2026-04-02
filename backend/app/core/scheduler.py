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

scheduler = BackgroundScheduler(
    job_defaults={'max_instances': 1, 'coalesce': True},
    executors={'default': {'type': 'threadpool', 'max_workers': 4}},
)

def run_with_db(task_func):
    """輔助函數：執行任務並正確關閉資料庫會話"""
    db = SessionLocal()
    try:
        task_func(db)
    except Exception as e:
        logger.error(f"Error executing scheduled task: {e}")
    finally:
        db.close()

def run_on_trading_day(task_func):
    """只在交易日執行（檢查今日 stock_prices 是否 >= 500 筆）。
    國定假日、颱風假等非交易日自動跳過，避免產生幽靈資料。"""
    from datetime import date
    from sqlalchemy import text
    db = SessionLocal()
    try:
        count = db.execute(
            text("SELECT COUNT(*) FROM stock_prices WHERE date = :d"),
            {"d": date.today()},
        ).scalar()
        if count < 500:
            logger.info(f"[Scheduler] 今日 stock_prices={count} 筆，判定為非交易日，跳過任務")
            return
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
        trigger=CronTrigger(day_of_week='mon-fri', hour=15, minute=0),
        id="sync_valuation_preliminary",
        name="Preliminary fundamental valuation sync",
        replace_existing=True
    )
    scheduler.add_job(
        lambda: run_with_db(FundamentalService.sync_mops_revenue),
        trigger=CronTrigger(day_of_week='mon-fri', hour=15, minute=0),
        id="sync_revenue_preliminary",
        name="Preliminary monthly revenue sync",
        replace_existing=True
    )
    scheduler.add_job(
        lambda: run_with_db(FundamentalService.sync_mops_performance),
        trigger=CronTrigger(day_of_week='mon-fri', hour=15, minute=0),
        id="sync_performance_preliminary",
        name="Preliminary performance sync",
        replace_existing=True
    )

    # 每日下午 3:30 執行市場行情
    scheduler.add_job(
        lambda: run_with_db(lambda _: MarketDataCrawler.sync_daily_market_data()),
        trigger=CronTrigger(day_of_week='mon-fri', hour=15, minute=30),
        id="sync_market_data_daily",
        name="Daily market data synchronization from TWSE/TPEx",
        replace_existing=True
    )

    # 每日下午 3:35 同步加權指數 (^TWII) — MarketDataCrawler 只同步個股，^TWII 需獨立從 yfinance 更新
    scheduler.add_job(
        lambda: run_with_db(lambda db: StockSyncService.sync_stock_data(db, "^TWII", days=5)),
        trigger=CronTrigger(day_of_week='mon-fri', hour=15, minute=35),
        id="sync_taiex_daily",
        name="Daily TAIEX (^TWII) sync via yfinance",
        replace_existing=True
    )

    # --- 第二梯次：17:00 最終確認更新 (確保所有官方統計已入庫) ---
    def _sync_with_retry(func, db, name: str, max_retries: int = 3, retry_delay: int = 30):
        """執行單一同步任務，失敗時最多重試 max_retries 次，間隔 retry_delay 秒。
        注意：retry_delay 不可過長，否則會阻塞 BackgroundScheduler 執行緒，
        延遲後續所有排程任務。"""
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
        trigger=CronTrigger(day_of_week='mon-fri', hour=17, minute=0),
        id="sync_final_batch",
        name="Final daily fundamental sync batch",
        replace_existing=True
    )

    # --- 第三梯次：16:30 抓取籌碼資料（三大法人 + 融資融券）---
    # 籌碼資料通常在 16:00~16:30 後才發佈
    scheduler.add_job(
        lambda: run_with_db(lambda db: sync_daily_chip_data(db)),
        trigger=CronTrigger(day_of_week='mon-fri', hour=16, minute=30),
        id="sync_chip_data_daily",
        name="Daily chip data sync (institutional + margin)",
        replace_existing=True
    )

    # --- 16:45 抓取 ETF 申贖張數 ---
    scheduler.add_job(
        lambda: run_with_db(lambda db: __import__('app.services.etf_flow_crawler', fromlist=['sync_etf_flows']).sync_etf_flows(db, days_back=3)),
        trigger=CronTrigger(day_of_week='mon-fri', hour=16, minute=45),
        id="sync_etf_flows_daily",
        name="Daily ETF creation/redemption sync",
        replace_existing=True
    )

    # --- 16:50 抓取 PCR (Put/Call Ratio，選擇權未平倉) ---
    scheduler.add_job(
        lambda: run_with_db(lambda db: __import__(
            'app.services.taifex_pcr_crawler', fromlist=['sync_pcr']
        ).sync_pcr(db, days_back=3)),
        trigger=CronTrigger(day_of_week='mon-fri', hour=16, minute=50),
        id="sync_pcr_daily",
        name="Daily TAIFEX PCR sync",
        replace_existing=True
    )

    # --- 16:55 抓取 CBOE VIX 恐慌指數 ---
    scheduler.add_job(
        lambda: run_with_db(lambda db: __import__(
            'app.services.vix_crawler', fromlist=['sync_vix']
        ).sync_vix(db, days_back=7)),
        trigger=CronTrigger(day_of_week='mon-fri', hour=16, minute=55),
        id="sync_vix_daily",
        name="Daily CBOE VIX sync",
        replace_existing=True
    )

    # --- 第四梯次：17:20 計算每日特徵快照 (Alpha Miner 數據基礎) ---
    # 需在基本面最終同步（17:00，含重試最多 15 分鐘）完成後執行
    # ⚠️ 使用 run_on_trading_day：國定假日無交易資料時自動跳過
    scheduler.add_job(
        lambda: run_on_trading_day(lambda db: FeatureService.compute_daily(db)),
        trigger=CronTrigger(day_of_week='mon-fri', hour=17, minute=20),
        id="compute_daily_features",
        name="Daily feature store computation",
        replace_existing=True
    )

    # --- 第五梯次：17:30 Alpha Miner 重訓（特徵計算完成後）---
    def retrain_alpha_miner(db):
        from sqlalchemy import delete as sa_delete
        from app.models.alpha_miner_snapshot import AlphaMinerSnapshot
        db.execute(sa_delete(AlphaMinerSnapshot))
        db.commit()
        AlphaMinerService.invalidate_cache()
        AlphaMinerService.get_strategies(db)  # 觸發背景重訓

    scheduler.add_job(
        lambda: run_on_trading_day(retrain_alpha_miner),
        trigger=CronTrigger(day_of_week='mon-fri', hour=17, minute=30),
        id="retrain_alpha_miner",
        name="Daily Alpha Miner retrain",
        replace_existing=True
    )

    # --- 第六梯次：18:10 儲存今日訊號至歷史記錄（確保重訓完成）---
    # Alpha Miner 重訓於 17:30 啟動，需 12-15 分鐘；save_today_signals 內部亦有等待邏輯
    scheduler.add_job(
        lambda: run_on_trading_day(lambda db: [
            AlphaMinerService.save_today_signals(db, dim, 'long')
            for dim in ["10d", "20d"]
        ]),
        trigger=CronTrigger(day_of_week='mon-fri', hour=18, minute=10),
        id="save_signal_history",
        name="Save today alpha signals to history (10d+20d long)",
        replace_existing=True
    )

    # --- 第七梯次：18:15 回填已到期訊號的實際報酬 ---
    # update_signal_returns 不產生新資料，只回填舊訊號報酬，交易日與否皆可執行
    scheduler.add_job(
        lambda: run_with_db(AlphaMinerService.update_signal_returns),
        trigger=CronTrigger(day_of_week='mon-fri', hour=18, minute=15),
        id="update_signal_returns",
        name="Backfill actual returns for expired signals",
        replace_existing=True
    )

    # --- 第八梯次：18:20 Strategy Miner 每日參數尋優 + 推薦生成 ---
    def run_strategy_miner(db):
        from app.services.strategy_miner_service import StrategyMinerService
        logger.info("[Scheduler] 開始每日 Strategy Miner 參數尋優…")
        StrategyMinerService.run_all(db)
        StrategyMinerService.run_daily(db)
        logger.info("[Scheduler] Strategy Miner 參數尋優 + 推薦生成完成")

    scheduler.add_job(
        lambda: run_on_trading_day(run_strategy_miner),
        trigger=CronTrigger(day_of_week='mon-fri', hour=18, minute=20),
        id="strategy_miner_daily",
        name="Strategy Miner daily optimization + picks",
        replace_existing=True
    )

    # --- 第九梯次：19:30 驗證今日推薦是否已產生，若缺漏則重跑 ---
    def verify_and_retry_picks(db):
        from app.services.strategy_miner_service import StrategyMinerService
        from app.models.strategy_miner_pick import StrategyMinerPick
        from datetime import date as dt_date
        today = dt_date.today()
        count = db.query(StrategyMinerPick).filter(
            StrategyMinerPick.pick_date == today
        ).count()
        if count > 0:
            logger.info(f"[Scheduler] 今日推薦已存在 ({count} 筆)，跳過重跑")
            return
        logger.warning("[Scheduler] 今日推薦缺漏，啟動補救流程…")
        # 重跑完整流程：特徵 → Alpha Miner → 訊號 → Strategy Miner
        try:
            FeatureService.compute_daily(db)
            logger.info("[Scheduler][Retry] 特徵計算完成")
        except Exception as e:
            logger.error(f"[Scheduler][Retry] 特徵計算失敗: {e}")
        try:
            from sqlalchemy import delete as sa_delete
            from app.models.alpha_miner_snapshot import AlphaMinerSnapshot
            db.execute(sa_delete(AlphaMinerSnapshot))
            db.commit()
            AlphaMinerService.invalidate_cache()
            AlphaMinerService.get_strategies(db)
            logger.info("[Scheduler][Retry] Alpha Miner 重訓完成")
        except Exception as e:
            logger.error(f"[Scheduler][Retry] Alpha Miner 重訓失敗: {e}")
        try:
            for dim in ["10d", "20d"]:
                AlphaMinerService.save_today_signals(db, dim, 'long')
            logger.info("[Scheduler][Retry] 訊號儲存完成")
        except Exception as e:
            logger.error(f"[Scheduler][Retry] 訊號儲存失敗: {e}")
        try:
            StrategyMinerService.run_all(db)
            StrategyMinerService.run_daily(db)
            new_count = db.query(StrategyMinerPick).filter(
                StrategyMinerPick.pick_date == today
            ).count()
            logger.info(f"[Scheduler][Retry] Strategy Miner 補救完成，產生 {new_count} 筆推薦")
        except Exception as e:
            logger.error(f"[Scheduler][Retry] Strategy Miner 補救失敗: {e}")

    scheduler.add_job(
        lambda: run_on_trading_day(verify_and_retry_picks),
        trigger=CronTrigger(day_of_week='mon-fri', hour=19, minute=30),
        id="strategy_miner_verify_retry",
        name="Verify today picks exist, retry if missing",
        replace_existing=True
    )

    scheduler.start()
    logger.info("Scheduler started and daily sync job added.")

def stop_scheduler():
    """停止定時任務"""
    if scheduler.running:
        scheduler.shutdown()
        logger.info("Scheduler stopped.")

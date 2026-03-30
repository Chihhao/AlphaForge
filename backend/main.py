# Build Timestamp: 2026-02-27T18:03:00 (Forcing build context change)
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.db.database import Base, engine
from app.api.endpoints import users, stocks, indicators, glossary, market
from app.api.endpoints import alpha_miner
from app.api.endpoints import strategy_miner
from app.models.stock_price import StockPrice
from app.models.stock_fundamental import StockFundamental
from app.models.stock_revenue import StockMonthlyRevenue
from app.models.stock_eps import StockQuarterlyEPS
from app.models.system_event import SystemEvent
from app.models.stock_feature import StockFeature
from app.models.stock_chip_data import StockChipData
from app.models.market_pcr import MarketPCR
from app.models.etf_flow import ETFFlow
from app.models.alpha_miner_snapshot import AlphaMinerSnapshot
from app.models.alpha_signal_history import AlphaSignalHistory
from app.models.stock_ai_analysis import StockAIAnalysis
from app.models.strategy_backtest_param import StrategyBacktestParam
from app.models.strategy_miner_trade import StrategyMinerTrade
from app.models.strategy_miner_pick import StrategyMinerPick
from app.core.scheduler import start_scheduler, stop_scheduler



# 建立數據庫表
Base.metadata.create_all(bind=engine)

# 建立 FastAPI 應用
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="台灣股市分析平台 API",
)

@app.on_event("startup")
def startup_event():
    start_scheduler()
    _maybe_catchup_sync()


def _maybe_catchup_sync():
    """
    補跑機制：若 backend 在排程時間後才啟動（例如 NAS 晚間重啟），
    檢查今天的基本面與行情資料是否已更新，若否則在背景補同步。
    條件：現在時間 > 15:30（市場已收盤），且今日資料尚未入庫。
    """
    import threading
    from datetime import datetime, date as date_type
    from app.db.database import SessionLocal
    from app.models.stock_fundamental import StockFundamental
    from app.models.stock_price import StockPrice
    from sqlalchemy import func
    import logging

    logger = logging.getLogger(__name__)
    now = datetime.now()

    # 只在收盤後才補跑
    if now.hour < 15 or (now.hour == 15 and now.minute < 30):
        return

    def catchup():
        db = SessionLocal()
        try:
            today = date_type.today()

            # 檢查基本面是否已在今天更新過
            latest_fund = db.query(func.max(StockFundamental.updated_at)).scalar()
            needs_fundamental = (latest_fund is None or latest_fund < today)

            # 檢查今天的行情資料是否已入庫
            latest_price = db.query(func.max(StockPrice.date)).scalar()
            needs_price = (latest_price is None or latest_price < today)
        finally:
            db.close()

        if needs_price:
            logger.info("[Startup] 行情資料未更新，補跑市場資料同步...")
            try:
                from app.services.market_data_crawler import MarketDataCrawler
                MarketDataCrawler.sync_daily_market_data()
            except Exception as e:
                logger.error(f"[Startup] 市場資料補同步失敗: {e}")

        if needs_fundamental:
            logger.info("[Startup] 基本面資料未更新，補跑基本面同步...")
            db2 = SessionLocal()
            try:
                from app.services.fundamental_service import FundamentalService
                FundamentalService.sync_twse_valuation(db2)
                FundamentalService.sync_tpex_valuation(db2)
                FundamentalService.update_volume_avg(db2)
            except Exception as e:
                logger.error(f"[Startup] 基本面補同步失敗: {e}")
            finally:
                db2.close()

        # 檢查今日特徵快照是否已計算
        db3 = SessionLocal()
        try:
            from app.models.stock_feature import StockFeature
            latest_feat = db3.query(func.max(StockFeature.date)).scalar()
            needs_features = (latest_feat is None or latest_feat < today)
        finally:
            db3.close()

        # 獨立檢查籌碼資料是否需要補同步（不依賴 needs_price）
        db4 = SessionLocal()
        try:
            from app.services.chip_data_crawler import sync_daily_chip_data
            from app.models.stock_chip_data import StockChipData
            latest_chip = db4.query(func.max(StockChipData.date)).scalar()
            needs_chip = (latest_chip is None or latest_chip < today)
            if needs_chip:
                sync_daily_chip_data(db4)
                logger.info("[Startup] 籌碼資料補同步完成。")
        except Exception as e:
            logger.error(f"[Startup] 籌碼資料補同步失敗: {e}")
        finally:
            db4.close()

        if needs_features or needs_price:
            # 計算每日特徵快照
            db5 = SessionLocal()
            try:
                from app.services.feature_service import FeatureService
                FeatureService.compute_daily(db5)
                logger.info("[Startup] 特徵快照計算完成。")
            except Exception as e:
                logger.error(f"[Startup] 特徵快照計算失敗: {e}")
            finally:
                db5.close()

        if needs_price or needs_fundamental:
            try:
                from app.services.screener_service import ScreenerService
                ScreenerService.invalidate_cache()
                ScreenerService.get_screener_results()
                logger.info("[Startup] 選股快取已刷新。")
            except Exception as e:
                logger.error(f"[Startup] 選股快取刷新失敗: {e}")

        if (needs_features or needs_price) and not settings.ALPHA_MINER_READONLY:
            # 觸發 Alpha Miner 重訓（READONLY 模式下跳過，只讀 NAS 快照）
            try:
                from sqlalchemy import delete as sa_delete
                from app.models.alpha_miner_snapshot import AlphaMinerSnapshot
                from app.services.alpha_miner_service import AlphaMinerService
                db6 = SessionLocal()
                db6.execute(sa_delete(AlphaMinerSnapshot))
                db6.commit()
                db6.close()
                AlphaMinerService.invalidate_cache()
                db7 = SessionLocal()
                AlphaMinerService.get_strategies(db7)  # 觸發背景重訓子程序
                db7.close()
                logger.info("[Startup] Alpha Miner 重訓已啟動。")
            except Exception as e:
                logger.error(f"[Startup] Alpha Miner 重訓啟動失敗: {e}")

        # Strategy Miner 補跑：若 strategy_backtest_params 為空，在背景執行 run_all + run_daily
        if not settings.ALPHA_MINER_READONLY:
            try:
                from app.models.strategy_backtest_param import StrategyBacktestParam
                from app.services.strategy_miner_service import StrategyMinerService
                db8 = SessionLocal()
                has_params = db8.query(StrategyBacktestParam).first() is not None
                db8.close()
                if not has_params:
                    logger.info("[Startup] Strategy Miner 尚無回測參數，啟動背景尋優…")
                    def _run_sm():
                        db_sm = SessionLocal()
                        try:
                            StrategyMinerService.run_all(db_sm)
                            StrategyMinerService.run_daily(db_sm)
                            logger.info("[Startup] Strategy Miner 背景尋優完成")
                        except Exception as e:
                            logger.error(f"[Startup] Strategy Miner 背景尋優失敗: {e}")
                        finally:
                            db_sm.close()
                    threading.Thread(target=_run_sm, daemon=True).start()
                else:
                    # 有回測參數但可能需要更新今日推薦
                    db9 = SessionLocal()
                    try:
                        StrategyMinerService.run_daily(db9)
                    except Exception as e:
                        logger.error(f"[Startup] Strategy Miner run_daily 失敗: {e}")
                    finally:
                        db9.close()
            except Exception as e:
                logger.error(f"[Startup] Strategy Miner 補跑失敗: {e}")

        logger.info("[Startup] 補同步流程完成。")

    threading.Thread(target=catchup, daemon=True).start()

@app.on_event("shutdown")
def shutdown_event():
    stop_scheduler()


# CORS 中間件配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 註冊路由
app.include_router(users.router)
app.include_router(stocks.router)
app.include_router(indicators.router)
app.include_router(glossary.router)
app.include_router(market.router)
app.include_router(alpha_miner.router)
app.include_router(strategy_miner.router)


@app.get("/")
def read_root():
    """根路由"""
    return {
        "app_name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "description": "台灣股市分析平台 API",
        "docs": "/docs",
        "redoc": "/redoc",
    }


@app.get("/health")
def health_check():
    """健康檢查"""
    return {
        "status": "healthy",
        "app_name": settings.APP_NAME,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG,
    )

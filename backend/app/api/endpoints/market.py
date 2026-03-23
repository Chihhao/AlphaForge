"""
大盤指數概況 API 端點

提供今日市場概況數據，包含加權指數、成交量、多空比等資訊。
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Dict, Any

from app.services.market_summary_service import MarketSummaryService
from app.services.screener_service import ScreenerService
from app.services.market_data_crawler import MarketDataCrawler
from app.services.feature_service import FeatureService
from app.models.system_event import SystemEvent
from app.schemas.market import MarketSummary, AlphaStats
from app.schemas.screener import StrategyResult
from app.db.database import SessionLocal

router = APIRouter(prefix="/market", tags=["market"])

@router.get("/system-events")
def get_system_events(limit: int = 500):
    """獲取最近的系統事件日誌"""
    db = SessionLocal()
    try:
        events = db.query(SystemEvent).order_by(SystemEvent.timestamp.desc()).limit(limit).all()
        return events
    finally:
        db.close()


@router.post("/sync/daily")

def sync_daily_market_data(target_date: str = None):
    """
    手動抓取指定日期的上市櫃資料並存入資料庫
    
    格式: YYYY-MM-DD (例如: 2024-05-20)。如果不給則預設今日或前一交易日。
    供開發與測試環境使用。
    """
    from datetime import datetime
    
    date_obj = None
    if target_date:
        try:
            date_obj = datetime.strptime(target_date, "%Y-%m-%d").date()
        except ValueError:
            return {"status": "error", "message": "Invalid date format. Use YYYY-MM-DD"}
            
    result = MarketDataCrawler.sync_daily_market_data(date_obj)
    ScreenerService.invalidate_cache()
    return result


@router.get("/summary", response_model=MarketSummary)
def get_market_summary():
    """
    取得今日大盤指數概況

    回傳加權指數漲跌、成交量與均量比較、上漲/下跌家數及市場情緒判斷。
    """
    return MarketSummaryService.get_market_summary()


@router.post("/sync/fundamentals")
def sync_fundamentals(target_date: str = None):
    """
    手動同步基本面數據 (PE/PB/殖利率/ROE/營收/EPS)
    
    - target_date: TWSE 估值的目標日期 (YYYYMMDD)，不填則自動使用最近交易日
    """
    from app.services.fundamental_service import FundamentalService
    db = SessionLocal()
    results = {}
    try:
        results["valuation"] = FundamentalService.sync_twse_valuation(db, target_date)
        results["tpex_valuation"] = FundamentalService.sync_tpex_valuation(db)
        results["revenue"] = FundamentalService.sync_mops_revenue(db)
        results["eps"] = FundamentalService.sync_mops_performance(db)
        results["volume_avg"] = FundamentalService.update_volume_avg(db)
    finally:
        db.close()
    
    # 數據同步後失效選股快取，確保下次請求能看到最新結果
    ScreenerService.invalidate_cache()
    return results

@router.post("/sync/livan-stocks")
def sync_livan_stocks():
    """強制同步 Livan 的 16 檔驗證標的"""
    from app.services.fundamental_service import FundamentalService
    db = SessionLocal()
    livan_stocks = ["1264", "1535", "1615", "1777", "2247", "2453", "2937", "3227", "3515", "3570", "4933", "5236", "6143", "6189", "6486", "6728"]
    try:
        # 1. 先抓 OTC 基本資訊
        FundamentalService.sync_tpex_valuation(db)
        # 2. 強制補齊這 16 檔
        result = FundamentalService.force_sync_specific_stocks(db, livan_stocks)
        ScreenerService.invalidate_cache()
        return result
    finally:
        db.close()

@router.post("/sync/backfill-history")
def backfill_fundamentals_history():
    """
    執行一次性的歷史財務數據回填腳本 (抓取 yfinance 過去 4 年營收與 EPS)
    僅處理初步篩選通過的標的。
    """
    from app.services.fundamental_service import FundamentalService
    db = SessionLocal()
    try:
        return FundamentalService.backfill_history(db)
    finally:
        db.close()


@router.get("/screener", response_model=List[StrategyResult])
def get_screener_results():
    """
    取得今日選股雷達掃描結果

    回傳兩組策略的預選名單：
    1. 乖離率過低 (跌深反彈)
    2. 乖離率轉正 (強勢動能)

    策略門檻為系統內建固定值，不接受前端動態調整。
    """
    return ScreenerService.get_screener_results()

@router.get("/diagnose_livan")
def diagnose_livan():
    from app.models.stock_fundamental import StockFundamental
    from app.db.database import SessionLocal
    db = SessionLocal()
    # Livan 的 16 檔 + AlphaForge 多抓到的關鍵 5 檔
    livan_stocks = ["1264", "1535", "1615", "1777", "2247", "2453", "2937", "3227", "3515", "3570", "4933", "5236", "6143", "6189", "6486", "6728", "3014", "6585", "6605", "8341", "9941"]
    
    output = []
    try:
        for sid in livan_stocks:
            stock = db.query(StockFundamental).filter(StockFundamental.stock_id == sid).first()
            if not stock:
                output.append({"stock_id": sid, "status": "Not found in DB"})
                continue
                
            c1 = stock.yield_rate >= 5.0
            c2 = stock.last_revenue >= 1.0
            c3 = stock.roe_latest >= 10.0
            c4 = 0 < stock.pb_ratio <= 3.0
            c5 = (stock.eps_y1 >= 2 and stock.eps_y2 >= 2 and stock.eps_y3 >= 2 and stock.eps_y4 >= 2)
            c6 = stock.is_growth_2yr == 1
            c7 = stock.is_accelerated == 1
            
            output.append({
                "stock_id": sid,
                "name": stock.stock_name,
                "passed_count": int(sum([c1, c2, c3, c4, c5, c6, c7])),
                "details": {
                    "1.殖利率>5%": {"val": stock.yield_rate, "passed": bool(c1)},
                    "2.營收>1億": {"val": stock.last_revenue, "passed": bool(c2)},
                    "3.ROE>10%": {"val": stock.roe_latest, "passed": bool(c3)},
                    "4.PB<3": {"val": stock.pb_ratio, "passed": bool(c4)},
                    "5.EPS連4年>2": {"val": [stock.eps_y1, stock.eps_y2, stock.eps_y3, stock.eps_y4], "passed": bool(c5)},
                    "6.連2年成長": {"val": int(stock.is_growth_2yr or 0), "passed": bool(c6)},
                    "7.營收加速度": {"val": int(stock.is_accelerated or 0), "passed": bool(c7)}
                }
            })
    finally:
        db.close()
    return output


# ==================== Alpha Miner API ====================

@router.get("/alpha/stats", response_model=AlphaStats)
def get_alpha_stats():
    """
    取得 AF 精選策略的歷史勝率統計（Alpha Miner Phase 2）

    回傳訊號勝率、期望報酬、累積報酬曲線與近期 10 筆訊號紀錄。
    結果按日快取，首次呼叫需約數秒計算。
    """
    from app.services.backtest_service import BacktestService
    db = SessionLocal()
    try:
        return BacktestService.run_af_choice_backtest(db)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


# ==================== Feature Store API ====================

@router.post("/sync/features")
def sync_features():
    """手動觸發當日特徵快照計算（開發用）"""
    db = SessionLocal()
    try:
        count = FeatureService.compute_daily(db)
        return {"status": "success", "features_computed": count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.get("/features/{stock_id}")
def get_features(stock_id: str, days: int = 60):
    """查詢指定股票的歷史特徵"""
    db = SessionLocal()
    try:
        features = FeatureService.get_features(db, stock_id, days)
        return [{
            "date": str(f.date),
            "close": f.close,
            "change_pct": f.change_pct,
            "ma5": f.ma5, "ma10": f.ma10, "ma20": f.ma20, "ma60": f.ma60,
            "bias5": f.bias5, "bias10": f.bias10, "bias20": f.bias20,
            "rsi14": f.rsi14,
            "k": f.k, "d": f.d,
            "macd_dif": f.macd_dif, "macd_dea": f.macd_dea, "macd_osc": f.macd_osc,
            "bb_upper": f.bb_upper, "bb_lower": f.bb_lower, "bb_pctb": f.bb_pctb,
            "volume": f.volume, "vol_ma5": f.vol_ma5, "vol_ratio": f.vol_ratio,
            "yield_rate": f.yield_rate, "roe": f.roe,
            "pb_ratio": f.pb_ratio, "revenue_yoy": f.revenue_yoy,
        } for f in features]
    finally:
        db.close()


@router.get("/etf-flows")
def get_etf_flows(etf_id: str = "0050", days: int = 20):
    """查詢 ETF 近期申贖資料"""
    from app.models.etf_flow import ETFFlow
    db = SessionLocal()
    try:
        rows = (
            db.query(ETFFlow)
            .filter(ETFFlow.etf_id == etf_id)
            .order_by(ETFFlow.date.desc())
            .limit(days)
            .all()
        )
        return [
            {
                "date": r.date.isoformat(),
                "etf_id": r.etf_id,
                "creation": r.creation,
                "redemption": r.redemption,
                "net_flow": r.net_flow,
            }
            for r in reversed(rows)
        ]
    finally:
        db.close()



@router.get("/data-status")
def get_data_status():
    """各資料源最後更新時間（用於系統健康監控）"""
    from sqlalchemy import func
    from app.models.stock_price import StockPrice
    from app.models.stock_fundamental import StockFundamental
    from app.models.stock_chip_data import StockChipData
    from app.models.stock_feature import StockFeature
    from app.models.alpha_signal_history import AlphaSignalHistory
    from app.models.strategy_miner_pick import StrategyMinerPick
    from app.models.etf_flow import ETFFlow

    db = SessionLocal()
    try:
        def latest(model, col):
            val = db.query(func.max(col)).scalar()
            return val.isoformat() if val else None

        return {
            "stock_prices":       latest(StockPrice,          StockPrice.date),
            "fundamentals":       latest(StockFundamental,    StockFundamental.updated_at),
            "chip_data":          latest(StockChipData,       StockChipData.date),
            "stock_features":     latest(StockFeature,        StockFeature.date),
            "alpha_signals":      latest(AlphaSignalHistory,  AlphaSignalHistory.signal_date),
            "strategy_picks":     latest(StrategyMinerPick,   StrategyMinerPick.pick_date),
            "etf_flows":          latest(ETFFlow,             ETFFlow.date),
        }
    finally:
        db.close()


@router.get("/pcr")
def get_pcr(days: int = 30):
    """Put/Call Ratio 歷史資料（近 N 天）"""
    from app.models.market_pcr import MarketPCR
    db = SessionLocal()
    try:
        from datetime import date, timedelta
        from sqlalchemy import and_
        cutoff = date.today() - timedelta(days=days)
        rows = (
            db.query(MarketPCR)
            .filter(MarketPCR.date >= cutoff)
            .order_by(MarketPCR.date.asc())
            .all()
        )
        history = [{"date": r.date.isoformat(), "pcr": r.pcr, "put_oi": r.put_oi, "call_oi": r.call_oi} for r in rows]
        latest = rows[-1] if rows else None
        return {
            "latest_pcr": latest.pcr if latest else None,
            "latest_date": latest.date.isoformat() if latest else None,
            "history": history,
        }
    finally:
        db.close()

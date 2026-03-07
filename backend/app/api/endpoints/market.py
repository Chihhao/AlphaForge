"""
大盤指數概況 API 端點

提供今日市場概況數據，包含加權指數、成交量、多空比等資訊。
"""
from fastapi import APIRouter
from typing import List

from app.services.market_summary_service import MarketSummaryService
from app.services.screener_service import ScreenerService
from app.services.market_data_crawler import MarketDataCrawler
from app.models.system_event import SystemEvent
from app.schemas.market import MarketSummary
from app.schemas.screener import StrategyResult
from app.db.database import SessionLocal

router = APIRouter(prefix="/market", tags=["market"])

@router.get("/system-events")
def get_system_events(limit: int = 20):
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
            
    return MarketDataCrawler.sync_daily_market_data(date_obj)


@router.get("/summary", response_model=MarketSummary)
def get_market_summary():
    """
    取得今日大盤指數概況

    回傳加權指數漲跌、成交量與均量比較、上漲/下跌家數及市場情緒判斷。
    """
    return MarketSummaryService.get_market_summary()


@router.get("/screener", response_model=List[StrategyResult])
def get_screener_results():
    """
    取得今日選股雷達掃描結果
    
    回傳兩組策略的預選名單：
    1. 乖離率過低 (跌深反彈)
    2. 乖離率轉正 (強勢動能)
    """
    return ScreenerService.get_screener_results()

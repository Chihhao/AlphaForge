"""
大盤指數概況 API 端點

提供今日市場概況數據，包含加權指數、成交量、多空比等資訊。
"""
from fastapi import APIRouter
from typing import List

from app.services.market_summary_service import MarketSummaryService
from app.services.screener_service import ScreenerService
from app.schemas.market import MarketSummary
from app.schemas.screener import StrategyResult

router = APIRouter(prefix="/market", tags=["market"])


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

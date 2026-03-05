from pydantic import BaseModel
from typing import List, Optional


class RankingItem(BaseModel):
    stock_id: str
    stock_name: str
    price: float
    change_percent: float
    volume: int


class MarketRankingResponse(BaseModel):
    top_gainers: List[RankingItem]
    top_losers: List[RankingItem]
    top_volume: List[RankingItem]


class MarketSummary(BaseModel):
    """大盤指數概況"""
    # 加權指數基本資訊
    taiex_price: float          # 加權指數點數
    taiex_change: float         # 漲跌點數
    taiex_change_percent: float # 漲跌幅 (%)
    taiex_volume: int           # 成交量 (張)

    # 成交量比較
    avg_volume_5d: int          # 5 日平均量
    volume_ratio: float         # 量比 (今日量 / 5 日均量)

    # 多空比
    advances: int               # 上漲家數
    declines: int               # 下跌家數
    unchanged: int              # 平盤家數
    limit_up: int               # 漲停家數
    limit_down: int             # 跌停家數
    advance_decline_ratio: float # 漲跌比 (上漲 / 下跌)

    # 市場情緒標籤
    market_sentiment: str       # "bullish" | "bearish" | "neutral"
    volume_status: str          # "high" | "normal" | "low"

    # 資料時間
    data_date: str              # 資料日期 (YYYY-MM-DD)

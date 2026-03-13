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
    is_live: bool = False       # 是否為盤中即時數據
    last_updated: Optional[str] = None # 最近更新時間 (HH:MM:SS)


class RecentSignal(BaseModel):
    stock_id: str
    stock_name: str
    signal_date: str
    return_1d: Optional[float]   # None 表示資料不足，單位 %
    return_10d: Optional[float]
    outcome: str  # "win" / "loss" / "pending"


class EquityCurvePoint(BaseModel):
    date: str
    cumulative_return: float  # 累積報酬率 (0.15 = +15%)


class AlphaStats(BaseModel):
    strategy_id: str
    strategy_name: str
    win_rate_1d: float
    win_rate_10d: float
    expectancy: float           # 單筆期望報酬率
    total_signals: int
    equity_curve: List[EquityCurvePoint]
    recent_signals: List[RecentSignal]
    data_date: str              # 計算基準日

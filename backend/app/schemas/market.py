from pydantic import BaseModel
from typing import List

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

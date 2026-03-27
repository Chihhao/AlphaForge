from pydantic import BaseModel
from typing import List
from datetime import date


class ConcludedPickItem(BaseModel):
    pick_date: date
    stock_id: str
    stock_name: str
    entry_price: float
    exit_reason: str          # take_profit | stop_loss | time_limit | settled
    return_pct: float
    days_held: int
    time_dimension: str
    buy_reasons: List[str]
    take_profit_pct: float
    stop_loss_pct: float
    hold_days_max: int


class ConcludedPicksResponse(BaseModel):
    items: List[ConcludedPickItem]
    total: int

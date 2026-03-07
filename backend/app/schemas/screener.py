from pydantic import BaseModel
from typing import List

class ScreenerStock(BaseModel):
    symbol: str
    name: str
    price: float
    change: float
    bias20: float

class StrategyResult(BaseModel):
    id: str
    name: str
    description: str
    tag: str
    stocks: List[ScreenerStock]

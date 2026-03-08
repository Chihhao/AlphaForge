from pydantic import BaseModel
from typing import List, Optional

class ScreenerStock(BaseModel):
    symbol: str
    name: str
    price: float
    change: float
    bias20: float
    yield_rate: Optional[float] = None
    roe: Optional[float] = None

class StrategyResult(BaseModel):
    id: str
    name: str
    description: str
    tag: str
    stocks: List[ScreenerStock]

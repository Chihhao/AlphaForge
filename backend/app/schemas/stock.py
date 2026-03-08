from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class StockBase(BaseModel):
    """股票基本信息"""
    stock_id: str
    stock_name: str


class StockCreate(StockBase):
    """建立股票"""
    industry: Optional[str] = None
    market: Optional[str] = None
    description: Optional[str] = None


class Stock(StockBase):
    """股票響應信息"""
    id: int
    industry: Optional[str] = None
    market: Optional[str] = None
    description: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class StockQuote(BaseModel):
    """股票行情"""
    stock_id: str
    stock_name: str
    current_price: float
    open_price: float
    high_price: float
    low_price: float
    volume: int
    change_percent: float
    timestamp: datetime
    
    # 基本面指標 (可選)
    pe_ratio: Optional[float] = None
    pb_ratio: Optional[float] = None
    yield_rate: Optional[float] = None
    roe: Optional[float] = None
    last_revenue: Optional[float] = None
    revenue_growth_yoy: Optional[float] = None
    last_eps: Optional[float] = None

from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class PortfolioBase(BaseModel):
    """投資組合基本信息"""
    stock_id: int
    quantity: int
    average_cost: float


class Portfolio(PortfolioBase):
    """投資組合響應信息"""
    id: int
    user_id: int
    current_price: Optional[float] = None
    unrealized_pnl: Optional[float] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class OrderBase(BaseModel):
    """訂單基本信息"""
    stock_id: int
    order_type: str  # "買入" or "賣出"
    price_type: str  # "市價" or "限價"
    quantity: int
    price: Optional[float] = None


class OrderCreate(OrderBase):
    """建立訂單"""
    pass


class Order(OrderBase):
    """訂單響應信息"""
    id: int
    user_id: int
    status: str
    executed_quantity: int
    executed_price: Optional[float] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Text, Boolean
from sqlalchemy.orm import relationship
from datetime import datetime

from app.db.database import Base


class User(Base):
    """用户模型"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True)
    username = Column(String(100), unique=True, index=True)
    hashed_password = Column(String(255))
    full_name = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True)
    virtual_balance = Column(Float, default=1000000.0)  # 初始100萬虛擬資金
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关系
    portfolios = relationship("Portfolio", back_populates="user")
    orders = relationship("Order", back_populates="user")


class Stock(Base):
    """股票模型"""
    __tablename__ = "stocks"

    id = Column(Integer, primary_key=True, index=True)
    stock_id = Column(String(10), unique=True, index=True)  # 股票代號，如 "2330"
    stock_name = Column(String(100))  # 股票名稱，如 "台積電"
    industry = Column(String(100), nullable=True)
    market = Column(String(20), nullable=True)  # "上市" or "上櫃"
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关系
    portfolios = relationship("Portfolio", back_populates="stock")
    orders = relationship("Order", back_populates="stock")


class Portfolio(Base):
    """投資組合（持股）模型"""
    __tablename__ = "portfolios"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    stock_id = Column(Integer, ForeignKey("stocks.id"))
    quantity = Column(Integer)  # 持股數
    average_cost = Column(Float)  # 平均成本
    current_price = Column(Float, nullable=True)  # 當前價格
    unrealized_pnl = Column(Float, nullable=True)  # 未實現損益
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关系
    user = relationship("User", back_populates="portfolios")
    stock = relationship("Stock", back_populates="portfolios")


class Order(Base):
    """訂單模型"""
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    stock_id = Column(Integer, ForeignKey("stocks.id"))
    order_type = Column(String(20))  # "買入" or "賣出"
    price_type = Column(String(20))  # "市價" or "限價"
    quantity = Column(Integer)
    price = Column(Float, nullable=True)  # 限價單的價格
    status = Column(String(20), default="未成交")  # "未成交", "部分成交", "完全成交", "已取消"
    executed_quantity = Column(Integer, default=0)  # 已成交數量
    executed_price = Column(Float, nullable=True)  # 成交價
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关系
    user = relationship("User", back_populates="orders")
    stock = relationship("Stock", back_populates="orders")

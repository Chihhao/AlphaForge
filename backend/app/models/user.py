from sqlalchemy import Column, Integer, String, Float, DateTime, Text, Boolean
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
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)



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

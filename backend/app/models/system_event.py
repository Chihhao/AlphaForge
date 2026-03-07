from sqlalchemy import Column, Integer, String, DateTime, Text
from datetime import datetime
from app.db.database import Base

class SystemEvent(Base):
    """系統事件與日誌模型"""
    __tablename__ = "system_events"

    id = Column(Integer, primary_key=True, index=True)
    level = Column(String(20), index=True)  # INFO, WARNING, ERROR, SUCCESS
    message = Column(Text)
    category = Column(String(50), index=True)  # crawler, screener, system
    timestamp = Column(DateTime, default=datetime.now, index=True)

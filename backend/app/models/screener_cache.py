from sqlalchemy import Column, Integer, String, DateTime, Text, Date
from datetime import datetime
from app.db.database import Base

class ScreenerCache(Base):
    """
    選股雷達掃描結果持久化快取
    用於解決大數據量掃描導致的延遲問題。
    """
    __tablename__ = "screener_cache"

    id = Column(Integer, primary_key=True, index=True)
    strategy_id = Column(String(50), index=True)  # 例如: af_choice
    cache_date = Column(Date, index=True)       # 快取日期 (YYYY-MM-DD)
    results_json = Column(Text)                  # 序列化後的結果列表 (JSON)
    last_updated = Column(DateTime, default=datetime.now, onupdate=datetime.now)

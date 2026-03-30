from sqlalchemy import Column, Integer, Date, Float
from app.db.database import Base


class MarketVIX(Base):
    """CBOE VIX 恐慌指數每日記錄"""
    __tablename__ = "market_vix"

    id    = Column(Integer, primary_key=True)
    date  = Column(Date, unique=True, index=True)
    open  = Column(Float)
    high  = Column(Float)
    low   = Column(Float)
    close = Column(Float)

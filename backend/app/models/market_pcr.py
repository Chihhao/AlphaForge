from sqlalchemy import Column, Integer, Date, Float, BigInteger
from app.db.database import Base


class MarketPCR(Base):
    """TAIFEX 台指選擇權 Put/Call Ratio 每日記錄"""
    __tablename__ = "market_pcr"

    id       = Column(Integer, primary_key=True)
    date     = Column(Date, unique=True, index=True)
    put_oi   = Column(BigInteger)   # Put 未平倉口數
    call_oi  = Column(BigInteger)   # Call 未平倉口數
    pcr      = Column(Float)        # put_oi / call_oi

from sqlalchemy import Column, Integer, Date, Float, String, BigInteger, Index
from app.db.database import Base


class ETFFlow(Base):
    """ETF 每日申購贖回資料"""
    __tablename__ = "etf_flows"

    id           = Column(Integer, primary_key=True)
    date         = Column(Date, index=True)
    etf_id       = Column(String(10))          # e.g. "0050"
    creation     = Column(BigInteger)           # 申購張數
    redemption   = Column(BigInteger)           # 贖回張數
    net_flow     = Column(BigInteger)           # creation - redemption（正=淨申購）

    __table_args__ = (
        Index('ix_etf_flows_etf_date', 'etf_id', 'date', unique=True),
    )

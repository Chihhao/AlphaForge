"""當沖交易每日明細

資料來源：TWSE TWTB4U（上市當沖）、TPEx（上櫃當沖）。
高當沖比 → 投機過熱 → 潛在反轉訊號。
"""
from sqlalchemy import Column, Integer, String, Float, Date, BigInteger, Index
from app.db.database import Base


class StockDayTrading(Base):
    __tablename__ = "stock_day_trading"

    id = Column(Integer, primary_key=True)
    stock_id = Column(String(10), nullable=False)
    date = Column(Date, nullable=False)

    day_trade_buy_volume = Column(BigInteger)     # 當沖買進成交量（股）
    day_trade_sell_volume = Column(BigInteger)     # 當沖賣出成交量（股）
    total_volume = Column(BigInteger)             # 該股當日總成交量（股）
    day_trade_pct = Column(Float)                 # 當沖佔比（%）

    __table_args__ = (
        Index('ix_daytrade_sid_date', 'stock_id', 'date', unique=True),
    )

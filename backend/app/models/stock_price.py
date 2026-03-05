from sqlalchemy import Column, Integer, String, Float, Date, ForeignKey, Index
from sqlalchemy.orm import relationship

from app.db.database import Base


class StockPrice(Base):
    """股票每日價格數據模型"""
    __tablename__ = "stock_prices"

    id = Column(Integer, primary_key=True, index=True)
    stock_id = Column(String(10), index=True)  # 股票代號，如 "2330"
    date = Column(Date, index=True)  # 交易日期
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    adj_close = Column(Float)  # 調整後收盤價
    volume = Column(Integer)

    # 複合索引：加速特定股票的時間區間查詢
    __table_args__ = (
        Index('ix_stock_prices_stock_id_date', 'stock_id', 'date'),
    )

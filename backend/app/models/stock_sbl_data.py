"""借券賣出每日明細（Securities Borrowing and Lending）

資料來源：TWSE TWT93U（上市借券）、TPEx（上櫃借券）。
與融券不同：借券是機構級的放空行為，金額更大、意義更強。
"""
from sqlalchemy import Column, Integer, String, Float, Date, BigInteger, Index
from app.db.database import Base


class StockSBLData(Base):
    __tablename__ = "stock_sbl_data"

    id = Column(Integer, primary_key=True)
    stock_id = Column(String(10), nullable=False)
    date = Column(Date, nullable=False)

    sbl_sell_balance = Column(BigInteger)    # 借券賣出餘額（張）
    sbl_sell_today = Column(BigInteger)      # 當日借券賣出（張）
    sbl_buy_today = Column(BigInteger)       # 當日借券買回（張）
    sbl_balance = Column(BigInteger)         # 借券餘額（張，含非賣出用途）

    __table_args__ = (
        Index('ix_sbl_sid_date', 'stock_id', 'date', unique=True),
    )

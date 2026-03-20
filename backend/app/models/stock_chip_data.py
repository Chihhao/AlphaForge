from sqlalchemy import Column, Integer, String, Float, Date, BigInteger, Index
from app.db.database import Base


class StockChipData(Base):
    """每日籌碼資料（三大法人買賣超 + 融資融券餘額）

    資料來源：TWSE T86（三大法人）、MI_MARGN（融資融券）；
              TPEx 三大法人、TPEx 融資融券。
    粒度：每支股票每天一筆。
    """
    __tablename__ = "stock_chip_data"

    id = Column(Integer, primary_key=True, index=True)
    stock_id = Column(String(10), index=True)
    date = Column(Date, index=True)

    # --- 三大法人（單位：千股 = 張）---
    foreign_net_buy = Column(Float)    # 外資淨買超（+買超, -賣超）
    trust_net_buy = Column(Float)      # 投信淨買超
    dealer_net_buy = Column(Float)     # 自營商淨買超

    # --- 融資融券（單位：張）---
    margin_balance = Column(BigInteger)    # 融資餘額
    short_balance = Column(BigInteger)     # 融券餘額

    # --- 外資持股比率（Phase 6）---
    foreign_hold_pct = Column(Float, nullable=True)  # 外資持股比率（%，僅上市；上櫃為 NULL）

    __table_args__ = (
        Index('ix_chip_sid_date', 'stock_id', 'date', unique=True),
    )

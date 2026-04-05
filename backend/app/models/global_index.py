"""全球指數每日收盤資料（S&P500, NASDAQ, SOX, VIX 等）"""
from sqlalchemy import Column, String, Float, Date, UniqueConstraint
from app.db.database import Base


class GlobalIndex(Base):
    __tablename__ = 'global_index'

    id = Column('id', __import__('sqlalchemy').Integer, primary_key=True, autoincrement=True)
    index_id = Column(String(20), nullable=False)   # sp500, nasdaq, sox, vix, dxy, ...
    date = Column(Date, nullable=False)
    close = Column(Float)
    change_pct = Column(Float)                       # 日漲跌幅 (%)

    __table_args__ = (
        UniqueConstraint('index_id', 'date', name='uq_global_index_id_date'),
    )

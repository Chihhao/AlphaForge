from sqlalchemy import Column, Integer, BigInteger, String, Float, Date, ForeignKey, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import insert as pg_insert
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
    volume = Column(BigInteger)

    # 複合索引：加速特定股票的時間區間查詢
    __table_args__ = (
        Index('ix_stock_prices_stock_id_date', 'stock_id', 'date'),
        UniqueConstraint('stock_id', 'date', name='uq_stock_prices_stock_date'),
    )


def bulk_upsert_stock_prices(db, price_objs):
    # 由 uq_stock_prices_stock_date 兜底，race condition 下同日同股重複時沉默略過
    if not price_objs:
        return 0
    records = [{
        'stock_id': p.stock_id,
        'date': p.date,
        'open': p.open,
        'high': p.high,
        'low': p.low,
        'close': p.close,
        'adj_close': p.adj_close,
        'volume': p.volume,
    } for p in price_objs]
    stmt = pg_insert(StockPrice).values(records).on_conflict_do_nothing(
        index_elements=['stock_id', 'date']
    )
    return db.execute(stmt).rowcount

from sqlalchemy import Column, Integer, String, Float, Date, Index
from app.db.database import Base


class StockQuarterlyEPS(Base):
    """股票每季 EPS 歷史模型"""
    __tablename__ = "stock_eps_history"

    id = Column(Integer, primary_key=True, index=True)
    stock_id = Column(String(10), index=True)
    year = Column(Integer)
    quarter = Column(Integer)
    eps = Column(Float)                # 每股盈餘
    eps_yoy = Column(Float, nullable=True) # EPS 年增率 (選填)
    
    updated_at = Column(Date)

    __table_args__ = (
        Index('ix_eps_stock_date', 'stock_id', 'year', 'quarter', unique=True),
    )

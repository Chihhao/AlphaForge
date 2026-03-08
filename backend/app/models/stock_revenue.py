from sqlalchemy import Column, Integer, String, Float, Date, Index
from app.db.database import Base


class StockMonthlyRevenue(Base):
    """股票每月營收歷史模型"""
    __tablename__ = "stock_revenue_history"

    id = Column(Integer, primary_key=True, index=True)
    stock_id = Column(String(10), index=True)
    year = Column(Integer)
    month = Column(Integer)
    revenue = Column(Float)            # 營收 (億)
    revenue_yoy = Column(Float)        # 營收年增率 (%)
    revenue_mom = Column(Float)        # 營收月增率 (%)
    
    updated_at = Column(Date)

    __table_args__ = (
        Index('ix_revenue_stock_date', 'stock_id', 'year', 'month', unique=True),
    )

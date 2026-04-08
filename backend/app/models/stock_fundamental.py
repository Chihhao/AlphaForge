from sqlalchemy import Column, Integer, String, Float, Date, Index
from app.db.database import Base


class StockFundamental(Base):
    """股票基本面快照模型 (用於 7 大條件篩選)"""
    __tablename__ = "stock_fundamentals"

    id = Column(Integer, primary_key=True, index=True)
    stock_id = Column(String(10), index=True, unique=True)  # 股票代號
    stock_name = Column(String(50))  # 證券名稱
    
    # 估值維度 (每日/更新頻率較高)
    yield_rate = Column(Float, nullable=True)   # 殖利率(%)
    pe_ratio = Column(Float, nullable=True)     # 本益比
    pb_ratio = Column(Float, nullable=True)     # 股價淨值比

    # 獲利與規模維度 (月/季更新)
    last_revenue = Column(Float, nullable=True)       # 最新月營收 (億)
    revenue_growth_yoy = Column(Float, nullable=True)  # 營收年增率 (%)
    roe_latest = Column(Float, nullable=True)         # 最新 ROE (%)
    eps_y1 = Column(Float, nullable=True)            # 去年 EPS
    eps_y2 = Column(Float, nullable=True)            # 前年 EPS
    eps_y3 = Column(Float, nullable=True)            # 大前年 EPS
    eps_y4 = Column(Float, nullable=True)            # 四年前 EPS

    # 流動性維度
    volume_avg_5d = Column(Float, nullable=True)     # 5 日平均成交量 (張)
    
    # 複合計算欄位 (預計算標記，加速篩選)
    is_growth_2yr = Column(Integer, default=0)    # 連續 2 年營收成長 > 5%
    is_accelerated = Column(Integer, default=0)   # 營收成長 > 4 年平均
    
    updated_at = Column(Date) # 最後更新日期

    __table_args__ = (
        Index('ix_stock_fundamentals_yield_pb', 'yield_rate', 'pb_ratio'),
    )

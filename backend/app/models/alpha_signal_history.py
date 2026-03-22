from sqlalchemy import Column, Integer, String, Date, Float, Boolean, UniqueConstraint, Index
from app.db.database import Base


class AlphaSignalHistory(Base):
    """Alpha Miner 每日訊號歷史記錄

    每次 save_today_signals 呼叫後批次寫入今日推薦股票。
    持有期結束後由 update_signal_returns 回填實際報酬。
    """
    __tablename__ = "alpha_signal_history"

    id             = Column(Integer, primary_key=True)
    signal_date    = Column(Date, index=True)        # 訊號發出日
    stock_id       = Column(String(10), index=True)
    stock_name     = Column(String(50))
    time_dimension = Column(String(5))               # "5d" / "10d" / "30d"
    trigger_count  = Column(Integer)
    weighted_win_rate   = Column(Float)
    weighted_odds_ratio = Column(Float)
    # 回填欄位（持有期結束後計算）
    actual_return  = Column(Float, nullable=True)    # 實際報酬率
    resolved_date  = Column(Date, nullable=True)     # 結算日期
    is_resolved    = Column(Boolean, default=False)

    __table_args__ = (
        UniqueConstraint('signal_date', 'stock_id', 'time_dimension',
                         name='uq_signal_history'),
        Index('ix_signal_history_dim_date', 'time_dimension', 'signal_date'),
    )

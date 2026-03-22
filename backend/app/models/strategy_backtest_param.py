from sqlalchemy import Column, Integer, String, Float, Boolean, Date
from app.db.database import Base

class StrategyBacktestParam(Base):
    __tablename__ = "strategy_backtest_params"
    id               = Column(Integer, primary_key=True)
    strategy_id      = Column(String(100), index=True)  # "5d" / "10d" / "30d"
    take_profit_pct  = Column(Float)   # 0.05 / 0.08 / 0.12
    stop_loss_pct    = Column(Float)   # 0.03 / 0.05 / 0.08
    hold_days_max    = Column(Integer) # 10 / 20
    sharpe_train     = Column(Float)
    sharpe_test      = Column(Float)
    win_rate_test    = Column(Float)
    avg_return_test  = Column(Float)
    trade_count_test = Column(Integer)
    is_optimal       = Column(Boolean, default=False)
    computed_at      = Column(Date)

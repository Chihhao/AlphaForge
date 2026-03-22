from sqlalchemy import Column, Integer, String, Float, Date, Index
from app.db.database import Base

class StrategyMinerTrade(Base):
    __tablename__ = "strategy_miner_trades"
    id           = Column(Integer, primary_key=True)
    strategy_id  = Column(String(100), index=True)  # "5d" / "10d" / "30d"
    stock_id     = Column(String(10), index=True)
    entry_date   = Column(Date)
    entry_price  = Column(Float)
    exit_date    = Column(Date)
    exit_price   = Column(Float)
    exit_reason  = Column(String(20))  # take_profit / stop_loss / time_limit
    return_pct   = Column(Float)       # percentage e.g. 7.9
    hold_days    = Column(Integer)

    __table_args__ = (
        Index('ix_strategy_miner_trades_stock_strategy', 'stock_id', 'strategy_id'),
    )

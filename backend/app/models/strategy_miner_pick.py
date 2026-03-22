from sqlalchemy import Column, Integer, String, Float, Date, Text, UniqueConstraint
from app.db.database import Base

class StrategyMinerPick(Base):
    __tablename__ = "strategy_miner_picks"
    id              = Column(Integer, primary_key=True)
    pick_date       = Column(Date, index=True)
    stock_id        = Column(String(10))
    stock_name      = Column(String(50))
    strategy_ids    = Column(Text)     # JSON array of time dimensions
    weighted_score  = Column(Float)
    entry_price     = Column(Float)    # latest close price
    take_profit_pct = Column(Float)    # from optimal params (e.g. 0.08)
    stop_loss_pct   = Column(Float)    # from optimal params (e.g. 0.05)
    hold_days_max   = Column(Integer)
    time_dimension  = Column(String(5))
    buy_reasons     = Column(Text, nullable=True)  # JSON array of strategy name strings

    __table_args__ = (
        UniqueConstraint('pick_date', 'stock_id', name='uq_strategy_miner_pick'),
    )

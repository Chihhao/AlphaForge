from sqlalchemy import Column, Integer, Date, Text
from app.db.database import Base


class AlphaMinerSnapshot(Base):
    """Alpha Miner 訓練結果持久化快照

    每次訓練完成後將結果序列化為 JSON 存入此表。
    後端重啟時直接從此表恢復，無需重新訓練。
    """
    __tablename__ = "alpha_miner_snapshot"

    id = Column(Integer, primary_key=True)
    train_date = Column(Date, index=True, unique=True)
    result_json = Column(Text, nullable=False)   # AlphaMinerResult（排行榜列表）
    details_json = Column(Text, nullable=False)  # Dict[strategy_id, StrategyDetail]

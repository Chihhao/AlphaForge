from sqlalchemy import Column, Integer, String, Float, Date, Index
from app.db.database import Base


class StockFeature(Base):
    """每日每股原子指標特徵快照模型
    
    用途：預計算並儲存全市場技術指標 + 基本面摘要，作為 Alpha Miner 回測引擎的數據基礎。
    粒度：每支股票每天一筆記錄。
    """
    __tablename__ = "stock_features"

    id = Column(Integer, primary_key=True, index=True)
    stock_id = Column(String(10), index=True)
    date = Column(Date, index=True)

    # --- 價格衍生 ---
    close = Column(Float)
    change_pct = Column(Float)       # 日漲跌幅 (%)

    # --- 均線系列 ---
    ma5 = Column(Float)
    ma10 = Column(Float)
    ma20 = Column(Float)
    ma60 = Column(Float)

    # --- 乖離率 ---
    bias5 = Column(Float)
    bias10 = Column(Float)
    bias20 = Column(Float)

    # --- RSI ---
    rsi14 = Column(Float)

    # --- KD ---
    k = Column(Float)
    d = Column(Float)

    # --- MACD ---
    macd_dif = Column(Float)
    macd_dea = Column(Float)
    macd_osc = Column(Float)

    # --- 布林通道 ---
    bb_upper = Column(Float)
    bb_lower = Column(Float)
    bb_pctb = Column(Float)          # %B 位置 (0~1)

    # --- 成交量 ---
    volume = Column(Integer)
    vol_ma5 = Column(Float)          # 5 日均量
    vol_ratio = Column(Float)        # 量比 (volume / vol_ma5)

    # --- 基本面快照 (從 StockFundamental 帶入) ---
    yield_rate = Column(Float)
    roe = Column(Float)
    pb_ratio = Column(Float)
    revenue_yoy = Column(Float)

    # 複合唯一索引：每支股票每天只有一筆
    __table_args__ = (
        Index('ix_sf_sid_date', 'stock_id', 'date', unique=True),
    )

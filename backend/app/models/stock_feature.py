from sqlalchemy import Column, Integer, BigInteger, String, Float, Date, Index
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
    volume = Column(BigInteger)
    vol_ma5 = Column(Float)          # 5 日均量
    vol_ratio = Column(Float)        # 量比 (volume / vol_ma5)

    # --- 基本面快照 (從 StockFundamental 帶入) ---
    yield_rate = Column(Float)
    roe = Column(Float)
    pb_ratio = Column(Float)
    revenue_yoy = Column(Float)

    # --- 籌碼面（Phase 4B，從 StockChipData 衍生）---
    foreign_net_buy = Column(Float)    # 外資單日淨買超（張）
    foreign_buy_5d = Column(Float)     # 外資5日累積淨買超（張）
    trust_net_buy = Column(Float)      # 投信單日淨買超（張）
    trust_buy_5d = Column(Float)       # 投信5日累積淨買超（張）
    margin_chg_5d = Column(Float)      # 融資餘額5日變化率（%）

    # --- 籌碼面（Phase 5B）---
    dealer_net_buy = Column(Float, nullable=True)    # 自營商單日淨買超（張）
    dealer_buy_5d  = Column(Float, nullable=True)    # 自營商5日累積淨買超（張）

    # --- 技術面新因子（Phase 5B）---
    price_vs_high20 = Column(Float, nullable=True)   # (close - 20日高點) / 20日高點
    ma_trend        = Column(Float, nullable=True)   # 均線多頭排列：MA5>MA10>MA20=1，否則=0

    # --- 產業相對強度 + 外資持股（Phase 6）---
    sector_rs           = Column(Float, nullable=True)  # 個股20日報酬 - 同產業中位數報酬
    foreign_hold_pct    = Column(Float, nullable=True)  # 全體外資持股比率（%，僅上市）
    foreign_hold_chg_5d = Column(Float, nullable=True)  # 外資持股比率5日變化（百分點）

    # --- 市場指標（Phase 3A）---
    market_pcr = Column(Float, nullable=True)  # 台指選擇權 Put/Call Ratio

    # --- 市場指標（Phase 3B）---
    etf_net_flow_5d = Column(Float, nullable=True)  # 0050 近5日累計淨申購（萬張，正=資金流入）

    # --- 籌碼面中長期（Phase 7）---
    foreign_buy_10d = Column(Float, nullable=True)   # 外資10日累積淨買超（張）
    foreign_buy_20d = Column(Float, nullable=True)   # 外資20日累積淨買超（張）
    trust_buy_10d   = Column(Float, nullable=True)   # 投信10日累積淨買超（張）
    trust_buy_20d   = Column(Float, nullable=True)   # 投信20日累積淨買超（張）
    dealer_buy_10d  = Column(Float, nullable=True)   # 自營商10日累積淨買超（張）
    dealer_buy_20d  = Column(Float, nullable=True)   # 自營商20日累積淨買超（張）

    # --- 波動率（Phase 7）---
    atr20   = Column(Float, nullable=True)    # 20日 Average True Range
    atr_pct = Column(Float, nullable=True)    # ATR / close × 100（波動率百分比）

    # --- 市場狀態（Phase 7）---
    market_breadth = Column(Float, nullable=True)  # 全市場站上 MA20 的股票比例 (0~1)
    market_trend   = Column(Float, nullable=True)  # 全市場中位數 20 日報酬 > 0 為 1，否則 0

    # 複合唯一索引：每支股票每天只有一筆
    __table_args__ = (
        Index('ix_sf_sid_date', 'stock_id', 'date', unique=True),
    )

from sqlalchemy import Column, Integer, String, Float, Date, Index
from app.db.database import Base


class StockValuationDaily(Base):
    """每日個股估值 (PE / PB / 殖利率) 歷史資料。

    資料來源: TWSE BWIBBU_d (個股日本益比、殖利率及股價淨值比)
              + TPEx 對應 endpoint (後續擴充)。
    粒度: 每支股票每天一筆。
    用途: 取代 stock_fundamentals (latest snapshot) 在 stock_features 的 pb_ratio /
          yield_rate 欄位, 解 historical backtest 的 forward-looking bias。
    """
    __tablename__ = "stock_valuation_daily"

    id = Column(Integer, primary_key=True, index=True)
    stock_id = Column(String(10), index=True)
    date = Column(Date, index=True)

    close = Column(Float, nullable=True)
    yield_rate = Column(Float, nullable=True)         # 殖利率 (%)
    pe_ratio = Column(Float, nullable=True)           # 本益比 (TWSE '-' → NULL)
    pb_ratio = Column(Float, nullable=True)           # 股價淨值比
    dividend_year = Column(Integer, nullable=True)    # 股利年度 (民國年)
    report_period = Column(String(10), nullable=True) # 財報年/季 e.g. "115/1"

    __table_args__ = (
        Index("ix_svd_sid_date", "stock_id", "date", unique=True),
    )

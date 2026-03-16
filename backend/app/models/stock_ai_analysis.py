from sqlalchemy import Column, Integer, String, Text, DateTime, Index
from datetime import datetime
from app.db.database import Base


class StockAIAnalysis(Base):
    """個股 AI 分析快取，以 (stock_id, date) 為唯一鍵，當天共用同一份分析"""
    __tablename__ = "stock_ai_analysis"

    id = Column(Integer, primary_key=True, index=True)
    stock_id = Column(String(10), nullable=False)
    date = Column(String(10), nullable=False)   # YYYY-MM-DD
    analysis_text = Column(Text, nullable=False)
    model = Column(String(64), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index('ix_saa_stock_date', 'stock_id', 'date', unique=True),
    )

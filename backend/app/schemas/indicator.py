from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

class KDValue(BaseModel):
    timestamp: datetime
    k: float
    d: float
    rsv: float

class IndicatorResponse(BaseModel):
    stock_id: str
    indicator_type: str
    values: List[KDValue]

class KDStatus(BaseModel):
    """用於顯示當前 KD 狀態的簡化 schema"""
    k: float
    d: float
    status: str # 如 "超買", "超賣", "中性"
    signal: Optional[str] = None # 如 "黃金交叉", "死亡交叉"

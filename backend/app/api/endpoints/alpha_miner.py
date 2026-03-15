"""
Alpha Miner API — 邏輯迴歸多因子策略排行榜
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete as sa_delete
from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.models.alpha_miner_snapshot import AlphaMinerSnapshot
from app.services.alpha_miner_service import AlphaMinerService
from app.schemas.alpha_miner import AlphaMinerResult, StrategyDetail, TodaySignal
from typing import List

router = APIRouter(prefix="/alpha-miner", tags=["alpha-miner"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/strategies", response_model=AlphaMinerResult)
def get_strategies(db: Session = Depends(get_db)):
    """回傳所有因子組合的邏輯迴歸訓練結果，依樣本外 IC 排序"""
    return AlphaMinerService.get_strategies(db)


@router.get("/strategies/{strategy_id}", response_model=StrategyDetail)
def get_strategy_detail(strategy_id: str, db: Session = Depends(get_db)):
    """回傳單一策略詳情：因子權重、損益曲線、近期訊號"""
    detail = AlphaMinerService.get_strategy_detail(strategy_id, db)
    if detail is None:
        raise HTTPException(status_code=404, detail="Strategy not found")
    return detail


@router.get("/signals/today", response_model=List[TodaySignal])
def get_today_signals(dimension: str = "10d", db: Session = Depends(get_db)):
    """回傳今日最強訊號：被多個顯著策略同時看好的股票，依觸發策略數排序"""
    return AlphaMinerService.get_today_signals(db, dimension=dimension)


@router.get("/training-progress")
def get_training_progress():
    """回傳目前訓練進度（百分比、目前維度、目前策略）"""
    return AlphaMinerService.get_progress()


@router.post("/train")
def retrain(db: Session = Depends(get_db)):
    """手動觸發重新訓練（子程序執行，立即回傳）。

    會先刪除 DB 快照 + 終止現有訓練子程序，確保從頭重算。
    """
    db.execute(sa_delete(AlphaMinerSnapshot))
    db.commit()
    AlphaMinerService.invalidate_cache()
    AlphaMinerService.get_strategies(db)  # 觸發新子程序啟動
    return {"status": "training_started", "message": "模型重新訓練已啟動，請稍後刷新頁面"}

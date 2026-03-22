"""
Strategy Miner API — 每日推薦清單 + 歷史交易記錄
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List
from datetime import date

from app.db.database import get_db
from app.services.strategy_miner_service import StrategyMinerService

router = APIRouter(prefix="/strategy-miner", tags=["strategy-miner"])


@router.get("/picks/today")
def get_today_picks(db: Session = Depends(get_db)):
    """今日推薦清單（含真實停利停損參數）"""
    picks = StrategyMinerService.get_today_picks(db)
    return [
        {
            "pick_date": p.pick_date.isoformat(),
            "stock_id": p.stock_id,
            "stock_name": p.stock_name,
            "strategy_ids": p.strategy_ids,
            "weighted_score": p.weighted_score,
            "entry_price": p.entry_price,
            "take_profit_pct": p.take_profit_pct,
            "stop_loss_pct": p.stop_loss_pct,
            "hold_days_max": p.hold_days_max,
            "time_dimension": p.time_dimension,
        }
        for p in picks
    ]


@router.get("/picks/history")
def get_picks_history(days: int = 7, db: Session = Depends(get_db)):
    """過去 N 天的推薦記錄"""
    picks = StrategyMinerService.get_picks_history(db, days=days)
    return [
        {
            "pick_date": p.pick_date.isoformat(),
            "stock_id": p.stock_id,
            "stock_name": p.stock_name,
            "weighted_score": p.weighted_score,
            "entry_price": p.entry_price,
            "take_profit_pct": p.take_profit_pct,
            "stop_loss_pct": p.stop_loss_pct,
            "hold_days_max": p.hold_days_max,
            "time_dimension": p.time_dimension,
        }
        for p in picks
    ]


@router.get("/trades/{stock_id}")
def get_trades(stock_id: str, db: Session = Depends(get_db)):
    """某股票的歷史逐筆交易記錄"""
    trades = StrategyMinerService.get_trades(db, stock_id)
    return [
        {
            "strategy_id": t.strategy_id,
            "stock_id": t.stock_id,
            "entry_date": t.entry_date.isoformat(),
            "entry_price": t.entry_price,
            "exit_date": t.exit_date.isoformat() if t.exit_date else None,
            "exit_price": t.exit_price,
            "exit_reason": t.exit_reason,
            "return_pct": t.return_pct,
            "hold_days": t.hold_days,
        }
        for t in trades
    ]


@router.get("/performance")
def get_performance(db: Session = Depends(get_db)):
    """整體績效統計（各維度最優參數回測結果）"""
    return StrategyMinerService.get_performance(db)


@router.post("/run-optimization")
def run_optimization(db: Session = Depends(get_db)):
    """手動觸發參數尋優（通常由排程執行）"""
    StrategyMinerService.run_all(db)
    return {"status": "ok", "message": "Strategy Miner 參數尋優已完成"}


@router.post("/run-daily")
def run_daily(db: Session = Depends(get_db)):
    """手動觸發今日推薦生成（通常由排程執行）"""
    count = StrategyMinerService.run_daily(db)
    return {"status": "ok", "picks_generated": count}

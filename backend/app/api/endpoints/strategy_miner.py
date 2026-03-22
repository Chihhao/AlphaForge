"""
Strategy Miner API — 每日推薦清單 + 歷史交易記錄
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List
from datetime import date

from app.db.database import get_db
from app.services.strategy_miner_service import StrategyMinerService
from app.models.strategy_backtest_param import StrategyBacktestParam
from app.models.strategy_miner_trade import StrategyMinerTrade
from sqlalchemy import func

router = APIRouter(prefix="/strategy-miner", tags=["strategy-miner"])


def _load_stock_perf_map(db: Session, stock_ids: list[str]) -> dict:
    """載入指定股票的逐筆回測績效，回傳 {stock_id: {win_rate, avg_return, trade_count}}"""
    if not stock_ids:
        return {}
    rows = (
        db.query(StrategyMinerTrade)
        .filter(StrategyMinerTrade.stock_id.in_(stock_ids))
        .all()
    )
    # 按 stock_id 分組計算
    from collections import defaultdict
    by_stock: dict = defaultdict(list)
    for r in rows:
        by_stock[r.stock_id].append(r.return_pct)
    result = {}
    for sid, rets in by_stock.items():
        wins = sum(1 for x in rets if x > 0)
        result[sid] = {
            "stock_win_rate": round(wins / len(rets), 4),
            "stock_avg_return": round(sum(rets) / len(rets), 4),
            "stock_trade_count": len(rets),
        }
    return result


@router.get("/picks/today")
def get_today_picks(db: Session = Depends(get_db)):
    """今日推薦清單（含真實停利停損參數 + 個股回測績效）"""
    picks = StrategyMinerService.get_today_picks(db)
    stock_ids = [p.stock_id for p in picks]
    stock_perf = _load_stock_perf_map(db, stock_ids)
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
            **stock_perf.get(p.stock_id, {
                "stock_win_rate": None,
                "stock_avg_return": None,
                "stock_trade_count": 0,
            }),
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

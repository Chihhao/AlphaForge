"""驗證 per-dimension picks 架構: 同股同天同方向可有多筆 (不同維度)。"""
import json as _json
from datetime import date

from app.db.database import SessionLocal
from app.models.strategy_miner_pick import StrategyMinerPick


def test_same_stock_same_day_multiple_dims_allowed():
    db = SessionLocal()
    try:
        db.query(StrategyMinerPick).filter(
            StrategyMinerPick.pick_date == date(2099, 1, 1),
            StrategyMinerPick.stock_id == 'TEST1',
        ).delete()
        db.commit()

        for dim in ('5d', '10d', '20d'):
            db.add(StrategyMinerPick(
                pick_date=date(2099, 1, 1),
                stock_id='TEST1',
                stock_name='測試股',
                strategy_ids=_json.dumps([dim]),
                weighted_score=1.0,
                entry_price=100.0,
                take_profit_pct=0.05,
                stop_loss_pct=0.03,
                hold_days_max=int(dim[:-1]),
                time_dimension=dim,
                direction='long',
                buy_reasons='[]',
            ))
        db.commit()

        got = db.query(StrategyMinerPick).filter(
            StrategyMinerPick.pick_date == date(2099, 1, 1),
            StrategyMinerPick.stock_id == 'TEST1',
            StrategyMinerPick.direction == 'long',
        ).all()
        assert len(got) == 3, f"預期 3 筆 (三維度), 實際 {len(got)}"

        db.query(StrategyMinerPick).filter(
            StrategyMinerPick.pick_date == date(2099, 1, 1),
            StrategyMinerPick.stock_id == 'TEST1',
        ).delete()
        db.commit()
    finally:
        db.close()

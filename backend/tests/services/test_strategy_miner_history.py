"""
測試真實推薦歷史 helpers: _evaluate_pick_concluded, _load_stock_perf_from_picks
"""
from __future__ import annotations
from datetime import date
import pytest
from unittest.mock import MagicMock

from app.services.strategy_miner_service import StrategyMinerService
from app.models.strategy_miner_pick import StrategyMinerPick


def _mk_pick(
    stock_id='3710', pick_date=date(2026, 3, 1),
    entry_price=10.0, tp=0.08, sl=0.05, hd=20,
    direction='long', time_dimension='20d',
):
    p = StrategyMinerPick(
        pick_date=pick_date, stock_id=stock_id, stock_name='連展投控',
        strategy_ids='["20d"]', weighted_score=1.0, entry_price=entry_price,
        take_profit_pct=tp, stop_loss_pct=sl, hold_days_max=hd,
        time_dimension=time_dimension, direction=direction,
    )
    return p


class TestEvaluatePickConcluded:
    def test_take_profit_hit(self):
        """後續收盤達 entry x (1+tp) 當天結算為停利."""
        pick = _mk_pick(entry_price=10.0, tp=0.08)
        prices = {
            date(2026, 3, 2): 10.3,
            date(2026, 3, 3): 10.9,   # +9% 觸發停利 (8%)
            date(2026, 3, 4): 11.5,
        }
        result = StrategyMinerService._evaluate_pick_concluded(pick, prices)
        assert result is not None
        assert result['exit_reason'] == 'take_profit'
        assert result['exit_date'] == date(2026, 3, 3)
        assert result['exit_price'] == 10.9
        assert abs(result['return_pct'] - 9.0) < 0.01  # (10.9-10.0)/10.0*100

    def test_stop_loss_hit(self):
        pick = _mk_pick(entry_price=10.0, sl=0.05)
        prices = {
            date(2026, 3, 2): 9.8,
            date(2026, 3, 3): 9.4,    # -6% 觸發停損 (5%)
        }
        result = StrategyMinerService._evaluate_pick_concluded(pick, prices)
        assert result is not None
        assert result['exit_reason'] == 'stop_loss'
        assert result['exit_date'] == date(2026, 3, 3)
        assert abs(result['return_pct'] - (-6.0)) < 0.01

    def test_time_limit_reached(self):
        """持有到 hold_days_max 未觸發 tp/sl, 用當日收盤結算."""
        pick = _mk_pick(entry_price=10.0, tp=0.20, sl=0.10, hd=3)
        prices = {
            date(2026, 3, 2): 10.2,
            date(2026, 3, 3): 10.5,
            date(2026, 3, 4): 10.3,
        }
        result = StrategyMinerService._evaluate_pick_concluded(pick, prices)
        assert result is not None
        assert result['exit_reason'] == 'time_limit'
        assert result['exit_date'] == date(2026, 3, 4)
        assert abs(result['return_pct'] - 3.0) < 0.01

    def test_still_holding_returns_none(self):
        """尚未到 hold_days_max 且未觸發條件 -> None."""
        pick = _mk_pick(entry_price=10.0, tp=0.20, sl=0.10, hd=5)
        prices = {
            date(2026, 3, 2): 10.2,
            date(2026, 3, 3): 10.5,
        }
        result = StrategyMinerService._evaluate_pick_concluded(pick, prices)
        assert result is None

    def test_short_take_profit(self):
        """放空: 股價下跌至 entry x (1-tp) 觸發停利."""
        pick = _mk_pick(entry_price=10.0, tp=0.08, direction='short')
        prices = {
            date(2026, 3, 2): 9.8,
            date(2026, 3, 3): 9.1,   # -9% 放空獲利 9%
        }
        result = StrategyMinerService._evaluate_pick_concluded(pick, prices)
        assert result is not None
        assert result['exit_reason'] == 'take_profit'
        assert abs(result['return_pct'] - 9.0) < 0.01

    def test_short_stop_loss(self):
        pick = _mk_pick(entry_price=10.0, sl=0.05, direction='short')
        prices = {date(2026, 3, 2): 10.6}  # +6% 放空虧損 6%
        result = StrategyMinerService._evaluate_pick_concluded(pick, prices)
        assert result is not None
        assert result['exit_reason'] == 'stop_loss'
        assert abs(result['return_pct'] - (-6.0)) < 0.01

    def test_no_price_data_returns_none(self):
        pick = _mk_pick(entry_price=10.0)
        result = StrategyMinerService._evaluate_pick_concluded(pick, {})
        assert result is None

    def test_includes_round_trip_cost(self):
        """扣 0.6% 來回成本."""
        pick = _mk_pick(entry_price=10.0, tp=0.08)
        prices = {date(2026, 3, 2): 10.8}  # +8% 前, 扣 0.6% 實際 +7.4%
        result = StrategyMinerService._evaluate_pick_concluded(
            pick, prices, round_trip_cost=0.006,
        )
        assert abs(result['return_pct'] - 7.4) < 0.01

"""
測試真實推薦歷史 helpers: _evaluate_pick_concluded, _load_stock_perf_from_picks
"""
from __future__ import annotations
from datetime import date, timedelta
import pytest
from unittest.mock import MagicMock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.services.strategy_miner_service import StrategyMinerService
from app.models.strategy_miner_pick import StrategyMinerPick
from app.models.stock_price import StockPrice


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


@pytest.fixture
def mem_db():
    """in-memory SQLite 測試 DB, 建立相關 tables."""
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine, tables=[
        StrategyMinerPick.__table__,
        StockPrice.__table__,
    ])
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()


def _add_price(db, stock_id, d, close):
    db.add(StockPrice(stock_id=stock_id, date=d, open=close, high=close, low=close, close=close, volume=1000))


class TestLoadStockPerfFromPicks:
    def test_single_concluded_win(self, mem_db):
        """1 筆已結案停利 -> win_rate=100%, trade_count=1."""
        db = mem_db
        pick = _mk_pick(stock_id='3710', pick_date=date(2026, 3, 1),
                        entry_price=10.0, tp=0.08, sl=0.05, hd=5)
        db.add(pick)
        _add_price(db, '3710', date(2026, 3, 2), 10.2)
        _add_price(db, '3710', date(2026, 3, 3), 10.9)
        db.commit()

        from app.services.strategy_miner_service import _load_stock_perf_from_picks
        result = _load_stock_perf_from_picks(db, ['3710'], direction='long')
        assert '3710' in result
        assert result['3710']['stock_win_rate'] == 1.0
        assert result['3710']['stock_trade_count'] == 1
        assert result['3710']['stock_avg_return'] > 8.0

    def test_still_holding_excluded(self, mem_db):
        """持有中不計入."""
        db = mem_db
        pick = _mk_pick(stock_id='3710', pick_date=date(2026, 4, 17),
                        entry_price=6.84, hd=20)
        db.add(pick)
        db.commit()

        from app.services.strategy_miner_service import _load_stock_perf_from_picks
        result = _load_stock_perf_from_picks(db, ['3710'], direction='long')
        assert '3710' not in result

    def test_empty_stock_returns_empty(self, mem_db):
        from app.services.strategy_miner_service import _load_stock_perf_from_picks
        result = _load_stock_perf_from_picks(mem_db, [], direction='long')
        assert result == {}

    def test_mixed_win_loss(self, mem_db):
        """2 勝 1 敗 -> win_rate=66.67%."""
        db = mem_db
        p1 = _mk_pick(stock_id='2330', pick_date=date(2026, 1, 1),
                      entry_price=100.0, tp=0.08, sl=0.05, hd=5)
        p2 = _mk_pick(stock_id='2330', pick_date=date(2026, 2, 1),
                      entry_price=100.0, tp=0.08, sl=0.05, hd=5)
        p3 = _mk_pick(stock_id='2330', pick_date=date(2026, 3, 1),
                      entry_price=100.0, tp=0.08, sl=0.05, hd=5)
        db.add_all([p1, p2, p3])
        _add_price(db, '2330', date(2026, 1, 2), 108.5)
        _add_price(db, '2330', date(2026, 2, 2), 94.0)
        _add_price(db, '2330', date(2026, 3, 2), 109.0)
        db.commit()

        from app.services.strategy_miner_service import _load_stock_perf_from_picks
        result = _load_stock_perf_from_picks(db, ['2330'], direction='long')
        assert result['2330']['stock_trade_count'] == 3
        assert abs(result['2330']['stock_win_rate'] - 2/3) < 0.01

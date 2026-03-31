"""回測引擎核心邏輯測試：交易成本常數 + open 缺失跳過"""
import pytest
import inspect
from app.services.strategy_miner_service import ROUND_TRIP_COST, StrategyMinerService


class TestTransactionCostConstant:
    def test_round_trip_cost_exists(self):
        """ROUND_TRIP_COST 應約為 0.006"""
        assert 0.005 <= ROUND_TRIP_COST <= 0.007


class TestOpenFallbackLogic:
    def test_open_fallback_is_continue_not_close(self):
        """原始碼中 open fallback 應已改為 continue"""
        source = inspect.getsource(StrategyMinerService._simulate_entries)
        assert "px.get(next_date" not in source, "open fallback 應改為 continue，不應 fallback 到 close"

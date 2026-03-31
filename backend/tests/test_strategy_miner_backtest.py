"""回測引擎核心邏輯測試：交易成本常數 + open 缺失跳過 + ATR 動態停損停利"""
import pytest
import inspect
import numpy as np
import pandas as pd
from datetime import date, timedelta
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


class TestTransactionCostIntegration:
    def test_return_deducts_cost(self):
        stock_id = "2330"
        base_date = date(2025, 1, 2)
        dates = [base_date + timedelta(days=i) for i in range(5)]

        price_dict = {stock_id: {d: p for d, p in zip(dates, [100, 105, 110, 108, 112])}}
        sorted_dates_dict = {stock_id: dates}
        open_dict = {stock_id: {d: p for d, p in zip(dates, [100, 104, 109, 107, 111])}}
        atr_dict = {stock_id: {dates[0]: 10.0}}

        signals_df = pd.DataFrame([{
            "signal_date": dates[0], "stock_id": stock_id, "stock_name": "台積電",
        }])
        params_list = [{"tp_atr_mult": 99, "sl_atr_mult": 99, "hold_days": 3}]

        results = StrategyMinerService._simulate_entries(
            signals_df, price_dict, sorted_dates_dict,
            params_list, is_short=False, open_dict=open_dict, atr_dict=atr_dict,
        )

        assert len(results[0]) == 1
        trade = results[0][0]
        raw = (108 - 104) / 104
        expected_net = raw - ROUND_TRIP_COST
        assert abs(trade["return_pct"] - expected_net * 100) < 0.01

    def test_skip_when_open_missing(self):
        stock_id = "2330"
        base_date = date(2025, 1, 2)
        dates = [base_date + timedelta(days=i) for i in range(5)]

        price_dict = {stock_id: {d: p for d, p in zip(dates, [100, 105, 110, 108, 112])}}
        sorted_dates_dict = {stock_id: dates}
        open_dict = {stock_id: {dates[0]: 100, dates[2]: 109, dates[3]: 107, dates[4]: 111}}
        atr_dict = {stock_id: {dates[0]: 10.0}}

        signals_df = pd.DataFrame([{
            "signal_date": dates[0], "stock_id": stock_id, "stock_name": "台積電",
        }])
        params_list = [{"tp_atr_mult": 99, "sl_atr_mult": 99, "hold_days": 3}]

        results = StrategyMinerService._simulate_entries(
            signals_df, price_dict, sorted_dates_dict,
            params_list, is_short=False, open_dict=open_dict, atr_dict=atr_dict,
        )
        assert len(results[0]) == 0

    def test_skip_when_atr_missing(self):
        stock_id = "2330"
        base_date = date(2025, 1, 2)
        dates = [base_date + timedelta(days=i) for i in range(5)]

        price_dict = {stock_id: {d: p for d, p in zip(dates, [100, 105, 110, 108, 112])}}
        sorted_dates_dict = {stock_id: dates}
        open_dict = {stock_id: {d: p for d, p in zip(dates, [100, 104, 109, 107, 111])}}
        atr_dict = {}  # no ATR data

        signals_df = pd.DataFrame([{
            "signal_date": dates[0], "stock_id": stock_id, "stock_name": "台積電",
        }])
        params_list = [{"tp_atr_mult": 2.0, "sl_atr_mult": 1.0, "hold_days": 3}]

        results = StrategyMinerService._simulate_entries(
            signals_df, price_dict, sorted_dates_dict,
            params_list, is_short=False, open_dict=open_dict, atr_dict=atr_dict,
        )
        assert len(results[0]) == 0  # should skip when ATR missing

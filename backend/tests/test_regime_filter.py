"""市場狀態 Regime Filter 測試"""
import pytest
from app.services.strategy_miner_service import MAX_PICKS_PER_DIRECTION, TRIGGER_COUNT_PERCENTILE


def _compute_regime_params(breadth: float, direction: str) -> tuple:
    """模擬 regime filter 邏輯，回傳 (max_picks, trigger_pct)"""
    if direction == 'long':
        if breadth < 0.30:
            return 2, 0.85
        elif breadth < 0.45:
            return 3, 0.80
        else:
            return MAX_PICKS_PER_DIRECTION, TRIGGER_COUNT_PERCENTILE
    else:  # short
        if breadth > 0.70:
            return 2, 0.85
        elif breadth > 0.55:
            return 3, 0.80
        else:
            return MAX_PICKS_PER_DIRECTION, TRIGGER_COUNT_PERCENTILE


class TestRegimeFilter:
    def test_long_weak_market_reduces_picks(self):
        max_picks, trigger_pct = _compute_regime_params(0.25, 'long')
        assert max_picks == 2
        assert trigger_pct == 0.85

    def test_long_normal_market_full_picks(self):
        max_picks, trigger_pct = _compute_regime_params(0.60, 'long')
        assert max_picks == 5
        assert trigger_pct == 0.70

    def test_long_moderate_weak_market(self):
        max_picks, trigger_pct = _compute_regime_params(0.40, 'long')
        assert max_picks == 3
        assert trigger_pct == 0.80

    def test_short_strong_market_reduces_picks(self):
        max_picks, trigger_pct = _compute_regime_params(0.75, 'short')
        assert max_picks == 2
        assert trigger_pct == 0.85

    def test_short_weak_market_full_picks(self):
        max_picks, trigger_pct = _compute_regime_params(0.35, 'short')
        assert max_picks == 5
        assert trigger_pct == 0.70

    def test_short_moderate_strong_market(self):
        max_picks, trigger_pct = _compute_regime_params(0.60, 'short')
        assert max_picks == 3
        assert trigger_pct == 0.80

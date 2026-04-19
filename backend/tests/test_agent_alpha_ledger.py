from __future__ import annotations
from datetime import date, timedelta
from unittest.mock import MagicMock, patch
import pytest
from app.agent.alpha_ledger import LedgerEntry, summarise


def _fake_response(items):
    m = MagicMock()
    m.status_code = 200
    m.raise_for_status.return_value = None
    m.json.return_value = {"items": items, "total": len(items)}
    return m


def test_summarise_with_closed_picks():
    today = date.today()
    fake_items = [
        {"pick_date": today.isoformat(), "time_dimension": "5d",
         "direction": "long", "return_pct": 3.0, "exit_reason": "take_profit"},
        {"pick_date": today.isoformat(), "time_dimension": "5d",
         "direction": "long", "return_pct": -2.0, "exit_reason": "stop_loss"},
        {"pick_date": today.isoformat(), "time_dimension": "5d",
         "direction": "long", "return_pct": 1.0, "exit_reason": "time_limit"},
        {"pick_date": today.isoformat(), "time_dimension": "10d",
         "direction": "long", "return_pct": 5.0, "exit_reason": "take_profit"},
        {"pick_date": today.isoformat(), "time_dimension": "20d",
         "direction": "long", "return_pct": 8.0, "exit_reason": "take_profit"},
    ]
    with patch("app.agent.alpha_ledger.httpx.get",
               return_value=_fake_response(fake_items)):
        result = summarise(days=7)
    assert isinstance(result, dict)
    assert result["5d"].n == 3
    assert result["5d"].wr == pytest.approx(2/3, abs=0.01)
    assert result["5d"].avg_return == pytest.approx((3.0 - 2.0 + 1.0) / 3, abs=0.01)
    assert result["10d"].n == 1
    assert result["20d"].n == 1


def test_summarise_filters_by_cutoff():
    today = date.today()
    old = (today - timedelta(days=30)).isoformat()
    recent = today.isoformat()
    fake_items = [
        {"pick_date": old, "time_dimension": "5d",
         "direction": "long", "return_pct": 100.0, "exit_reason": "take_profit"},
        {"pick_date": recent, "time_dimension": "5d",
         "direction": "long", "return_pct": 1.0, "exit_reason": "take_profit"},
    ]
    with patch("app.agent.alpha_ledger.httpx.get",
               return_value=_fake_response(fake_items)):
        result = summarise(days=7)
    # old pick 超過 7 天 cutoff 應被濾掉
    assert result["5d"].n == 1
    assert result["5d"].avg_return == pytest.approx(1.0, abs=0.01)


def test_summarise_empty_returns_empty_dict():
    with patch("app.agent.alpha_ledger.httpx.get",
               return_value=_fake_response([])):
        result = summarise(days=7)
    assert result == {}

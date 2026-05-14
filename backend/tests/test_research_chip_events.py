import pandas as pd
import pytest

from scripts.research_chip_events import find_consecutive_buy_events


def test_find_consecutive_buy_events_basic():
    """連續 3 日外資淨買 → 1 個 event。"""
    df = pd.DataFrame([
        {"stock_id": "2330", "date": "2026-05-01", "foreign_net_buy": 100},
        {"stock_id": "2330", "date": "2026-05-02", "foreign_net_buy": 200},
        {"stock_id": "2330", "date": "2026-05-03", "foreign_net_buy": 150},
        {"stock_id": "2330", "date": "2026-05-04", "foreign_net_buy": -50},
        {"stock_id": "2330", "date": "2026-05-05", "foreign_net_buy": 80},
    ])
    events = find_consecutive_buy_events(df, factor_col="foreign_net_buy", min_days=3)
    assert len(events) == 1
    e = events.iloc[0]
    assert e["stock_id"] == "2330"
    assert str(e["event_date"]) == "2026-05-03"
    assert e["consecutive_days"] == 3
    assert e["cumulative_net_buy"] == 450


def test_find_consecutive_buy_events_min_days_filter():
    df = pd.DataFrame([
        {"stock_id": "2330", "date": "2026-05-01", "foreign_net_buy": 100},
        {"stock_id": "2330", "date": "2026-05-02", "foreign_net_buy": 200},
        {"stock_id": "2330", "date": "2026-05-03", "foreign_net_buy": -50},
    ])
    events = find_consecutive_buy_events(df, factor_col="foreign_net_buy", min_days=3)
    assert len(events) == 0


def test_find_consecutive_buy_events_multi_stock():
    df = pd.DataFrame([
        {"stock_id": "2330", "date": "2026-05-01", "foreign_net_buy": 100},
        {"stock_id": "2330", "date": "2026-05-02", "foreign_net_buy": 200},
        {"stock_id": "2330", "date": "2026-05-03", "foreign_net_buy": 50},
        {"stock_id": "2454", "date": "2026-05-01", "foreign_net_buy": 80},
        {"stock_id": "2454", "date": "2026-05-02", "foreign_net_buy": 90},
        {"stock_id": "2454", "date": "2026-05-03", "foreign_net_buy": 110},
    ])
    events = find_consecutive_buy_events(df, factor_col="foreign_net_buy", min_days=3)
    assert len(events) == 2
    assert set(events["stock_id"].tolist()) == {"2330", "2454"}

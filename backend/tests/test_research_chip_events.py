import pandas as pd
import pytest

from scripts.research_chip_events import (
    find_consecutive_buy_events,
    event_post_returns,
)


def test_find_consecutive_buy_events_basic():
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


# ── event_post_returns ───────────────────────────────────────


def test_event_post_returns_5d():
    """event 後 5 個交易日報酬計算 (使用 trading day index)。"""
    prices = pd.DataFrame([
        {"stock_id": "2330", "date": "2026-05-01", "close": 100.0},
        {"stock_id": "2330", "date": "2026-05-02", "close": 102.0},
        {"stock_id": "2330", "date": "2026-05-03", "close": 105.0},
        {"stock_id": "2330", "date": "2026-05-04", "close": 103.0},
        {"stock_id": "2330", "date": "2026-05-05", "close": 108.0},
        {"stock_id": "2330", "date": "2026-05-06", "close": 110.0},
    ])
    events = pd.DataFrame([
        {"stock_id": "2330", "event_date": pd.to_datetime("2026-05-01").date(),
         "consecutive_days": 3, "cumulative_net_buy": 500},
    ])
    out = event_post_returns(events, prices, horizons=[5])
    row = out.iloc[0]
    # event_date=5/1 (close=100), event+5 trading days = 5/6 (close=110) → +10%
    assert row["ret_5d"] == pytest.approx(10.0, abs=0.1)


def test_event_post_returns_skips_when_horizon_overflows():
    prices = pd.DataFrame([
        {"stock_id": "2330", "date": "2026-05-01", "close": 100.0},
        {"stock_id": "2330", "date": "2026-05-02", "close": 102.0},
    ])
    events = pd.DataFrame([
        {"stock_id": "2330", "event_date": pd.to_datetime("2026-05-01").date(),
         "consecutive_days": 3, "cumulative_net_buy": 500},
    ])
    out = event_post_returns(events, prices, horizons=[5])
    row = out.iloc[0]
    assert pd.isna(row["ret_5d"])

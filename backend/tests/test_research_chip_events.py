import pandas as pd
import pytest

from scripts.research_chip_events import (
    find_consecutive_buy_events,
    event_post_returns,
    walk_forward_summary,
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


def test_event_post_returns_5d():
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


# ── walk_forward_summary ─────────────────────────────────────


def test_walk_forward_summary_aggregates_by_quarter():
    events_with_ret = pd.DataFrame([
        {"event_date": pd.to_datetime("2026-01-15").date(), "ret_5d": 1.5, "ret_10d": 3.0},
        {"event_date": pd.to_datetime("2026-02-15").date(), "ret_5d": -0.5, "ret_10d": 1.0},
        {"event_date": pd.to_datetime("2026-03-15").date(), "ret_5d": 2.0, "ret_10d": 4.0},
        {"event_date": pd.to_datetime("2026-04-15").date(), "ret_5d": 0.0, "ret_10d": -1.0},
        {"event_date": pd.to_datetime("2026-05-15").date(), "ret_5d": 3.0, "ret_10d": 5.0},
    ])
    out = walk_forward_summary(events_with_ret, horizons=[5, 10])
    assert set(out["quarter"].tolist()) == {"2026Q1", "2026Q2"}
    q1 = out[out["quarter"] == "2026Q1"].iloc[0]
    assert q1["n"] == 3
    assert q1["wr_5d"] == pytest.approx(66.67, abs=0.5)
    assert q1["avg_5d"] == pytest.approx(1.0, abs=0.01)

import numpy as np
import pandas as pd
import pytest

from scripts.research_factor_ablation import (
    FACTOR_COLUMNS,
    _join_picks_features,
    per_factor_ic,
    quality_gate_impact,
    universe_slice_alpha,
)


def test_factor_columns_list_includes_chip():
    """FACTOR_COLUMNS 必須涵蓋技術 / 基本面 / 籌碼 / 市場 / 波動 / 背離 全部。"""
    assert "rsi14" in FACTOR_COLUMNS
    assert "ma_trend" in FACTOR_COLUMNS
    assert "roe" in FACTOR_COLUMNS
    assert "rev_surprise" in FACTOR_COLUMNS
    assert "foreign_buy_5d" in FACTOR_COLUMNS
    assert "trust_buy_10d" in FACTOR_COLUMNS
    assert "dealer_buy_20d" in FACTOR_COLUMNS
    assert "margin_chg_5d" in FACTOR_COLUMNS
    assert "short_chg_5d" in FACTOR_COLUMNS
    assert "log_amihud_20d" in FACTOR_COLUMNS
    assert "atr_pct" in FACTOR_COLUMNS
    assert "divergence_avg" in FACTOR_COLUMNS


def test_join_picks_features_matches_by_sid_date():
    picks = pd.DataFrame([
        {"stock_id": "2330", "pick_date": "2026-05-01", "return_pct": 5.0, "time_dimension": "5d"},
        {"stock_id": "2454", "pick_date": "2026-05-02", "return_pct": -2.0, "time_dimension": "10d"},
    ])
    features = pd.DataFrame([
        {"stock_id": "2330", "date": "2026-05-01", "rsi14": 60.0, "foreign_buy_5d": 1000.0},
        {"stock_id": "2454", "date": "2026-05-02", "rsi14": 30.0, "foreign_buy_5d": -500.0},
        {"stock_id": "9999", "date": "2026-05-01", "rsi14": 50.0, "foreign_buy_5d": 0.0},
    ])
    out = _join_picks_features(picks, features)
    assert len(out) == 2
    assert "rsi14" in out.columns
    assert "return_pct" in out.columns
    row_2330 = out[out["stock_id"] == "2330"].iloc[0]
    assert row_2330["rsi14"] == 60.0
    assert row_2330["return_pct"] == 5.0


# ── per_factor_ic ────────────────────────────────────────────


def test_per_factor_ic_strong_positive_signal():
    n = 100
    rng = np.random.default_rng(42)
    factor = rng.uniform(0, 100, n)
    ret = factor / 100.0 * 10 - 5 + rng.normal(0, 0.5, n)
    df = pd.DataFrame({"factor_x": factor, "return_pct": ret})
    out = per_factor_ic(df, ["factor_x"])
    row = out[out["factor"] == "factor_x"].iloc[0]
    assert row["ic"] > 0.8
    assert row["spread_pp"] > 5.0
    assert row["n"] == n


def test_per_factor_ic_no_signal():
    n = 200
    rng = np.random.default_rng(7)
    factor = rng.uniform(0, 100, n)
    ret = rng.normal(0, 5, n)
    df = pd.DataFrame({"factor_x": factor, "return_pct": ret})
    out = per_factor_ic(df, ["factor_x"])
    row = out[out["factor"] == "factor_x"].iloc[0]
    assert abs(row["ic"]) < 0.2


def test_per_factor_ic_skips_all_null_factor():
    df = pd.DataFrame({"factor_x": [None]*10, "return_pct": [1.0]*10})
    out = per_factor_ic(df, ["factor_x"])
    row = out[out["factor"] == "factor_x"].iloc[0]
    assert row["n"] == 0
    assert pd.isna(row["ic"])


# ── quality_gate_impact ──────────────────────────────────────


def test_quality_gate_impact_separates_pass_fail():
    df = pd.DataFrame([
        {"quality_gate_passed": True, "return_pct": 5.0},
        {"quality_gate_passed": True, "return_pct": 3.0},
        {"quality_gate_passed": True, "return_pct": -1.0},
        {"quality_gate_passed": False, "return_pct": -3.0},
        {"quality_gate_passed": False, "return_pct": -2.0},
    ])
    out = quality_gate_impact(df)
    assert out["passed"]["n"] == 3
    assert out["passed"]["wr"] == pytest.approx(66.67, abs=0.5)
    assert out["failed"]["n"] == 2
    assert out["failed"]["wr"] == 0.0


def test_universe_slice_alpha_by_dimension():
    df = pd.DataFrame([
        {"time_dimension": "5d", "return_pct": 2.0},
        {"time_dimension": "5d", "return_pct": -1.0},
        {"time_dimension": "5d", "return_pct": 3.0},
        {"time_dimension": "10d", "return_pct": -2.0},
        {"time_dimension": "10d", "return_pct": -1.0},
    ])
    out = universe_slice_alpha(df, by="time_dimension")
    out_dict = {row["slice"]: row for _, row in out.iterrows()}
    assert out_dict["5d"]["n"] == 3
    assert out_dict["5d"]["wr"] == pytest.approx(66.67, abs=0.5)
    assert out_dict["10d"]["n"] == 2
    assert out_dict["10d"]["wr"] == 0.0

"""Phase 1: 對結案 picks 跑全因子 ablation 診斷。

職責: 從 NAS Postgres pull stock_picks (concluded) + 對應 stock_features,
跑 per-factor IC + quality gate impact + universe slice, 輸出 markdown report。

純 read-only, 不改 schema 不改 production。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd
from scipy import stats

FACTOR_COLUMNS = [
    # 技術 (價格 / MA / bias / RSI / KD / MACD / 布林)
    "change_pct",
    "ma5", "ma10", "ma20", "ma60",
    "bias5", "bias10", "bias20",
    "rsi14", "rsi2",
    "k", "d",
    "macd_dif", "macd_dea", "macd_osc",
    "bb_pctb",
    "vol_ratio",
    "price_vs_high20", "ma_trend",
    "atr20", "atr_pct", "ivol_20d",
    "log_amihud_20d",
    "divergence_avg",
    # 基本面
    "yield_rate", "roe", "pb_ratio", "revenue_yoy",
    "rev_surprise", "rev_accel",
    # 籌碼
    "foreign_net_buy", "foreign_buy_5d", "foreign_buy_10d", "foreign_buy_20d",
    "trust_net_buy", "trust_buy_5d", "trust_buy_10d", "trust_buy_20d",
    "dealer_net_buy", "dealer_buy_5d", "dealer_buy_10d", "dealer_buy_20d",
    "margin_chg_5d", "short_chg_5d",
    "foreign_hold_pct", "foreign_hold_chg_5d",
    "sector_rs",
    # 市場
    "market_pcr", "etf_net_flow_5d", "market_breadth", "market_trend",
]


def _join_picks_features(picks: pd.DataFrame, features: pd.DataFrame) -> pd.DataFrame:
    """join stock_picks (用 pick_date) + stock_features (用 date) by (stock_id, date)。"""
    picks = picks.copy()
    features = features.copy()
    picks["_d"] = pd.to_datetime(picks["pick_date"]).dt.date.astype(str)
    features["_d"] = pd.to_datetime(features["date"]).dt.date.astype(str)
    merged = picks.merge(
        features.drop(columns=["date"]),
        left_on=["stock_id", "_d"],
        right_on=["stock_id", "_d"],
        how="inner",
        suffixes=("", "_feat"),
    )
    return merged.drop(columns=["_d"])


def per_factor_ic(df: pd.DataFrame, factors: list[str]) -> pd.DataFrame:
    """每個因子算 IC + p_value + top/bot quintile wr/avg + spread_pp + n。"""
    rows = []
    for factor in factors:
        if factor not in df.columns:
            rows.append({
                "factor": factor, "n": 0, "ic": float("nan"), "p_value": float("nan"),
                "top_q_wr": float("nan"), "bot_q_wr": float("nan"),
                "top_q_avg": float("nan"), "bot_q_avg": float("nan"), "spread_pp": float("nan"),
            })
            continue
        sub = df[[factor, "return_pct"]].dropna()
        n = len(sub)
        if n < 10:
            rows.append({
                "factor": factor, "n": n, "ic": float("nan"), "p_value": float("nan"),
                "top_q_wr": float("nan"), "bot_q_wr": float("nan"),
                "top_q_avg": float("nan"), "bot_q_avg": float("nan"), "spread_pp": float("nan"),
            })
            continue
        ic, p_value = stats.spearmanr(sub[factor], sub["return_pct"])
        try:
            sub = sub.copy()
            sub["_q"] = pd.qcut(sub[factor], 5, labels=False, duplicates="drop")
        except ValueError:
            sub["_q"] = pd.NA
        top = sub[sub["_q"] == 4]
        bot = sub[sub["_q"] == 0]
        top_q_wr = (top["return_pct"] > 0).mean() * 100 if len(top) else float("nan")
        bot_q_wr = (bot["return_pct"] > 0).mean() * 100 if len(bot) else float("nan")
        top_q_avg = top["return_pct"].mean() if len(top) else float("nan")
        bot_q_avg = bot["return_pct"].mean() if len(bot) else float("nan")
        spread_pp = top_q_wr - bot_q_wr if not (pd.isna(top_q_wr) or pd.isna(bot_q_wr)) else float("nan")
        rows.append({
            "factor": factor, "n": n,
            "ic": float(ic) if not pd.isna(ic) else float("nan"),
            "p_value": float(p_value) if not pd.isna(p_value) else float("nan"),
            "top_q_wr": top_q_wr, "bot_q_wr": bot_q_wr,
            "top_q_avg": top_q_avg, "bot_q_avg": bot_q_avg,
            "spread_pp": spread_pp,
        })
    return pd.DataFrame(rows).sort_values("ic", ascending=False, na_position="last")


def quality_gate_impact(df: pd.DataFrame, gate_col: str = "quality_gate_passed") -> dict:
    """有/沒 pass quality gate 兩組對比。
    回 {"passed": {n, wr, avg}, "failed": {n, wr, avg}}。
    若 gate_col 不在 df 內, 整體當 "passed" group。
    """
    if gate_col not in df.columns:
        sub = df.dropna(subset=["return_pct"])
        n = len(sub)
        return {
            "passed": {"n": n,
                       "wr": (sub["return_pct"] > 0).mean() * 100 if n else float("nan"),
                       "avg": sub["return_pct"].mean() if n else float("nan")},
            "failed": {"n": 0, "wr": float("nan"), "avg": float("nan")},
        }
    result = {}
    for label, val in [("passed", True), ("failed", False)]:
        sub = df[df[gate_col] == val].dropna(subset=["return_pct"])
        n = len(sub)
        result[label] = {
            "n": n,
            "wr": (sub["return_pct"] > 0).mean() * 100 if n else float("nan"),
            "avg": sub["return_pct"].mean() if n else float("nan"),
        }
    return result


def universe_slice_alpha(df: pd.DataFrame, by: str) -> pd.DataFrame:
    """按 by 欄位切片, 每組算 n / wr / avg。
    常用 by: time_dimension / direction / 自訂 market_cap_bucket 等。
    """
    if by not in df.columns:
        return pd.DataFrame([{"slice": "__all__", "n": len(df),
                              "wr": (df["return_pct"] > 0).mean() * 100 if len(df) else float("nan"),
                              "avg": df["return_pct"].mean() if len(df) else float("nan")}])
    rows = []
    for slice_val, sub in df.groupby(by):
        sub = sub.dropna(subset=["return_pct"])
        n = len(sub)
        rows.append({
            "slice": str(slice_val),
            "n": n,
            "wr": (sub["return_pct"] > 0).mean() * 100 if n else float("nan"),
            "avg": sub["return_pct"].mean() if n else float("nan"),
        })
    return pd.DataFrame(rows).sort_values("n", ascending=False)

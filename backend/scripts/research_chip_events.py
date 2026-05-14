"""Phase 2: 籌碼連續淨買 event 偵測 + 事件後報酬分析。

純 read-only, 用既有 stock_chip_data (NAS 93 萬筆) + stock_prices 跑分析。
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd
import numpy as np

TAIPEI_TZ = timezone(timedelta(hours=8))


def find_consecutive_buy_events(df: pd.DataFrame, factor_col: str, min_days: int = 3) -> pd.DataFrame:
    """對每個 stock 找 factor_col > 0 連續 ≥ min_days 的 event。"""
    df = df.copy().sort_values(["stock_id", "date"]).reset_index(drop=True)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["_positive"] = df[factor_col] > 0
    df["_streak_group"] = (df["_positive"] != df.groupby("stock_id")["_positive"].shift()).cumsum()
    streaks = (
        df[df["_positive"]]
        .groupby(["stock_id", "_streak_group"])
        .agg(
            event_date=("date", "last"),
            consecutive_days=(factor_col, "size"),
            cumulative_net_buy=(factor_col, "sum"),
        )
        .reset_index()
        .drop(columns=["_streak_group"])
    )
    return streaks[streaks["consecutive_days"] >= min_days].reset_index(drop=True)


def event_post_returns(
    events: pd.DataFrame,
    prices: pd.DataFrame,
    horizons: list[int] = [5, 10, 20],
) -> pd.DataFrame:
    """對每個 event 算 horizon 個**交易日**後的累積報酬 (%)。

    使用 trading day index (依 prices 表內每股的實際 trading days), 不算 calendar days。
    若 horizon 超過該股可用 trading day, 該 horizon ret = NaN。
    """
    prices = prices.copy().sort_values(["stock_id", "date"]).reset_index(drop=True)
    prices["date"] = pd.to_datetime(prices["date"]).dt.date
    prices["_td_idx"] = prices.groupby("stock_id").cumcount()
    p_lookup = prices.set_index(["stock_id", "date"])
    p_by_idx = prices.set_index(["stock_id", "_td_idx"])

    out = events.copy()
    for h in horizons:
        out[f"ret_{h}d"] = float("nan")
    for i, e in out.iterrows():
        sid = e["stock_id"]
        edate = e["event_date"]
        try:
            base_idx = int(p_lookup.loc[(sid, edate), "_td_idx"])
        except KeyError:
            continue
        try:
            base_close = float(p_lookup.loc[(sid, edate), "close"])
        except KeyError:
            continue
        for h in horizons:
            try:
                future_close = float(p_by_idx.loc[(sid, base_idx + h), "close"])
                out.at[i, f"ret_{h}d"] = (future_close / base_close - 1) * 100
            except KeyError:
                pass
    return out

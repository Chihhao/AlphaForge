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
    """對每個 stock 找 factor_col > 0 連續 ≥ min_days 的 event。

    Event 定義: 連續 N 日同正後**第 N 日**該日為 event date (即連續 streak 的最後一天)。
    """
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

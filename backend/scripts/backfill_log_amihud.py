"""Backfill log_amihud_20d into stock_features (Phase 11 factor).

This script only updates the ``log_amihud_20d`` column for every row in
``stock_features``; it does not touch any other column. It loads the full
``stock_prices`` history, computes the factor vectorised, then issues batched
UPDATE statements.

Usage:
    cd backend
    ./.venv/bin/python scripts/backfill_log_amihud.py [--start-date 2023-01-01]
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text

sys.path.insert(0, os.getcwd())

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

PG_URL = os.environ.get(
    "PG_URL",
    "postgresql://alphaforge:alphaforge_secret@10.0.4.3:5433/alphaforge",
)

WARMUP_DAYS = 60  # 保證 rolling 20 的 min_periods=15 有足夠資料


def load_prices(engine, start_date: date, end_date: date) -> pd.DataFrame:
    """Load (stock_id, date, close, volume) for the warmup+target window."""
    warmup_start = start_date - timedelta(days=WARMUP_DAYS)
    log.info("Loading prices %s ~ %s (warmup %s)", start_date, end_date, warmup_start)
    query = text(
        "SELECT stock_id, date, close, volume FROM stock_prices "
        "WHERE date >= :start AND date <= :end AND close > 0"
    )
    df = pd.read_sql(
        query, engine, params={"start": warmup_start, "end": end_date}
    )
    df["date"] = pd.to_datetime(df["date"])
    log.info("  loaded %d rows, %d stocks", len(df), df["stock_id"].nunique())
    return df


def compute_log_amihud(df: pd.DataFrame) -> pd.DataFrame:
    """Compute log_amihud_20d vectorised across all stock-days."""
    log.info("Computing log_amihud_20d...")
    df = df.sort_values(["stock_id", "date"]).copy()
    df["ret"] = df.groupby("stock_id")["close"].pct_change()
    df["dollar_vol"] = df["close"] * df["volume"]
    df["abs_ret_over_dvol"] = (
        df["ret"].abs() / df["dollar_vol"].replace(0, np.nan)
    )
    df["amihud_20d"] = df.groupby("stock_id")["abs_ret_over_dvol"].transform(
        lambda x: x.rolling(20, min_periods=15).mean()
    )
    df["log_amihud_20d"] = np.log1p(df["amihud_20d"] * 1e8)
    cov = df["log_amihud_20d"].notna().mean()
    log.info("  coverage: %.1f%%", cov * 100)
    return df[["stock_id", "date", "log_amihud_20d"]]


def backfill_updates(
    engine, factor_df: pd.DataFrame, start_date: date, end_date: date
) -> int:
    """Bulk update log_amihud_20d via temp table + UPDATE FROM.

    Strategy:
        1. Create TEMP TABLE with (stock_id, date, log_amihud_20d)
        2. Bulk insert via pandas to_sql (COPY-backed)
        3. Single UPDATE FROM join to stock_features
        4. Drop temp table
    """
    mask = (factor_df["date"] >= pd.Timestamp(start_date)) & (
        factor_df["date"] <= pd.Timestamp(end_date)
    )
    target = factor_df[mask].dropna(subset=["log_amihud_20d"]).copy()
    target["date"] = target["date"].dt.date
    log.info("Writing %d updates via temp table...", len(target))

    if target.empty:
        return 0

    with engine.begin() as conn:
        log.info("  creating temp table...")
        conn.execute(
            text(
                "CREATE TEMP TABLE tmp_amihud ("
                "stock_id VARCHAR(10), "
                "date DATE, "
                "log_amihud_20d DOUBLE PRECISION"
                ") ON COMMIT DROP"
            )
        )
        log.info("  bulk loading %d rows into temp table...", len(target))
        target.to_sql(
            "tmp_amihud",
            conn,
            if_exists="append",
            index=False,
            method="multi",
            chunksize=10000,
        )
        log.info("  creating index on temp table...")
        conn.execute(
            text("CREATE INDEX ON tmp_amihud (stock_id, date)")
        )
        log.info("  executing UPDATE FROM...")
        result = conn.execute(
            text(
                "UPDATE stock_features sf "
                "SET log_amihud_20d = t.log_amihud_20d "
                "FROM tmp_amihud t "
                "WHERE sf.stock_id = t.stock_id AND sf.date = t.date"
            )
        )
        total_updated = result.rowcount
        log.info("  updated %d rows in stock_features", total_updated)

    return total_updated


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill log_amihud_20d column")
    parser.add_argument(
        "--start-date",
        type=str,
        default="2023-01-01",
        help="回補起始日期 (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end-date",
        type=str,
        default=None,
        help="回補結束日期 (YYYY-MM-DD)，預設 today",
    )
    args = parser.parse_args()

    start_d = date.fromisoformat(args.start_date)
    end_d = date.fromisoformat(args.end_date) if args.end_date else date.today()

    engine = create_engine(PG_URL)
    prices = load_prices(engine, start_d, end_d)
    factor = compute_log_amihud(prices)
    n = backfill_updates(engine, factor, start_d, end_d)
    log.info("✅ Backfill complete: %d rows", n)


if __name__ == "__main__":
    main()

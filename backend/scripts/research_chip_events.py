"""Phase 2: 籌碼連續淨買 event 偵測 + 事件後報酬分析。

純 read-only, 用既有 stock_chip_data (NAS 93 萬筆) + stock_prices 跑分析。

Usage (從 backend/ 目錄):
    ./.venv/bin/python -m scripts.research_chip_events
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd
import numpy as np
from sqlalchemy import create_engine, text


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
    """對每個 event 算 horizon 個交易日後的累積報酬 (%) — trading day index."""
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


def walk_forward_summary(events_with_ret: pd.DataFrame, horizons: list[int] = [5, 10, 20]) -> pd.DataFrame:
    """按 quarter 切 events, 算各 horizon 的 n / wr / avg。"""
    df = events_with_ret.copy()
    df["event_date"] = pd.to_datetime(df["event_date"])
    df["quarter"] = df["event_date"].dt.to_period("Q").astype(str)
    rows = []
    for q, sub in df.groupby("quarter"):
        row = {"quarter": q, "n": len(sub)}
        for h in horizons:
            col = f"ret_{h}d"
            valid = sub[col].dropna()
            row[f"wr_{h}d"] = (valid > 0).mean() * 100 if len(valid) else float("nan")
            row[f"avg_{h}d"] = valid.mean() if len(valid) else float("nan")
        rows.append(row)
    return pd.DataFrame(rows).sort_values("quarter")


# ── runtime helpers ──────────────────────────────────────────


def _load_db_url() -> str:
    env = Path(__file__).resolve().parents[1] / ".env"
    if not env.exists():
        raise RuntimeError(f"backend/.env not found at {env}")
    for line in env.read_text().splitlines():
        line = line.strip()
        if line.startswith("DATABASE_URL="):
            return line.split("=", 1)[1]
    raise RuntimeError("DATABASE_URL not in backend/.env")


def _fetch_chip_data(engine) -> pd.DataFrame:
    sql = text("""
        SELECT stock_id, date, foreign_net_buy, trust_net_buy, dealer_net_buy
        FROM stock_chip_data
        WHERE date >= CURRENT_DATE - INTERVAL '1 year'
    """)
    with engine.connect() as conn:
        return pd.read_sql(sql, conn)


def _fetch_prices(engine) -> pd.DataFrame:
    sql = text("""
        SELECT stock_id, date, close
        FROM stock_prices
        WHERE date >= CURRENT_DATE - INTERVAL '15 months'
    """)
    with engine.connect() as conn:
        return pd.read_sql(sql, conn)


def _fetch_taiex(engine) -> pd.DataFrame:
    """讀 TAIEX 大盤 close。"""
    sql = text("""
        SELECT date, close FROM stock_prices
        WHERE stock_id IN ('IX0001', 'TWII', 'TAIEX')
          AND date >= CURRENT_DATE - INTERVAL '15 months'
        ORDER BY date
    """)
    try:
        with engine.connect() as conn:
            return pd.read_sql(sql, conn)
    except Exception:
        return pd.DataFrame(columns=["date", "close"])


def _overall_stats(events_with_ret: pd.DataFrame, horizons: list[int]) -> dict:
    out = {}
    for h in horizons:
        col = f"ret_{h}d"
        valid = events_with_ret[col].dropna()
        out[f"wr_{h}d"] = (valid > 0).mean() * 100 if len(valid) else float("nan")
        out[f"avg_{h}d"] = valid.mean() if len(valid) else float("nan")
    return out


def _taiex_baseline(taiex: pd.DataFrame, horizons: list[int]) -> dict:
    """大盤 baseline: 對每個 day 算 day+H close / day close - 1, 取所有 day 平均。"""
    if taiex.empty:
        return {}
    taiex = taiex.copy().sort_values("date").reset_index(drop=True)
    taiex["date"] = pd.to_datetime(taiex["date"]).dt.date
    closes = taiex["close"].values
    out = {}
    for h in horizons:
        if len(closes) > h:
            rets = (closes[h:] / closes[:-h] - 1) * 100
            out[f"{h}d"] = float(np.mean(rets))
        else:
            out[f"{h}d"] = float("nan")
    return out


def _render_report(
    summary_foreign: pd.DataFrame,
    summary_trust: pd.DataFrame,
    overall_foreign: dict,
    overall_trust: dict,
    n_events_foreign: int,
    n_events_trust: int,
    taiex_baseline: dict,
) -> str:
    now = datetime.now(TAIPEI_TZ).strftime("%Y-%m-%d %H:%M")
    today = datetime.now(TAIPEI_TZ).strftime("%Y-%m-%d")
    lines = [
        "###### tags: `日報`,`AlphaForge`,`alpha 研究`,`chip-event-prototype`",
        "",
        "# Phase 2 — 籌碼連續淨買 Event Prototype Report",
        "",
        f"`文件版本: {today}a`",
        "",
        f"產生時間: {now} (Asia/Taipei)",
        "",
        f"## 事件樣本 (近 1 年, 連續淨買 ≥ 3 日)",
        f"- 外資 (foreign): {n_events_foreign} 事件",
        f"- 投信 (trust): {n_events_trust} 事件",
        "",
        "## 整體 (所有事件聚合)",
        "",
        "| 訊號源 | 5d wr | 5d avg | 10d wr | 10d avg | 20d wr | 20d avg |",
        "|---|---|---|---|---|---|---|",
    ]
    for label, ov in [("外資", overall_foreign), ("投信", overall_trust)]:
        lines.append(
            f"| {label} | {ov.get('wr_5d', float('nan')):.1f}% | {ov.get('avg_5d', float('nan')):+.2f}% | "
            f"{ov.get('wr_10d', float('nan')):.1f}% | {ov.get('avg_10d', float('nan')):+.2f}% | "
            f"{ov.get('wr_20d', float('nan')):.1f}% | {ov.get('avg_20d', float('nan')):+.2f}% |"
        )
    lines += ["", "## TAIEX baseline (同期大盤平均)", ""]
    if taiex_baseline:
        lines.append(
            f"- TAIEX 5d avg: {taiex_baseline.get('5d', float('nan')):+.2f}%, "
            f"10d avg: {taiex_baseline.get('10d', float('nan')):+.2f}%, "
            f"20d avg: {taiex_baseline.get('20d', float('nan')):+.2f}%"
        )
    else:
        lines.append("- (TAIEX 資料缺, baseline=N/A)")
    lines += ["", "## Walk-forward (按 quarter)", "",
              "### 外資", "",
              "| quarter | n | 5d wr | 5d avg | 10d wr | 10d avg | 20d wr | 20d avg |",
              "|---|---|---|---|---|---|---|---|"]
    for _, r in summary_foreign.iterrows():
        lines.append(
            f"| {r['quarter']} | {int(r['n'])} | {r.get('wr_5d', float('nan')):.1f}% | "
            f"{r.get('avg_5d', float('nan')):+.2f}% | {r.get('wr_10d', float('nan')):.1f}% | "
            f"{r.get('avg_10d', float('nan')):+.2f}% | {r.get('wr_20d', float('nan')):.1f}% | "
            f"{r.get('avg_20d', float('nan')):+.2f}% |"
        )
    lines += ["", "### 投信", "",
              "| quarter | n | 5d wr | 5d avg | 10d wr | 10d avg | 20d wr | 20d avg |",
              "|---|---|---|---|---|---|---|---|"]
    for _, r in summary_trust.iterrows():
        lines.append(
            f"| {r['quarter']} | {int(r['n'])} | {r.get('wr_5d', float('nan')):.1f}% | "
            f"{r.get('avg_5d', float('nan')):+.2f}% | {r.get('wr_10d', float('nan')):.1f}% | "
            f"{r.get('avg_10d', float('nan')):+.2f}% | {r.get('wr_20d', float('nan')):.1f}% | "
            f"{r.get('avg_20d', float('nan')):+.2f}% |"
        )
    lines += ["", "## Verdict 標準", "",
              "- Pass: 5d 或 10d wr > 53% AND avg > TAIEX baseline 同期",
              "- 看上述 overall + walk-forward 是否符合, 由 user 看完決定 Phase 3 整不整合", ""]
    return "\n".join(lines)


def main() -> int:
    db_url = _load_db_url()
    engine = create_engine(db_url, pool_pre_ping=True)
    print("loading chip data + prices from NAS Postgres ...")
    chip = _fetch_chip_data(engine)
    prices = _fetch_prices(engine)
    taiex = _fetch_taiex(engine)
    print(f"  chip: {len(chip)} rows, prices: {len(prices)} rows, taiex: {len(taiex)} rows")
    if chip.empty or prices.empty:
        print("ERROR: empty input")
        return 1

    horizons = [5, 10, 20]
    # 外資 events
    events_f = find_consecutive_buy_events(chip, factor_col="foreign_net_buy", min_days=3)
    print(f"  foreign events: {len(events_f)}")
    events_f_ret = event_post_returns(events_f, prices, horizons=horizons)
    summary_f = walk_forward_summary(events_f_ret, horizons=horizons)
    overall_f = _overall_stats(events_f_ret, horizons)
    # 投信 events
    events_t = find_consecutive_buy_events(chip, factor_col="trust_net_buy", min_days=3)
    print(f"  trust events: {len(events_t)}")
    events_t_ret = event_post_returns(events_t, prices, horizons=horizons)
    summary_t = walk_forward_summary(events_t_ret, horizons=horizons)
    overall_t = _overall_stats(events_t_ret, horizons)
    # TAIEX baseline
    base = _taiex_baseline(taiex, horizons)

    report = _render_report(summary_f, summary_t, overall_f, overall_t,
                            len(events_f), len(events_t), base)
    out_dir = Path(__file__).resolve().parents[2] / "docs" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{datetime.now(TAIPEI_TZ).strftime('%Y-%m-%d')}-chip-event-prototype.md"
    out_path.write_text(report, encoding="utf-8")
    print(f"report → {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

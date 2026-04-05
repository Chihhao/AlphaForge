"""
研究：營收公布最佳進場時機

因為 MOPS 封鎖 API、無法取得個別公司公告日，
改用「假設公布日」掃描法：測試每月 3/5/7/10 日作為進場日，
找出 alpha 最集中的日期 → 直接回答「每月幾號該買」的問題。

方法：
1. 每月計算 rev_surprise（月營收 vs 3 月均值）
2. 從不同進場日（3/5/7/10日）買入，持有 5/10/20 天
3. 按 rev_surprise 五分位分組
4. 比較各組合的 IC、Q5-Q1 價差、Sharpe
"""
from __future__ import annotations

import os
import warnings
from typing import Dict, List

import numpy as np
import pandas as pd
from scipy import stats
from sqlalchemy import create_engine, text

warnings.filterwarnings("ignore")
PG_URL = os.getenv(
    "PG_URL",
    "postgresql://alphaforge:alphaforge_secret@10.0.4.3:5433/alphaforge",
)
engine = create_engine(PG_URL)
COST = 0.006  # 來回交易成本


def load_revenue() -> pd.DataFrame:
    sql = text("""
        SELECT stock_id, year, month, revenue, revenue_yoy
        FROM stock_revenue_history
        WHERE revenue > 0
        ORDER BY stock_id, year, month
    """)
    df = pd.read_sql(sql, engine)
    df = df.sort_values(["stock_id", "year", "month"]).reset_index(drop=True)

    # rev_surprise: 實際 vs 3 月均值
    g = df.groupby("stock_id")
    df["rev_ma3"] = g["revenue"].transform(
        lambda x: x.rolling(3, min_periods=2).mean().shift(1)
    )
    df["rev_surprise"] = (df["revenue"] - df["rev_ma3"]) / df["rev_ma3"] * 100

    # rev_accel
    df["rev_accel"] = g["revenue_yoy"].diff()

    # 營收月份 → 公布月（次月）
    next_m = df["month"] + 1
    df["ann_year"] = df["year"] + (next_m > 12).astype(int)
    df["ann_month"] = next_m.where(next_m <= 12, next_m - 12)
    return df


def load_prices() -> pd.DataFrame:
    sql = text("""
        SELECT stock_id, date, close
        FROM stock_prices
        WHERE close > 0 AND date >= '2023-01-01'
        ORDER BY stock_id, date
    """)
    df = pd.read_sql(sql, engine)
    df["date"] = pd.to_datetime(df["date"])
    return df


def find_nearest_trade_day(
    trade_dates: np.ndarray, target: pd.Timestamp
) -> pd.Timestamp | None:
    """找 target 之後最近的交易日"""
    idx = np.searchsorted(trade_dates, np.datetime64(target))
    if idx >= len(trade_dates):
        return None
    return pd.Timestamp(trade_dates[idx])


def run_entry_day_scan(
    rev: pd.DataFrame, prices: pd.DataFrame
) -> None:
    """掃描不同進場日的 alpha"""

    trade_dates = np.sort(prices["date"].unique())

    # 建 price lookup
    price_map: Dict[str, pd.Series] = {}
    for sid, grp in prices.groupby("stock_id"):
        price_map[sid] = grp.set_index("date")["close"].sort_index()

    ENTRY_DAYS = [1, 3, 5, 7, 10, 12]  # 每月幾號進場
    HOLD_DAYS = [5, 10, 20]

    print(f"\n{'=' * 110}")
    print(f"  營收公布最佳進場時機研究")
    print(f"{'=' * 110}")

    all_results: List[dict] = []

    for entry_day in ENTRY_DAYS:
        # 為每個 (stock, ann_year, ann_month) 建立事件
        records: List[dict] = []
        for _, row in rev.iterrows():
            sid = row["stock_id"]
            rs = row.get("rev_surprise")
            if pd.isna(rs) or sid not in price_map:
                continue

            # 進場日: 公布月的第 entry_day 天
            try:
                target = pd.Timestamp(int(row["ann_year"]), int(row["ann_month"]), entry_day)
            except ValueError:
                continue

            t0 = find_nearest_trade_day(trade_dates, target)
            if t0 is None:
                continue

            px = price_map[sid]
            if t0 not in px.index:
                continue

            p0 = px.loc[t0]
            loc = px.index.get_loc(t0)
            t0_pos = loc if isinstance(loc, int) else loc.start if isinstance(loc, slice) else int(np.flatnonzero(loc)[0])
            px_vals = px.values

            rec = {
                "stock_id": sid,
                "entry_date": t0,
                "rev_surprise": rs,
                "rev_accel": row.get("rev_accel"),
                "ym": t0.to_period("M"),
            }

            for hold in HOLD_DAYS:
                exit_pos = t0_pos + hold
                if exit_pos < len(px_vals):
                    rec[f"ret_{hold}d"] = (px_vals[exit_pos] - p0) / p0
                else:
                    rec[f"ret_{hold}d"] = np.nan

            records.append(rec)

        if not records:
            continue

        df = pd.DataFrame(records)
        df = df.dropna(subset=["ret_5d", "ret_10d", "ret_20d"])

        # 按月排名
        df["rs_quintile"] = df.groupby("ym")["rev_surprise"].transform(
            lambda x: pd.qcut(x, 5, labels=[1, 2, 3, 4, 5], duplicates="drop")
        )
        df = df.dropna(subset=["rs_quintile"])
        df["rs_quintile"] = df["rs_quintile"].astype(int)

        for hold in HOLD_DAYS:
            col = f"ret_{hold}d"

            # 月度 IC
            monthly_ics = []
            for _, mgrp in df.groupby("ym"):
                if len(mgrp) < 30:
                    continue
                ic, _ = stats.spearmanr(mgrp["rev_surprise"], mgrp[col])
                if not np.isnan(ic):
                    monthly_ics.append(ic)

            if not monthly_ics:
                continue

            avg_ic = np.mean(monthly_ics)
            ic_pos = sum(1 for x in monthly_ics if x > 0) / len(monthly_ics)
            ic_std = np.std(monthly_ics, ddof=1)
            ir = avg_ic / ic_std if ic_std > 0 else 0

            # Q5 vs Q1
            q5 = df[df["rs_quintile"] == 5][col]
            q1 = df[df["rs_quintile"] == 1][col]
            q5_mean = q5.mean() * 100
            q1_mean = q1.mean() * 100
            spread = q5_mean - q1_mean

            # 月度 Sharpe (Q5-Q1)
            monthly_spreads = []
            for _, mgrp in df.groupby("ym"):
                q5m = mgrp[mgrp["rs_quintile"] == 5][col].mean()
                q1m = mgrp[mgrp["rs_quintile"] == 1][col].mean()
                if not np.isnan(q5m) and not np.isnan(q1m):
                    monthly_spreads.append(q5m - q1m)
            sharpe = (np.mean(monthly_spreads) / np.std(monthly_spreads, ddof=1)
                      * np.sqrt(12) if len(monthly_spreads) > 1 else 0)

            all_results.append({
                "entry_day": entry_day,
                "hold": hold,
                "ic": avg_ic,
                "ic_pos": ic_pos,
                "ir": ir,
                "q5": q5_mean,
                "q1": q1_mean,
                "spread": spread,
                "spread_net": spread - COST * 100,
                "sharpe": sharpe,
                "n_months": len(monthly_ics),
                "n_events": len(df),
            })

    # ── 結果表 ──
    rdf = pd.DataFrame(all_results)
    if rdf.empty:
        print("  No results!")
        return

    print(f"\n  ── 進場日 × 持有期 矩陣 (IC / Q5-Q1 價差% / Sharpe) ──\n")
    print(f"  {'進場日':>6}", end="")
    for hold in HOLD_DAYS:
        print(f" │ {'IC':>7} {'Q5-Q1':>7} {'Shrp':>6}  ({hold}d)", end="")
    print(f" │ {'月數':>4}")
    print("  " + "─" * (8 + (8 + 8 + 8 + 6) * len(HOLD_DAYS) + 6))

    best_combo = None
    best_score = -999
    for ed in ENTRY_DAYS:
        sub = rdf[rdf["entry_day"] == ed]
        print(f"  {ed:>4}日", end="")
        for hold in HOLD_DAYS:
            row = sub[sub["hold"] == hold]
            if row.empty:
                print(f" │ {'---':>7} {'---':>7} {'---':>6}      ", end="")
                continue
            r = row.iloc[0]
            ic_str = f"{r['ic']:+.4f}"
            sp_str = f"{r['spread']:+.2f}%"
            sh_str = f"{r['sharpe']:.2f}"

            # 標記最佳
            score = r["ir"] * r["spread_net"]
            if score > best_score:
                best_score = score
                best_combo = (ed, hold, r)

            print(f" │ {ic_str:>7} {sp_str:>7} {sh_str:>6}      ", end="")

        n_months = sub.iloc[0]["n_months"] if not sub.empty else 0
        print(f" │ {n_months:>4}")

    # ── Alpha 集中度：哪個進場日的短期效率最高 ──
    print(f"\n  ── Alpha 效率（每日 alpha = Q5-Q1 / 持有天數）──\n")
    print(f"  {'進場日':>6}", end="")
    for hold in HOLD_DAYS:
        print(f" {hold:>2}d 日均alpha", end="")
    print()
    print("  " + "─" * (8 + 14 * len(HOLD_DAYS)))
    for ed in ENTRY_DAYS:
        sub = rdf[rdf["entry_day"] == ed]
        print(f"  {ed:>4}日", end="")
        for hold in HOLD_DAYS:
            row = sub[sub["hold"] == hold]
            if row.empty:
                print(f" {'---':>13}", end="")
            else:
                daily = row.iloc[0]["spread"] / hold
                print(f"  {daily:>+.3f}%/d   ", end="")
        print()

    # ── 最佳組合 ──
    if best_combo:
        ed, hold, r = best_combo
        print(f"\n  ── 最佳組合 ──")
        print(f"  進場日: 每月 {ed} 日 | 持有: {hold} 天")
        print(f"  IC: {r['ic']:+.4f} (正比 {r['ic_pos']:.0%}) | IR: {r['ir']:.2f}")
        print(f"  Q5: {r['q5']:+.2f}% | Q1: {r['q1']:+.2f}%")
        print(f"  價差: {r['spread']:+.2f}% (扣成本: {r['spread_net']:+.2f}%)")
        print(f"  Sharpe: {r['sharpe']:.2f}")

    # ── 和現有 20d 模型比較 ──
    print(f"\n  ── 和現有 20d 靜態模型比較 ──")
    baseline = rdf[(rdf["entry_day"] == 10) & (rdf["hold"] == 20)]
    if not baseline.empty and best_combo:
        bl = baseline.iloc[0]
        ed, hold, r = best_combo
        print(f"  現有 (10日/20d): IC={bl['ic']:+.4f}, 價差={bl['spread']:+.2f}%, Sharpe={bl['sharpe']:.2f}")
        print(f"  最佳 ({ed}日/{hold}d): IC={r['ic']:+.4f}, 價差={r['spread']:+.2f}%, Sharpe={r['sharpe']:.2f}")
        ic_gain = (r["ic"] - bl["ic"]) / abs(bl["ic"]) * 100 if bl["ic"] != 0 else 0
        print(f"  IC 提升: {ic_gain:+.0f}%")

    # ── 結論 ──
    print(f"\n{'=' * 110}")
    print(f"  結論")
    print(f"{'=' * 110}")

    if best_combo:
        ed, hold, r = best_combo
        if r["ic"] > 0.05 and r["spread_net"] > 0.5:
            print(f"  ★ 營收事件 alpha 確認存在")
            print(f"    最佳策略：每月 {ed} 日買入高 rev_surprise 股票，持有 {hold} 天")
            print(f"    可作為 overlay 與現有 20d 模型疊加")
            if hold <= 10:
                print(f"    短期效率高，適合作為「加碼」而非「取代」")
        elif r["ic"] > 0.03:
            print(f"  ◎ 營收因子有持續性 alpha，但進場時機差異不大")
            print(f"    現有 20d 靜態模型已捕捉大部分 alpha")
        else:
            print(f"  ✗ 營收事件 alpha 不顯著，不建議追加")


def main() -> None:
    print("=== 營收公布最佳進場時機 ===\n")

    print("Loading revenue...")
    rev = load_revenue()
    print(f"  {len(rev):,} records")

    print("Loading prices...")
    prices = load_prices()
    print(f"  {len(prices):,} records")

    run_entry_day_scan(rev, prices)


if __name__ == "__main__":
    main()

"""
驗證：rev_surprise 是否只是動量的影子？

方法：
1. 計算每檔股票進場前 20d 動量 (momentum)
2. 雙重排序：先按動量分 5 組，再在每組內按 rev_surprise 分 5 組
3. 如果控制動量後 rev_surprise 仍有 IC → 真 alpha
4. 如果控制動量後 IC 消失 → rev_surprise 只是動量 proxy

額外測試：
- Fama-MacBeth 迴歸：同時放 momentum + rev_surprise，看各自 t-stat
- 偏相關 IC：控制 momentum 後的 rev_surprise partial IC
"""
from __future__ import annotations

import os
import warnings

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
COST = 0.006


# ── 數據 ──────────────────────────────────────────────────────────────
def load_revenue() -> pd.DataFrame:
    sql = text("""
        SELECT stock_id, year, month, revenue, revenue_yoy
        FROM stock_revenue_history WHERE revenue > 0
        ORDER BY stock_id, year, month
    """)
    df = pd.read_sql(sql, engine)
    df = df.sort_values(["stock_id", "year", "month"]).reset_index(drop=True)
    g = df.groupby("stock_id")
    df["rev_ma3"] = g["revenue"].transform(
        lambda x: x.rolling(3, min_periods=2).mean().shift(1)
    )
    df["rev_surprise"] = (df["revenue"] - df["rev_ma3"]) / df["rev_ma3"] * 100
    df["rev_accel"] = g["revenue_yoy"].diff()

    next_m = df["month"] + 1
    df["ann_year"] = df["year"] + (next_m > 12).astype(int)
    df["ann_month"] = next_m.where(next_m <= 12, next_m - 12)
    return df


def load_prices() -> pd.DataFrame:
    sql = text("""
        SELECT stock_id, date, close
        FROM stock_prices WHERE close > 0 AND date >= '2023-01-01'
        ORDER BY stock_id, date
    """)
    df = pd.read_sql(sql, engine)
    df["date"] = pd.to_datetime(df["date"])
    return df


def build_events(rev: pd.DataFrame, prices: pd.DataFrame, entry_day: int = 5) -> pd.DataFrame:
    """建立事件表：每月 entry_day 進場，含動量和 rev_surprise"""
    trade_dates = np.sort(prices["date"].unique())

    price_map = {}
    for sid, grp in prices.groupby("stock_id"):
        price_map[sid] = grp.set_index("date")["close"].sort_index()

    records = []
    for _, row in rev.iterrows():
        sid = row["stock_id"]
        rs = row.get("rev_surprise")
        if pd.isna(rs) or sid not in price_map:
            continue

        try:
            target = pd.Timestamp(int(row["ann_year"]), int(row["ann_month"]), entry_day)
        except ValueError:
            continue

        idx = np.searchsorted(trade_dates, np.datetime64(target))
        if idx >= len(trade_dates):
            continue
        t0 = pd.Timestamp(trade_dates[idx])

        px = price_map[sid]
        if t0 not in px.index:
            continue

        loc = px.index.get_loc(t0)
        t0_pos = loc if isinstance(loc, int) else loc.start if isinstance(loc, slice) else int(np.flatnonzero(loc)[0])
        px_vals = px.values

        p0 = px_vals[t0_pos]

        # 動量: 進場前 20 天報酬
        mom_pos = t0_pos - 20
        if mom_pos < 0:
            continue
        p_20 = px_vals[mom_pos]
        momentum_20d = (p0 - p_20) / p_20

        # 動量: 進場前 5 天報酬
        mom5_pos = t0_pos - 5
        if mom5_pos < 0:
            continue
        momentum_5d = (p0 - px_vals[mom5_pos]) / px_vals[mom5_pos]

        # 前瞻報酬
        ret_5d = (px_vals[t0_pos + 5] - p0) / p0 if t0_pos + 5 < len(px_vals) else np.nan
        ret_10d = (px_vals[t0_pos + 10] - p0) / p0 if t0_pos + 10 < len(px_vals) else np.nan
        ret_20d = (px_vals[t0_pos + 20] - p0) / p0 if t0_pos + 20 < len(px_vals) else np.nan

        records.append({
            "stock_id": sid,
            "entry_date": t0,
            "ym": t0.to_period("M"),
            "rev_surprise": rs,
            "rev_accel": row.get("rev_accel"),
            "momentum_20d": momentum_20d,
            "momentum_5d": momentum_5d,
            "ret_5d": ret_5d,
            "ret_10d": ret_10d,
            "ret_20d": ret_20d,
        })

    df = pd.DataFrame(records)
    df = df.dropna(subset=["ret_5d", "ret_10d", "ret_20d"])
    return df


# ── 測試 1: 雙重排序 ─────────────────────────────────────────────────
def double_sort_test(df: pd.DataFrame) -> None:
    """先按動量分 5 組，再按 rev_surprise 分 5 組"""
    print(f"\n{'=' * 100}")
    print(f"  測試 1: 雙重排序（控制動量後 rev_surprise 是否仍有效）")
    print(f"{'=' * 100}")

    for hold, col in [(5, "ret_5d"), (10, "ret_10d"), (20, "ret_20d")]:
        print(f"\n  ── 持有 {hold} 天 ──")

        # 按月排名
        df[f"mom_q"] = df.groupby("ym")["momentum_20d"].transform(
            lambda x: pd.qcut(x, 5, labels=[1, 2, 3, 4, 5], duplicates="drop")
        )
        df = df.dropna(subset=["mom_q"])
        df["mom_q"] = df["mom_q"].astype(int)

        # 在每個動量組內按 rev_surprise 排名
        df["rs_q_within"] = df.groupby(["ym", "mom_q"])["rev_surprise"].transform(
            lambda x: pd.qcut(x, 5, labels=[1, 2, 3, 4, 5], duplicates="drop") if len(x) >= 10 else np.nan
        )
        valid = df.dropna(subset=["rs_q_within"])
        valid["rs_q_within"] = valid["rs_q_within"].astype(int)

        if valid.empty:
            print("    (insufficient data)")
            continue

        # 每個動量組的 Q5-Q1 rev_surprise 效果
        print(f"    {'動量組':>6} {'RS Q5':>7} {'RS Q1':>7} {'Q5-Q1':>7} {'筆數':>6}")
        print(f"    " + "─" * 40)

        spreads = []
        for mq in range(1, 6):
            sub = valid[valid["mom_q"] == mq]
            q5 = sub[sub["rs_q_within"] == 5][col].mean() * 100
            q1 = sub[sub["rs_q_within"] == 1][col].mean() * 100
            spread = q5 - q1
            spreads.append(spread)
            mom_label = ["低動量", "  ↓  ", " 中等 ", "  ↑  ", "高動量"][mq - 1]
            print(f"    {mom_label:>6} {q5:>+7.2f} {q1:>+7.2f} {spread:>+7.2f} {len(sub):>6}")

        avg_spread = np.mean(spreads)
        print(f"    {'平均':>6} {'':>7} {'':>7} {avg_spread:>+7.2f}")

        if avg_spread > 0.5:
            print(f"    → ★ 控制動量後 rev_surprise 仍有效 (平均價差 +{avg_spread:.2f}%)")
        elif avg_spread > 0.1:
            print(f"    → ◎ 有殘餘 alpha 但較弱")
        else:
            print(f"    → ✗ rev_surprise alpha 被動量解釋了")


# ── 測試 2: Fama-MacBeth 迴歸 ────────────────────────────────────────
def fama_macbeth_test(df: pd.DataFrame) -> None:
    """每月截面迴歸，看各因子的獨立 t-stat"""
    print(f"\n{'=' * 100}")
    print(f"  測試 2: Fama-MacBeth 迴歸（momentum 和 rev_surprise 各自 t-stat）")
    print(f"{'=' * 100}")

    # 標準化（月度截面 z-score）
    for f in ["rev_surprise", "momentum_20d", "momentum_5d", "rev_accel"]:
        df[f"{f}_z"] = df.groupby("ym")[f].transform(
            lambda x: (x - x.mean()) / x.std() if x.std() > 0 else 0
        )

    for hold, col in [(5, "ret_5d"), (10, "ret_10d"), (20, "ret_20d")]:
        print(f"\n  ── 持有 {hold} 天 ──")

        # 模型 A: 只有 rev_surprise
        # 模型 B: 只有 momentum
        # 模型 C: rev_surprise + momentum（同時）
        models = {
            "A: rev_surprise only": ["rev_surprise_z"],
            "B: momentum_20d only": ["momentum_20d_z"],
            "C: rev_surprise + mom20d": ["rev_surprise_z", "momentum_20d_z"],
            "D: rev_surprise + mom5d + mom20d": ["rev_surprise_z", "momentum_5d_z", "momentum_20d_z"],
        }

        for name, factors in models.items():
            monthly_coefs = {f: [] for f in factors}
            for _, mgrp in df.groupby("ym"):
                if len(mgrp) < 50:
                    continue
                y = mgrp[col].values
                X = mgrp[factors].values
                # OLS: y = X @ beta + e
                try:
                    X_with_const = np.column_stack([np.ones(len(X)), X])
                    beta = np.linalg.lstsq(X_with_const, y, rcond=None)[0]
                    for i, f in enumerate(factors):
                        monthly_coefs[f].append(beta[i + 1])
                except Exception:
                    continue

            print(f"\n    {name}")
            for f in factors:
                coefs = monthly_coefs[f]
                if not coefs:
                    continue
                mean_c = np.mean(coefs)
                std_c = np.std(coefs, ddof=1)
                t_stat = mean_c / (std_c / np.sqrt(len(coefs))) if std_c > 0 else 0
                p_val = 2 * (1 - stats.t.cdf(abs(t_stat), len(coefs) - 1))
                sig = "★★★" if abs(t_stat) > 3 else "★★" if abs(t_stat) > 2 else "★" if abs(t_stat) > 1.5 else ""
                short_f = f.replace("_z", "")
                print(f"      {short_f:>20}: coef={mean_c:>+.6f}, t={t_stat:>6.2f}, p={p_val:.4f} {sig}")


# ── 測試 3: 偏相關 IC ────────────────────────────────────────────────
def partial_ic_test(df: pd.DataFrame) -> None:
    """控制動量的偏 rank IC"""
    print(f"\n{'=' * 100}")
    print(f"  測試 3: 偏相關 IC（控制動量後的 rev_surprise 殘差 IC）")
    print(f"{'=' * 100}")

    for hold, col in [(5, "ret_5d"), (10, "ret_10d"), (20, "ret_20d")]:
        # 月度 rank
        df["rs_rank"] = df.groupby("ym")["rev_surprise"].rank(pct=True)
        df["mom_rank"] = df.groupby("ym")["momentum_20d"].rank(pct=True)
        df["ret_rank"] = df.groupby("ym")[col].rank(pct=True)

        # 原始 IC
        raw_ics = []
        # 偏 IC: 從 rev_surprise rank 中去掉 momentum rank 的影響
        partial_ics = []
        # 動量 IC
        mom_ics = []

        for _, mgrp in df.groupby("ym"):
            if len(mgrp) < 50:
                continue

            rs = mgrp["rs_rank"].values
            mom = mgrp["mom_rank"].values
            ret = mgrp["ret_rank"].values

            valid = ~(np.isnan(rs) | np.isnan(mom) | np.isnan(ret))
            if valid.sum() < 30:
                continue

            rs_v, mom_v, ret_v = rs[valid], mom[valid], ret[valid]

            # 原始 IC
            ic_raw, _ = stats.spearmanr(rs_v, ret_v)
            raw_ics.append(ic_raw)

            # 動量 IC
            ic_mom, _ = stats.spearmanr(mom_v, ret_v)
            mom_ics.append(ic_mom)

            # 偏 IC: 殘差法
            # 1. 用 momentum 預測 rev_surprise → 殘差 = rev_surprise 中「非動量」的部分
            slope_rs, intercept_rs, _, _, _ = stats.linregress(mom_v, rs_v)
            rs_resid = rs_v - (slope_rs * mom_v + intercept_rs)

            # 2. 用 momentum 預測 return → 殘差 = return 中「非動量」的部分
            slope_ret, intercept_ret, _, _, _ = stats.linregress(mom_v, ret_v)
            ret_resid = ret_v - (slope_ret * mom_v + intercept_ret)

            # 3. 殘差之間的相關 = 控制動量後的偏 IC
            ic_partial, _ = stats.spearmanr(rs_resid, ret_resid)
            partial_ics.append(ic_partial)

        if not raw_ics:
            continue

        raw_avg = np.mean(raw_ics)
        mom_avg = np.mean(mom_ics)
        partial_avg = np.mean(partial_ics)
        retained = partial_avg / raw_avg * 100 if raw_avg != 0 else 0

        # t-stats
        raw_t = raw_avg / (np.std(raw_ics, ddof=1) / np.sqrt(len(raw_ics)))
        mom_t = mom_avg / (np.std(mom_ics, ddof=1) / np.sqrt(len(mom_ics)))
        partial_t = partial_avg / (np.std(partial_ics, ddof=1) / np.sqrt(len(partial_ics)))

        print(f"\n  ── 持有 {hold} 天 ──")
        print(f"    {'因子':>20} {'IC':>8} {'t-stat':>8} {'月數':>6}")
        print(f"    " + "─" * 48)
        print(f"    {'rev_surprise (原始)':>20} {raw_avg:>+8.4f} {raw_t:>8.2f} {len(raw_ics):>6}")
        print(f"    {'momentum_20d':>20} {mom_avg:>+8.4f} {mom_t:>8.2f} {len(mom_ics):>6}")
        print(f"    {'rev_surprise (偏IC)':>20} {partial_avg:>+8.4f} {partial_t:>8.2f} {len(partial_ics):>6}")
        print(f"    控制動量後保留: {retained:.0f}%")

        if retained > 60:
            print(f"    → ★ rev_surprise 大部分 alpha 獨立於動量 ({retained:.0f}% retained)")
        elif retained > 30:
            print(f"    → ◎ 部分 alpha 來自動量，但仍有獨立貢獻 ({retained:.0f}% retained)")
        else:
            print(f"    → ✗ rev_surprise alpha 主要被動量解釋 ({retained:.0f}% retained)")


# ── 測試 4: 相關性矩陣 ───────────────────────────────────────────────
def correlation_test(df: pd.DataFrame) -> None:
    """rev_surprise 和 momentum 的截面相關"""
    print(f"\n{'=' * 100}")
    print(f"  測試 4: rev_surprise vs momentum 截面相關（它們有多重疊？）")
    print(f"{'=' * 100}")

    monthly_corrs = []
    for _, mgrp in df.groupby("ym"):
        if len(mgrp) < 50:
            continue
        corr, _ = stats.spearmanr(mgrp["rev_surprise"], mgrp["momentum_20d"])
        if not np.isnan(corr):
            monthly_corrs.append(corr)

    if monthly_corrs:
        avg = np.mean(monthly_corrs)
        print(f"\n  月均 Spearman 相關: {avg:+.4f}")
        print(f"  範圍: [{min(monthly_corrs):+.4f}, {max(monthly_corrs):+.4f}]")
        if abs(avg) > 0.3:
            print(f"  → 高度相關！rev_surprise 和動量有大量重疊")
        elif abs(avg) > 0.15:
            print(f"  → 中度相關，部分重疊但仍有獨立資訊")
        else:
            print(f"  → 低相關，rev_surprise 和動量基本獨立")


def main() -> None:
    print("=== rev_surprise vs Momentum 驗證 ===\n")

    print("Loading data...")
    rev = load_revenue()
    prices = load_prices()

    print("Building events (entry_day=5)...")
    df = build_events(rev, prices, entry_day=5)
    print(f"  {len(df):,} events")

    correlation_test(df)
    double_sort_test(df)
    fama_macbeth_test(df)
    partial_ic_test(df)

    # ── 總結 ──
    print(f"\n{'=' * 100}")
    print(f"  最終判定")
    print(f"{'=' * 100}")


if __name__ == "__main__":
    main()

"""
Track E: 波動率異象因子篩選
假說：低波動異象（low-vol anomaly）是最穩健的市場異象之一，
      但台股可能有獨特的波動率定價模式。
候選因子：
  1. neg_ivol_20d     — 負特異波動率（扣除市場後的殘差波動，低 = 好）
  2. neg_atr_pct      — 負 ATR 百分比（低波動偏好）
  3. neg_max_ret_20d  — 負最大單日報酬（避免彩券型股票）
  4. neg_downside_dev — 負下行偏差（只計負報酬的波動）
  5. neg_skew_20d     — 負偏態（右偏 = 彩券，左偏 = 穩健）
  6. vol_trend        — 波動率趨勢（近期波動 vs 長期波動）
  7. neg_tail_ratio   — 負尾部比率（極端日佔比）
  8. stability_score  — 穩定度分數（低波動 + 低 max_ret + 低偏態的複合）
"""
from __future__ import annotations

import os
import warnings
from typing import List

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
HOLD, GAP = 20, 1

FACTORS: List[str] = [
    "neg_ivol_20d",
    "neg_atr_pct",
    "neg_max_ret_20d",
    "neg_downside_dev",
    "neg_skew_20d",
    "vol_trend",
    "neg_tail_ratio",
    "stability_score",
]


def load_data() -> pd.DataFrame:
    print("載入 stock_prices ...", flush=True)
    sql = text("""
        SELECT stock_id, date, close, high, low, volume
        FROM stock_prices
        WHERE date >= '2022-06-01' AND close > 0 AND volume > 0
        ORDER BY stock_id, date
    """)
    df = pd.read_sql(sql, engine)
    df["date"] = pd.to_datetime(df["date"])
    print(f"  載入 {len(df):,} 筆 ({df['stock_id'].nunique()} 檔)")
    return df


def compute_factors(df: pd.DataFrame) -> pd.DataFrame:
    print("計算波動率因子 ...", flush=True)
    df = df.sort_values(["stock_id", "date"])
    g = df.groupby("stock_id")

    # Daily return
    df["ret"] = g["close"].pct_change()

    # Market return (daily cross-section median)
    daily_mkt = df.groupby("date")["ret"].median()
    df["mkt_ret"] = df["date"].map(daily_mkt)
    df["excess_ret"] = df["ret"] - df["mkt_ret"]

    # ATR
    high_low = df["high"] - df["low"]
    high_pc = (df["high"] - g["close"].shift(1)).abs()
    low_pc = (df["low"] - g["close"].shift(1)).abs()
    tr = pd.concat([high_low, high_pc, low_pc], axis=1).max(axis=1)
    df["atr20"] = g.apply(lambda x: tr.loc[x.index].rolling(20, min_periods=10).mean()).reset_index(level=0, drop=True)
    df["atr_pct"] = df["atr20"] / df["close"] * 100

    # 1. Idiosyncratic volatility (residual vol after removing market)
    df["ivol_20d"] = g["excess_ret"].transform(
        lambda x: x.rolling(20, min_periods=10).std()
    )
    df["neg_ivol_20d"] = -df["ivol_20d"]

    # 2. Negative ATR pct (low vol preference)
    df["neg_atr_pct"] = -df["atr_pct"]

    # 3. Max single-day return in 20d (lottery preference → bad)
    df["max_ret_20d"] = g["ret"].transform(
        lambda x: x.rolling(20, min_periods=10).max()
    )
    df["neg_max_ret_20d"] = -df["max_ret_20d"]

    # 4. Downside deviation (only negative returns)
    def downside_dev(ret_series: pd.Series) -> pd.Series:
        """只計算負報酬的標準差"""
        neg = ret_series.clip(upper=0)
        return neg.rolling(20, min_periods=10).std()

    df["downside_dev"] = g["ret"].transform(downside_dev)
    df["neg_downside_dev"] = -df["downside_dev"]

    # 5. Skewness (negative skew = no lottery tail = good)
    df["skew_20d"] = g["ret"].transform(
        lambda x: x.rolling(20, min_periods=15).skew()
    )
    df["neg_skew_20d"] = -df["skew_20d"]

    # 6. Volatility trend: recent vol / longer vol (increasing = bad)
    vol_10d = g["ret"].transform(lambda x: x.rolling(10, min_periods=5).std())
    vol_40d = g["ret"].transform(lambda x: x.rolling(40, min_periods=20).std())
    df["vol_trend"] = -(vol_10d / (vol_40d + 1e-6))  # negative = decreasing vol

    # 7. Tail ratio: fraction of days with |return| > 2 * avg |return|
    abs_ret = df["ret"].abs()
    avg_abs_ret = g["ret"].transform(lambda x: x.abs().rolling(20, min_periods=10).mean())
    df["tail_day"] = (abs_ret > 2 * avg_abs_ret).astype(float)
    df["tail_ratio"] = g["tail_day"].transform(
        lambda x: x.rolling(20, min_periods=10).mean()
    )
    df["neg_tail_ratio"] = -df["tail_ratio"]

    # 8. Stability score: composite of low vol + low max_ret + low skew
    # Each component ranked daily, then averaged
    # Computed in run_ic_test as it needs cross-section ranking
    df["stability_score"] = np.nan  # placeholder, computed later

    # Forward return
    df["entry"] = g["close"].shift(-GAP)
    df["exit"] = g["close"].shift(-(GAP + HOLD))
    df["fwd_ret"] = (df["exit"] - df["entry"]) / df["entry"]

    df = df[df["date"] >= "2023-03-01"].copy()
    df["ym"] = df["date"].dt.to_period("M")

    # Compute stability score (needs daily cross-section)
    def compute_stability(group: pd.DataFrame) -> pd.Series:
        r1 = group["neg_ivol_20d"].rank(pct=True, na_option="keep")
        r2 = group["neg_max_ret_20d"].rank(pct=True, na_option="keep")
        r3 = group["neg_skew_20d"].rank(pct=True, na_option="keep")
        return (r1 + r2 + r3) / 3

    df["stability_score"] = (
        df.groupby("date")
        .apply(compute_stability)
        .reset_index(level=0, drop=True)
    )

    print(f"  計算完成，有效筆數: {df.dropna(subset=['fwd_ret']).shape[0]:,}")
    return df


def run_ic_test(df: pd.DataFrame) -> None:
    print(f"\n{'=' * 100}")
    print("  Track E: 波動率異象因子 IC 篩選")
    print(f"{'=' * 100}")

    all_months = sorted(df["ym"].unique())
    summary = []

    for factor in FACTORS:
        monthly_stats = []
        for ym in all_months:
            month_data = df[df["ym"] == ym]
            daily_ics = []
            daily_tops = []
            daily_bots = []
            daily_mkts = []

            for d, day in month_data.groupby("date"):
                valid = day.dropna(subset=[factor, "fwd_ret"])
                if len(valid) < 100:
                    continue
                ic, _ = stats.spearmanr(valid[factor], valid["fwd_ret"])
                if np.isnan(ic):
                    continue
                daily_ics.append(ic)

                ranked = valid[factor].rank(pct=True)
                top10 = valid.loc[ranked >= 0.9, "fwd_ret"]
                bot10 = valid.loc[ranked <= 0.1, "fwd_ret"]
                daily_tops.append(top10.mean())
                daily_bots.append(bot10.mean())
                daily_mkts.append(valid["fwd_ret"].mean())

            if daily_ics:
                monthly_stats.append(
                    {
                        "month": str(ym),
                        "ic": np.mean(daily_ics),
                        "top10": np.mean(daily_tops),
                        "bot10": np.mean(daily_bots),
                        "mkt": np.mean(daily_mkts),
                    }
                )

        if not monthly_stats:
            continue
        mdf = pd.DataFrame(monthly_stats)
        avg_ic = mdf["ic"].mean()
        ic_pos = (mdf["ic"] > 0).mean()
        ic_tstat = avg_ic / (mdf["ic"].std(ddof=1) / np.sqrt(len(mdf))) if mdf["ic"].std() > 0 else 0
        avg_excess = (mdf["top10"] - mdf["mkt"]).mean() * 100
        avg_ls = (mdf["top10"] - mdf["bot10"]).mean() * 100
        ls_pos = ((mdf["top10"] - mdf["bot10"]) > 0).mean()

        summary.append(
            {
                "factor": factor,
                "months": len(mdf),
                "ic": avg_ic,
                "ic_pos": ic_pos,
                "ic_tstat": ic_tstat,
                "excess": avg_excess,
                "ls": avg_ls,
                "ls_pos": ls_pos,
            }
        )

    print(
        f"\n  {'因子':>25} {'月數':>4} {'IC':>8} {'IC正':>5} {'t值':>7}"
        f" {'超額':>8} {'L-S':>8} {'LS正':>5} {'判定':>6}"
    )
    print("  " + "─" * 90)

    for s in sorted(summary, key=lambda x: -x["ic"]):
        verdict = "★★★" if s["ic"] > 0.03 and s["ic_pos"] >= 0.6 else \
                  "★★" if s["ic"] > 0.02 and s["ic_pos"] >= 0.55 else \
                  "★" if s["ic"] > 0.01 and s["ic_pos"] >= 0.5 else \
                  "—"
        print(
            f"  {s['factor']:>25} {s['months']:>4} {s['ic']:>+8.4f} {s['ic_pos']:>4.0%}"
            f" {s['ic_tstat']:>+7.2f} {s['excess']:>+7.2f}% {s['ls']:>+7.2f}%"
            f" {s['ls_pos']:>4.0%} {verdict:>6}"
        )

    # 逐月 IC for top 3
    top3 = sorted(summary, key=lambda x: -x["ic"])[:3]
    for s in top3:
        factor = s["factor"]
        print(f"\n  ── {factor} 逐月 IC ──")
        for ym in all_months:
            month_data = df[df["ym"] == ym]
            daily_ics = []
            for d, day in month_data.groupby("date"):
                valid = day.dropna(subset=[factor, "fwd_ret"])
                if len(valid) < 100:
                    continue
                ic, _ = stats.spearmanr(valid[factor], valid["fwd_ret"])
                if not np.isnan(ic):
                    daily_ics.append(ic)
            if daily_ics:
                ic = np.mean(daily_ics)
                bar = "+" * int(abs(ic) * 200) if ic > 0 else "-" * int(abs(ic) * 200)
                print(f"    {ym} IC={ic:+.4f} {'|':>1}{bar}")

    print(f"\n{'=' * 100}")
    print("  Track E 完成")
    print(f"{'=' * 100}\n")


if __name__ == "__main__":
    df = load_data()
    df = compute_factors(df)
    run_ic_test(df)

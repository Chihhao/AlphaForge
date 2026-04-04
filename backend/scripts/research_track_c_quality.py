"""
Track C: 基本面品質與複合因子篩選
假說：單因子 ROE/PB/yield 已在模型中，但複合因子（如 Greenblatt magic formula）
      及盈餘穩定性可能捕捉到單因子遺漏的品質維度。
候選因子：
  1. magic_formula    — ROE rank + (1/PB) rank 的平均（品質+價值複合）
  2. eps_stability    — 近 4~8 季 EPS 標準差/均值的負值（穩定性）
  3. eps_accel        — 最新季 EPS YoY - 前季 EPS YoY（盈餘加速度）
  4. rev_slope_6m     — 近 6 個月 revenue_yoy 的線性迴歸斜率（營收趨勢）
  5. yield_x_roe      — 殖利率 × ROE 交互（高殖利 + 高 ROE = 被忽視的好股）
  6. pb_inv_rank      — 1/PB 排名（純價值因子，看是否被 ML 捕捉）
  7. roe_momentum     — ROE 變化（如果有多期 ROE 快照）
  8. rev_mom_3m       — 近 3 個月 revenue_mom 平均（營收月增率動量）
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
    "magic_formula",
    "neg_eps_cv",
    "eps_accel",
    "rev_slope_6m",
    "yield_x_roe",
    "pb_inv",
    "rev_mom_3m",
    "rev_surprise_persist",
]


def load_features() -> pd.DataFrame:
    print("載入 stock_features ...", flush=True)
    sql = text("""
        SELECT stock_id, date, close, roe, pb_ratio, yield_rate,
               revenue_yoy, rev_surprise, rev_accel
        FROM stock_features
        WHERE date >= '2023-03-01' AND close > 0
        ORDER BY stock_id, date
    """)
    df = pd.read_sql(sql, engine)
    df["date"] = pd.to_datetime(df["date"])
    print(f"  features: {len(df):,} 筆")
    return df


def load_eps() -> pd.DataFrame:
    print("載入 stock_eps_history ...", flush=True)
    sql = text("""
        SELECT stock_id, year, quarter, eps, eps_yoy
        FROM stock_eps_history
        WHERE eps IS NOT NULL
        ORDER BY stock_id, year, quarter
    """)
    df = pd.read_sql(sql, engine)
    print(f"  EPS: {len(df):,} 筆")
    return df


def load_revenue() -> pd.DataFrame:
    print("載入 stock_revenue_history ...", flush=True)
    sql = text("""
        SELECT stock_id, year, month, revenue, revenue_yoy, revenue_mom
        FROM stock_revenue_history
        WHERE revenue > 0
        ORDER BY stock_id, year, month
    """)
    df = pd.read_sql(sql, engine)
    print(f"  revenue: {len(df):,} 筆")
    return df


def compute_eps_factors(eps_df: pd.DataFrame) -> pd.DataFrame:
    """從季度 EPS 計算因子，回傳 stock_id, quarter_date, factor_columns"""
    eps_df = eps_df.sort_values(["stock_id", "year", "quarter"])
    g = eps_df.groupby("stock_id")

    # EPS 穩定性: CV = std/|mean| of last 4-8 quarters (negative = prefer stable)
    eps_df["eps_cv"] = g["eps"].transform(
        lambda x: x.rolling(4, min_periods=3).std()
        / (x.rolling(4, min_periods=3).mean().abs() + 0.01)
    )
    eps_df["neg_eps_cv"] = -eps_df["eps_cv"]

    # EPS 加速度: 本季 YoY - 前季 YoY
    eps_df["prev_yoy"] = g["eps_yoy"].shift(1)
    eps_df["eps_accel"] = eps_df["eps_yoy"] - eps_df["prev_yoy"]

    # 建立日期：季末日期（Q1=3/31, Q2=6/30, Q3=9/30, Q4=12/31）
    # 但財報公布有延遲，保守使用 +2 個月
    q_to_month = {1: 5, 2: 8, 3: 11, 4: 2}  # 公布月
    q_to_year_add = {1: 0, 2: 0, 3: 0, 4: 1}
    eps_df["pub_year"] = eps_df["year"] + eps_df["quarter"].map(q_to_year_add)
    eps_df["pub_month"] = eps_df["quarter"].map(q_to_month)
    eps_df["pub_date"] = pd.to_datetime(
        eps_df["pub_year"].astype(str) + "-" + eps_df["pub_month"].astype(str) + "-15"
    )

    return eps_df[["stock_id", "pub_date", "neg_eps_cv", "eps_accel"]].dropna(
        subset=["neg_eps_cv"]
    )


def compute_revenue_factors(rev_df: pd.DataFrame) -> pd.DataFrame:
    """從月營收計算因子"""
    rev_df = rev_df.sort_values(["stock_id", "year", "month"])
    g = rev_df.groupby("stock_id")

    # 營收趨勢斜率: 近 6 個月 revenue_yoy 的線性回歸斜率
    def rolling_slope(s: pd.Series) -> pd.Series:
        result = s.copy() * np.nan
        vals = s.values
        x = np.arange(6)
        for i in range(5, len(vals)):
            y = vals[i - 5 : i + 1]
            if np.any(np.isnan(y)):
                continue
            slope, _, _, _, _ = stats.linregress(x, y)
            result.iloc[i] = slope
        return result

    rev_df["rev_slope_6m"] = g["revenue_yoy"].transform(rolling_slope)

    # 營收月增率動量: 近 3 個月 revenue_mom 平均
    rev_df["rev_mom_3m"] = g["revenue_mom"].transform(
        lambda x: x.rolling(3, min_periods=2).mean()
    )

    # 營收驚喜持續性: 近 2 個月 revenue_yoy 變化
    rev_df["rev_surprise_persist"] = g["revenue_yoy"].diff(1)

    # 建立日期（營收通常在次月 10 號公布，保守用 15 號）
    rev_df["pub_date"] = pd.to_datetime(
        rev_df["year"].astype(str)
        + "-"
        + rev_df["month"].astype(str).str.zfill(2)
        + "-15"
    ) + pd.DateOffset(months=1)

    return rev_df[
        ["stock_id", "pub_date", "rev_slope_6m", "rev_mom_3m", "rev_surprise_persist"]
    ].dropna(subset=["rev_slope_6m"])


def merge_all(
    features: pd.DataFrame,
    eps_factors: pd.DataFrame,
    rev_factors: pd.DataFrame,
) -> pd.DataFrame:
    print("合併所有因子 ...", flush=True)
    df = features.copy()

    # 基本複合因子（直接從 features 計算）
    # Magic formula: ROE rank + 1/PB rank (each day cross-section)
    df["pb_inv"] = 1.0 / (df["pb_ratio"].replace(0, np.nan))
    df["yield_x_roe"] = df["yield_rate"] * df["roe"]

    # Magic formula needs daily cross-section ranking, computed later
    # rev_surprise_persist from revenue needs merging

    # Merge EPS factors (forward-fill from pub_date)
    eps_factors = eps_factors.sort_values(["stock_id", "pub_date"])
    eps_factors = eps_factors.rename(columns={"pub_date": "date"})

    # For each stock, forward-fill EPS factors to daily features
    for col in ["neg_eps_cv", "eps_accel"]:
        lookup = eps_factors.dropna(subset=[col])[["stock_id", "date", col]]
        merged = pd.merge_asof(
            df.sort_values("date"),
            lookup.sort_values("date"),
            on="date",
            by="stock_id",
            direction="backward",
        )
        df[col] = merged[col].values

    # Merge revenue factors (forward-fill)
    rev_factors = rev_factors.sort_values(["stock_id", "pub_date"])
    rev_factors = rev_factors.rename(columns={"pub_date": "date"})

    for col in ["rev_slope_6m", "rev_mom_3m", "rev_surprise_persist"]:
        lookup = rev_factors.dropna(subset=[col])[["stock_id", "date", col]]
        merged = pd.merge_asof(
            df.sort_values("date"),
            lookup.sort_values("date"),
            on="date",
            by="stock_id",
            direction="backward",
        )
        df[col] = merged[col].values

    # Magic formula: cross-section ranks
    def magic_rank(group: pd.DataFrame) -> pd.Series:
        roe_r = group["roe"].rank(pct=True, na_option="keep")
        pb_inv_r = group["pb_inv"].rank(pct=True, na_option="keep")
        return (roe_r + pb_inv_r) / 2

    df["magic_formula"] = df.groupby("date").apply(
        lambda g: magic_rank(g)
    ).reset_index(level=0, drop=True)

    # Forward return
    g = df.groupby("stock_id")
    df = df.sort_values(["stock_id", "date"])
    df["entry"] = g["close"].shift(-GAP)
    df["exit"] = g["close"].shift(-(GAP + HOLD))
    df["fwd_ret"] = (df["exit"] - df["entry"]) / df["entry"]
    df["ym"] = df["date"].dt.to_period("M")

    print(f"  合併完成: {len(df):,} 筆")
    return df


def run_ic_test(df: pd.DataFrame) -> None:
    print(f"\n{'=' * 100}")
    print("  Track C: 基本面品質與複合因子 IC 篩選")
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
    print("  Track C 完成")
    print(f"{'=' * 100}\n")


if __name__ == "__main__":
    features = load_features()
    eps = load_eps()
    revenue = load_revenue()

    eps_factors = compute_eps_factors(eps)
    rev_factors = compute_revenue_factors(revenue)
    df = merge_all(features, eps_factors, rev_factors)
    run_ic_test(df)

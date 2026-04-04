"""
Track B: 動量分解與風格因子篩選
假說：動量可分解為產業動量+個股特異動量，且不同計算方式的動量預測力不同。
候選因子：
  1. high_52w_ratio  — Close / 52 週最高價（近歷史高點效應）
  2. neg_ret5        — 負5日報酬（短期反轉）
  3. ret20           — 20日動量（中期追漲）
  4. accel_10_20     — ret10 - ret20（加速度）
  5. vol_adj_ret20   — ret20 / volatility（風險調整動量）
  6. idio_ret20      — 個股 20d 報酬 - 同期市場報酬（特異動量）
  7. neg_drawdown_20d — 負 20 日最大回撤（回撤越小越好）
  8. up_vol_ratio    — 上漲日成交量 / 下跌日成交量（量能方向）
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
HOLD, GAP, COST = 20, 1, 0.006

FACTORS: List[str] = [
    "high_52w_ratio",
    "neg_ret5",
    "ret20",
    "accel_10_20",
    "vol_adj_ret20",
    "idio_ret20",
    "neg_drawdown_20d",
    "up_vol_ratio",
]


def load_data() -> pd.DataFrame:
    print("載入 stock_prices ...", flush=True)
    sql = text("""
        SELECT stock_id, date, close, high, volume
        FROM stock_prices
        WHERE date >= '2022-01-01' AND close > 0 AND volume > 0
        ORDER BY stock_id, date
    """)
    df = pd.read_sql(sql, engine)
    df["date"] = pd.to_datetime(df["date"])
    print(f"  載入 {len(df):,} 筆 ({df['stock_id'].nunique()} 檔)")
    return df


def compute_factors(df: pd.DataFrame) -> pd.DataFrame:
    print("計算動量因子 ...", flush=True)
    g = df.groupby("stock_id")

    # Returns at different horizons
    df["ret1"] = g["close"].pct_change(1)
    df["ret5"] = g["close"].pct_change(5)
    df["ret10"] = g["close"].pct_change(10)
    df["ret20"] = g["close"].pct_change(20)

    # 1. 52-week high ratio
    df["high_52w"] = g["high"].transform(lambda x: x.rolling(250, min_periods=60).max())
    df["high_52w_ratio"] = df["close"] / df["high_52w"]

    # 2. Short-term reversal (negative 5d return)
    df["neg_ret5"] = -df["ret5"]

    # 3. ret20 already computed

    # 4. Acceleration: ret10 - ret20
    df["accel_10_20"] = df["ret10"] - df["ret20"]

    # 5. Volatility-adjusted momentum
    df["vol_20d"] = g["ret1"].transform(lambda x: x.rolling(20, min_periods=10).std())
    df["vol_adj_ret20"] = df["ret20"] / (df["vol_20d"] + 1e-6)

    # 6. Idiosyncratic momentum (vs market)
    # Market return = cross-sectional median return each day
    daily_mkt = df.groupby("date")["ret20"].median()
    df["mkt_ret20"] = df["date"].map(daily_mkt)
    df["idio_ret20"] = df["ret20"] - df["mkt_ret20"]

    # 7. Max drawdown in last 20d (negative = prefer low drawdown)
    def rolling_max_dd(close_series: pd.Series) -> pd.Series:
        """向量化 rolling max drawdown"""
        result = close_series.copy() * np.nan
        vals = close_series.values
        for i in range(20, len(vals)):
            window = vals[i - 20 : i + 1]
            peak = np.maximum.accumulate(window)
            dd = (window - peak) / peak
            result.iloc[i] = dd.min()
        return result

    df["drawdown_20d"] = g["close"].transform(rolling_max_dd)
    df["neg_drawdown_20d"] = -df["drawdown_20d"]  # positive = less drawdown

    # 8. Up-volume ratio (volume on up days / volume on down days)
    df["up_day"] = (df["ret1"] > 0).astype(float)
    df["up_vol"] = df["volume"] * df["up_day"]
    df["dn_vol"] = df["volume"] * (1 - df["up_day"])
    df["up_vol_5d"] = g["up_vol"].transform(lambda x: x.rolling(10, min_periods=5).sum())
    df["dn_vol_5d"] = g["dn_vol"].transform(lambda x: x.rolling(10, min_periods=5).sum())
    df["up_vol_ratio"] = df["up_vol_5d"] / (df["dn_vol_5d"] + 1)

    # Forward return
    df["entry"] = g["close"].shift(-GAP)
    df["exit"] = g["close"].shift(-(GAP + HOLD))
    df["fwd_ret"] = (df["exit"] - df["entry"]) / df["entry"]

    df = df[df["date"] >= "2023-03-01"].copy()
    df["ym"] = df["date"].dt.to_period("M")
    print(f"  計算完成，有效筆數: {df.dropna(subset=['fwd_ret']).shape[0]:,}")
    return df


def run_ic_test(df: pd.DataFrame) -> None:
    print(f"\n{'=' * 100}")
    print("  Track B: 動量分解與風格因子 IC 篩選")
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
    print("  Track B 完成")
    print(f"{'=' * 100}\n")


if __name__ == "__main__":
    df = load_data()
    df = compute_factors(df)
    run_ic_test(df)

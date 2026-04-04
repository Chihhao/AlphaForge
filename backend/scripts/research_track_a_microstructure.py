"""
Track A: 價格微結構因子篩選
假說：OHLC 日內行為蘊含散戶 vs 法人的資訊不對稱。
候選因子：
  1. clv_5d        — 5日平均 Close Location Value（買壓指標）
  2. neg_upper_shadow_5d — 5日平均上影線比例的負值（拒絕高點 → 壞訊號）
  3. lower_shadow_5d    — 5日平均下影線比例（抄底力道）
  4. gap_5d         — 5日平均跳空幅度（隔夜情緒）
  5. neg_amihud_20d — 20日 Amihud 流動性（低流動性溢酬）
  6. body_ratio_5d  — 5日平均實體/影線比（趨勢確定性）
  7. neg_range_pct  — 負日內振幅（低波動偏好）
  8. overnight_ret_5d — 5日隔夜報酬（夜盤溢酬）
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
    "clv_5d",
    "neg_upper_shadow_5d",
    "lower_shadow_5d",
    "gap_5d",
    "neg_amihud_20d",
    "body_ratio_5d",
    "neg_range_pct_20d",
    "overnight_ret_5d",
]


def load_data() -> pd.DataFrame:
    print("載入 stock_prices ...", flush=True)
    sql = text("""
        SELECT stock_id, date, open, high, low, close, volume
        FROM stock_prices
        WHERE date >= '2022-10-01' AND close > 0 AND volume > 0
        ORDER BY stock_id, date
    """)
    df = pd.read_sql(sql, engine)
    df["date"] = pd.to_datetime(df["date"])
    print(f"  載入 {len(df):,} 筆 ({df['stock_id'].nunique()} 檔)")
    return df


def compute_factors(df: pd.DataFrame) -> pd.DataFrame:
    print("計算微結構因子 ...", flush=True)
    g = df.groupby("stock_id")

    # 日內振幅
    range_ = (df["high"] - df["low"]).replace(0, np.nan)
    range_pct = range_ / df["close"]

    # 1. Close Location Value
    df["clv"] = (df["close"] - df["low"]) / range_
    df["clv_5d"] = g["clv"].transform(lambda x: x.rolling(5, min_periods=3).mean())

    # 2. Upper shadow ratio (negative → less rejection is better)
    max_oc = df[["open", "close"]].max(axis=1)
    df["upper_shadow"] = (df["high"] - max_oc) / range_
    df["neg_upper_shadow_5d"] = -g["upper_shadow"].transform(
        lambda x: x.rolling(5, min_periods=3).mean()
    )

    # 3. Lower shadow ratio (buying at lows)
    min_oc = df[["open", "close"]].min(axis=1)
    df["lower_shadow"] = (min_oc - df["low"]) / range_
    df["lower_shadow_5d"] = g["lower_shadow"].transform(
        lambda x: x.rolling(5, min_periods=3).mean()
    )

    # 4. Gap: (Open - prev Close) / prev Close
    prev_close = g["close"].shift(1)
    df["gap"] = (df["open"] - prev_close) / prev_close
    df["gap_5d"] = g["gap"].transform(lambda x: x.rolling(5, min_periods=3).mean())

    # 5. Amihud illiquidity (negative → prefer liquid stocks)
    daily_ret = g["close"].pct_change()
    dollar_vol = df["close"] * df["volume"]
    df["amihud"] = daily_ret.abs() / (dollar_vol + 1)
    df["neg_amihud_20d"] = -g["amihud"].transform(
        lambda x: x.rolling(20, min_periods=10).mean()
    )

    # 6. Body ratio: |close - open| / range (trend certainty)
    df["body_ratio"] = (df["close"] - df["open"]).abs() / range_
    df["body_ratio_5d"] = g["body_ratio"].transform(
        lambda x: x.rolling(5, min_periods=3).mean()
    )

    # 7. Negative range pct (low intraday vol preference)
    df["range_pct"] = range_pct
    df["neg_range_pct_20d"] = -g["range_pct"].transform(
        lambda x: x.rolling(20, min_periods=10).mean()
    )

    # 8. Overnight return: (Open - prev Close) / prev Close, accumulated
    df["overnight_ret"] = (df["open"] - prev_close) / prev_close
    df["overnight_ret_5d"] = g["overnight_ret"].transform(
        lambda x: x.rolling(5, min_periods=3).sum()
    )

    # Forward return
    df["entry"] = g["close"].shift(-GAP)
    df["exit"] = g["close"].shift(-(GAP + HOLD))
    df["fwd_ret"] = (df["exit"] - df["entry"]) / df["entry"]

    # 只保留覆蓋完整的期間
    df = df[df["date"] >= "2023-03-01"].copy()
    df["ym"] = df["date"].dt.to_period("M")
    print(f"  計算完成，有效筆數: {df.dropna(subset=['fwd_ret']).shape[0]:,}")
    return df


def run_ic_test(df: pd.DataFrame) -> None:
    """對每個因子做逐日截面 IC 測試"""
    print(f"\n{'=' * 100}")
    print("  Track A: 價格微結構因子 IC 篩選")
    print(f"{'=' * 100}")

    all_months = sorted(df["ym"].unique())
    summary = []

    for factor in FACTORS:
        monthly_stats = []
        all_daily_ics: list[float] = []

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
                all_daily_ics.append(ic)

                # Top/Bot 10%
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
                        "ic_pos": np.mean([1 for x in daily_ics if x > 0]),
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

    # ── 結果表 ──
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

    # ── 逐年詳情（top 3 因子）──
    top3 = sorted(summary, key=lambda x: -x["ic"])[:3]
    for s in top3:
        factor = s["factor"]
        print(f"\n  ── {factor} 逐月 IC ──")
        monthly_ics = []
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
                monthly_ics.append((str(ym), np.mean(daily_ics)))

        for m, ic in monthly_ics:
            bar = "+" * int(abs(ic) * 200) if ic > 0 else "-" * int(abs(ic) * 200)
            print(f"    {m} IC={ic:+.4f} {'|':>1}{bar}")

    print(f"\n{'=' * 100}")
    print("  Track A 完成")
    print(f"{'=' * 100}\n")


if __name__ == "__main__":
    df = load_data()
    df = compute_factors(df)
    run_ic_test(df)

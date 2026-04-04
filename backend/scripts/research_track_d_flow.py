"""
Track D: 法人流向動態因子篩選
假說：三大法人的「互動模式」比單一法人的淨買超更有預測力。
      法人共識、分歧、持續性等二階資訊可能包含 alpha。
候選因子：
  1. inst_consensus    — 三法人方向一致性（+3=全買, -3=全賣, 0=分歧）
  2. smart_dumb_div    — 外資 - 投信（聰明錢 vs 散戶代理人分歧）
  3. foreign_persist_5d — 外資淨買超 5 日自相關（持續性 = 大單進場）
  4. neg_margin_chg_5d — 負融資餘額 5 日變化（反向散戶）
  5. total_inst_norm   — (外資+投信+自營)合計淨買超 / 成交量（法人佔比）
  6. chip_momentum_10d — 近 10 日外資累積淨買超的方向一致性
  7. dealer_contrarian  — 自營商逆勢買入（股價跌但自營商買）
  8. short_interest_chg — 融券餘額變化率（看空壓力）
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
    "inst_consensus",
    "smart_dumb_div",
    "foreign_persist_5d",
    "neg_margin_chg_5d",
    "total_inst_norm",
    "chip_momentum_10d",
    "dealer_contrarian",
    "neg_short_chg_5d",
]


def load_data() -> pd.DataFrame:
    print("載入 stock_chip_data + stock_prices ...", flush=True)

    sql_chip = text("""
        SELECT stock_id, date,
               foreign_net_buy, trust_net_buy, dealer_net_buy,
               margin_balance, short_balance
        FROM stock_chip_data
        WHERE date >= '2023-01-01'
        ORDER BY stock_id, date
    """)
    chip = pd.read_sql(sql_chip, engine)
    chip["date"] = pd.to_datetime(chip["date"])
    print(f"  chip_data: {len(chip):,} 筆")

    sql_price = text("""
        SELECT stock_id, date, close, volume
        FROM stock_prices
        WHERE date >= '2023-01-01' AND close > 0 AND volume > 0
        ORDER BY stock_id, date
    """)
    price = pd.read_sql(sql_price, engine)
    price["date"] = pd.to_datetime(price["date"])
    print(f"  prices: {len(price):,} 筆")

    df = pd.merge(price, chip, on=["stock_id", "date"], how="inner")
    print(f"  合併後: {len(df):,} 筆 ({df['stock_id'].nunique()} 檔)")
    return df


def compute_factors(df: pd.DataFrame) -> pd.DataFrame:
    print("計算法人流向動態因子 ...", flush=True)
    df = df.sort_values(["stock_id", "date"])
    g = df.groupby("stock_id")

    # 基本衍生
    foreign = df["foreign_net_buy"].fillna(0)
    trust = df["trust_net_buy"].fillna(0)
    dealer = df["dealer_net_buy"].fillna(0)
    total = foreign + trust + dealer

    # 1. Institutional consensus: sign agreement
    f_sign = np.sign(foreign)
    t_sign = np.sign(trust)
    d_sign = np.sign(dealer)
    df["inst_consensus_raw"] = f_sign + t_sign + d_sign
    # 5d rolling average for stability
    df["inst_consensus"] = g["inst_consensus_raw"].transform(
        lambda x: x.rolling(5, min_periods=3).mean()
    )

    # 2. Smart-dumb divergence: foreign - trust (smart money vs retail proxy)
    df["sd_raw"] = foreign - trust
    # Normalize by stock's recent volume
    avg_vol = g["volume"].transform(lambda x: x.rolling(20, min_periods=10).mean())
    df["smart_dumb_div"] = g["sd_raw"].transform(
        lambda x: x.rolling(5, min_periods=3).sum()
    ) / (avg_vol + 1)

    # 3. Foreign persistence: 5d rolling autocorrelation of daily foreign_net_buy
    def rolling_autocorr(s: pd.Series) -> pd.Series:
        """5-day sign consistency"""
        sign_s = np.sign(s)
        return sign_s.rolling(5, min_periods=3).mean().abs()

    df["foreign_persist_5d"] = g["foreign_net_buy"].transform(rolling_autocorr)

    # 4. Negative margin change (contrarian vs retail)
    margin = df["margin_balance"].fillna(method="ffill")
    df["margin_chg"] = g["margin_balance"].pct_change(5)
    df["neg_margin_chg_5d"] = -df["margin_chg"]

    # 5. Total institutional buy / volume (institutional participation)
    df["total_inst_norm"] = g[["foreign_net_buy", "trust_net_buy", "dealer_net_buy"]].transform("sum").sum(axis=1)
    # Simplified: just use total / volume
    df["total_inst_norm"] = total / (df["volume"] + 1)
    df["total_inst_norm"] = g["total_inst_norm"].transform(
        lambda x: x.rolling(5, min_periods=3).mean()
    )

    # 6. Chip momentum: direction consistency of foreign 10d cumulative
    foreign_10d = g["foreign_net_buy"].transform(
        lambda x: x.rolling(10, min_periods=5).sum()
    )
    # 10d cumulative sign * magnitude (normalized)
    df["chip_momentum_10d"] = foreign_10d / (avg_vol + 1)

    # 7. Dealer contrarian: dealer buys while price falls
    ret_5d = g["close"].pct_change(5)
    dealer_5d = g["dealer_net_buy"].transform(
        lambda x: x.rolling(5, min_periods=3).sum()
    )
    # Dealer buying when price falling = positive signal
    df["dealer_contrarian"] = np.where(
        ret_5d < 0, dealer_5d / (avg_vol + 1), 0
    )

    # 8. Short interest change (negative = prefer decreasing shorts)
    short = df["short_balance"].fillna(method="ffill")
    df["short_chg_5d"] = g["short_balance"].pct_change(5)
    df["neg_short_chg_5d"] = -df["short_chg_5d"]

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
    print("  Track D: 法人流向動態因子 IC 篩選")
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
    print("  Track D 完成")
    print(f"{'=' * 100}\n")


if __name__ == "__main__":
    df = load_data()
    df = compute_factors(df)
    run_ic_test(df)

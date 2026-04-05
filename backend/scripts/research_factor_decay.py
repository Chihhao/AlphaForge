"""
因子衰退診斷
============
模型 2025-09~2026-01 表現強勁（alpha +6.62%, t=5.41），
但 2026-02 下旬至 03 月出現連續負超額。
本腳本診斷：
  1. 逐月逐因子 IC — 哪個因子在衰退？
  2. 去極端值後的真實 alpha
  3. 做空端表現分析
  4. 近期推薦股票 vs 強勢期推薦股票的差異

使用: cd backend && ./.venv/bin/python scripts/research_factor_decay.py
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


def load_data():
    print("載入資料 ...", flush=True)
    feat = pd.read_sql(text(
        "SELECT stock_id, date, roe, yield_rate, pb_ratio, revenue_yoy,"
        " rev_surprise, rev_accel, foreign_hold_chg_5d, dealer_buy_20d,"
        " vol_ratio, ivol_20d, trust_net_buy"
        " FROM stock_features WHERE date >= :start ORDER BY stock_id, date"
    ), engine, params={"start": "2025-06-01"})
    feat["date"] = pd.to_datetime(feat["date"])

    prices = pd.read_sql(text(
        "SELECT stock_id, date, close FROM stock_prices"
        " WHERE date >= :start AND close > 0 ORDER BY stock_id, date"
    ), engine, params={"start": "2025-06-01"})
    prices["date"] = pd.to_datetime(prices["date"])

    signals = pd.read_sql(text(
        "SELECT signal_date, stock_id, stock_name, time_dimension, direction, weighted_win_rate"
        " FROM alpha_signal_history"
        " WHERE time_dimension IN (:d1, :d2)"
        " ORDER BY signal_date, direction, weighted_win_rate DESC"
    ), engine, params={"d1": "30d", "d2": "20d"})
    signals["signal_date"] = pd.to_datetime(signals["signal_date"])

    print(f"  Features: {len(feat):,}, Prices: {len(prices):,}, Signals: {len(signals):,}")
    return feat, prices, signals


def part1_factor_ic_by_month(feat, prices):
    """逐月逐因子 IC"""
    print("\n" + "=" * 90)
    print("Part 1: 逐月逐因子 IC（哪個因子在衰退？）")
    print("=" * 90)

    df = feat.merge(prices[["stock_id", "date", "close"]], on=["stock_id", "date"], how="inner")
    df = df.sort_values(["stock_id", "date"])
    df["fwd_ret_20d"] = df.groupby("stock_id")["close"].transform(
        lambda x: x.shift(-21) / x.shift(-1) - 1
    )

    # neg 翻轉
    df["neg_ivol_20d"] = -df["ivol_20d"]
    df["neg_trust_net_buy"] = -df["trust_net_buy"]

    factors = {
        "roe": "ROE",
        "yield_rate": "殖利率",
        "pb_ratio": "股淨比",
        "revenue_yoy": "營收YoY",
        "rev_surprise": "營收驚喜",
        "rev_accel": "營收加速",
        "foreign_hold_chg_5d": "外資持股5d",
        "dealer_buy_20d": "自營商20d",
        "vol_ratio": "量比",
        "neg_ivol_20d": "低波動率",
        "neg_trust_net_buy": "反向投信",
    }

    dates = sorted(df["date"].unique())
    ic_records = []
    for d in dates:
        day = df[(df["date"] == d) & df["fwd_ret_20d"].notna()]
        if len(day) < 50:
            continue
        month = pd.Timestamp(d).to_period("M")
        for f in factors:
            valid = day[[f, "fwd_ret_20d"]].dropna()
            if len(valid) < 30:
                continue
            ic, _ = stats.spearmanr(valid[f], valid["fwd_ret_20d"])
            if not np.isnan(ic):
                ic_records.append({"date": d, "month": month, "factor": f, "ic": ic})

    ic_df = pd.DataFrame(ic_records)
    months = sorted(ic_df["month"].unique())

    # 表頭
    hdr = f"{'因子':<14s}"
    for m in months:
        hdr += f" {str(m):>8s}"
    hdr += "  趨勢"
    print(hdr)
    print("-" * (14 + 9 * len(months) + 6))

    for f, label in factors.items():
        row = f"{label:<12s}"
        fdata = ic_df[ic_df["factor"] == f]
        vals = []
        for m in months:
            mdata = fdata[fdata["month"] == m]
            if len(mdata) > 0:
                v = mdata["ic"].mean()
                vals.append(v)
                marker = "★" if v > 0.03 else ("✗" if v < -0.02 else " ")
                row += f" {v:>+.4f}{marker}"
            else:
                row += f"  {'---':>7s}"
                vals.append(np.nan)

        clean = [v for v in vals if not np.isnan(v)]
        if len(clean) >= 4:
            half = len(clean) // 2
            first_half = np.mean(clean[:half])
            second_half = np.mean(clean[half:])
            diff = second_half - first_half
            trend = "↑" if diff > 0.005 else ("↓" if diff < -0.005 else "→")
            row += f"  {trend} ({diff:+.3f})"
        print(row)

    # Composite IC
    print(f"\n--- Composite IC 逐月 ---")
    for m in months:
        mdata = ic_df[ic_df["month"] == m]
        daily_avg = mdata.groupby("date")["ic"].mean()
        n = len(daily_avg)
        ic_mean = daily_avg.mean()
        print(f"  {str(m):>8s}  IC={ic_mean:>+.4f}  n={n}")

    return ic_df


def part2_trimmed_alpha(signals, prices):
    """去極端值後的真實 alpha"""
    print("\n" + "=" * 90)
    print("Part 2: 去極端值後的真實 alpha")
    print("=" * 90)

    trading_days = sorted(prices["date"].unique())
    td_map = {d: i for i, d in enumerate(trading_days)}

    results = []
    for _, sig in signals.iterrows():
        sd = sig["signal_date"]
        if sd not in td_map:
            continue
        idx = td_map[sd]
        if idx + 20 >= len(trading_days):
            continue
        entry_date = trading_days[idx + 1]
        exit_date = trading_days[idx + 20]
        sp = prices[prices["stock_id"] == sig["stock_id"]]
        entry = sp[sp["date"] == entry_date]
        exit_ = sp[sp["date"] == exit_date]
        if entry.empty or exit_.empty:
            continue
        ret = exit_["close"].iloc[0] / entry["close"].iloc[0] - 1
        results.append({
            "signal_date": sd,
            "stock_id": sig["stock_id"],
            "stock_name": sig["stock_name"],
            "direction": sig["direction"],
            "wr": sig["weighted_win_rate"],
            "actual_return": ret,
            "entry_date": entry_date,
            "exit_date": exit_date,
        })

    df = pd.DataFrame(results)

    # 大盤
    mkt = prices.copy()
    mkt["ret20"] = mkt.groupby("stock_id")["close"].transform(lambda x: x.shift(-20) / x - 1)
    mkt_daily = mkt.groupby("date")["ret20"].mean().to_dict()

    # 每日 Top5
    dates = sorted(df["signal_date"].unique())
    daily = []
    for d in dates:
        day = df[df["signal_date"] == d]
        longs = day[day["direction"] == "long"].nlargest(5, "wr")
        shorts = day[day["direction"] == "short"].nlargest(5, "wr")
        if len(longs) == 0:
            continue

        entry_d = longs["entry_date"].iloc[0]
        mkt_r = mkt_daily.get(entry_d, 0)
        long_ret = longs["actual_return"].mean()
        short_ret = shorts["actual_return"].mean() if len(shorts) > 0 else np.nan
        excess = long_ret - mkt_r
        stocks = longs["stock_name"].tolist()

        daily.append({
            "date": d, "month": pd.Timestamp(d).to_period("M"),
            "long_ret": long_ret, "short_ret": short_ret,
            "mkt_ret": mkt_r, "excess": excess, "stocks": stocks,
        })

    dr = pd.DataFrame(daily)

    # 原始 vs Trimmed (去掉 >50% 的極端值)
    print(f"\n--- 做多 Top5 ---")
    raw = dr["excess"].dropna()
    trimmed = raw[raw.abs() < 0.5]  # 去掉 |excess| > 50%
    removed = len(raw) - len(trimmed)
    print(f"  原始:    alpha={raw.mean()*100:+.2f}%, 勝率={( raw>0).mean()*100:.1f}%, t={raw.mean()/(raw.std()/np.sqrt(len(raw))):.2f}, n={len(raw)}")
    print(f"  去極端值: alpha={trimmed.mean()*100:+.2f}%, 勝率={(trimmed>0).mean()*100:.1f}%, t={trimmed.mean()/(trimmed.std()/np.sqrt(len(trimmed))):.2f}, n={len(trimmed)} (移除{removed}筆)")

    # Winsorize (cap at 5th/95th percentile)
    lo, hi = raw.quantile(0.05), raw.quantile(0.95)
    winsorized = raw.clip(lo, hi)
    print(f"  Winsorize: alpha={winsorized.mean()*100:+.2f}%, t={winsorized.mean()/(winsorized.std()/np.sqrt(len(winsorized))):.2f}")

    # 月度分解
    print(f"\n--- 月度超額報酬 ---")
    print(f"  {'月份':>8s}  {'alpha':>8s}  {'勝率':>6s}  {'大盤':>8s}  {'做多':>8s}  n")
    print("  " + "-" * 55)
    for m, g in dr.groupby("month"):
        exc = g["excess"].mean() * 100
        wr = (g["excess"] > 0).mean() * 100
        mkt = g["mkt_ret"].mean() * 100
        lr = g["long_ret"].mean() * 100
        print(f"  {str(m):>8s}  {exc:>+7.2f}%  {wr:>5.0f}%  {mkt:>+7.2f}%  {lr:>+7.2f}%  {len(g)}")

    # 做空端
    print(f"\n--- 做空 Top5 ---")
    short_valid = dr["short_ret"].dropna()
    if len(short_valid) > 10:
        short_profit = -short_valid  # 做空利潤
        print(f"  做空利潤: {short_profit.mean()*100:+.2f}%, 勝率={(short_profit>0).mean()*100:.1f}%")
        print(f"\n  月度做空:")
        for m, g in dr.groupby("month"):
            sr = g["short_ret"].dropna()
            if len(sr) == 0:
                continue
            profit = -sr.mean() * 100
            wr = (sr < 0).mean() * 100
            print(f"    {str(m):>8s}  做空利潤={profit:>+7.2f}%  做空勝率={wr:>5.0f}%  n={len(sr)}")

    return dr


def part3_recent_vs_strong(dr):
    """近期 vs 強勢期的推薦差異"""
    print("\n" + "=" * 90)
    print("Part 3: 近期 vs 強勢期")
    print("=" * 90)

    # 分成三期
    strong = dr[(dr["month"] >= "2025-09") & (dr["month"] <= "2025-12")]
    mid = dr[(dr["month"] >= "2026-01") & (dr["month"] <= "2026-01")]
    weak = dr[dr["month"] >= "2026-02"]

    for label, subset in [("強勢期 9-12月", strong), ("1月", mid), ("弱勢期 2-3月", weak)]:
        if len(subset) == 0:
            continue
        exc = subset["excess"]
        mkt = subset["mkt_ret"]
        lr = subset["long_ret"]
        print(f"\n  {label} ({len(subset)} 天):")
        print(f"    alpha={exc.mean()*100:+.2f}%, 勝率={(exc>0).mean()*100:.0f}%")
        print(f"    大盤={mkt.mean()*100:+.2f}%, 做多報酬={lr.mean()*100:+.2f}%")

        # 統計常出現的股票
        all_stocks = []
        for sl in subset["stocks"]:
            all_stocks.extend(sl)
        from collections import Counter
        top = Counter(all_stocks).most_common(10)
        print(f"    常推股票: {', '.join(f'{s}({c})' for s, c in top[:8])}")


def main():
    feat, prices, signals = load_data()
    ic_df = part1_factor_ic_by_month(feat, prices)
    dr = part2_trimmed_alpha(signals, prices)
    part3_recent_vs_strong(dr)

    print("\n" + "=" * 90)
    print("診斷完成！")
    print("=" * 90)


if __name__ == "__main__":
    main()

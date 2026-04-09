"""
月底-月初 Timing 效應 OOS 驗證

之前 Track F 發現：月底 3 日超額 +4.54%(p=0.052)，月初 3 日 +1.89%(p=0.011)
本研究做更嚴謹的驗證：
  1. 分年度 OOS 穩定性
  2. 月底/月初的精確定義（最後 N 交易日 vs 前 N 交易日）
  3. 與模型 Top 推薦的交互：Timing + 選股是否加乘？
  4. 不同 N（1d/2d/3d/5d）的效果比較
  5. 可操作性分析：進出場時點
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


def load_data() -> pd.DataFrame:
    sql = text("""
        SELECT stock_id, date, close, volume
        FROM stock_prices
        WHERE date >= '2023-01-01' AND close > 0
        ORDER BY stock_id, date
    """)
    df = pd.read_sql(sql, engine)
    df["date"] = pd.to_datetime(df["date"])

    # 流動性過濾
    grp = df.groupby("stock_id")
    df["vol_ma20"] = grp["volume"].transform(lambda x: x.rolling(20, min_periods=5).mean())
    df = df[df["vol_ma20"] >= 500_000].copy()
    df = df[df["stock_id"].str.match(r"^[1-9]\d{3}$")].copy()

    # 日報酬
    df["daily_ret"] = df.groupby("stock_id")["close"].pct_change()

    # Forward returns
    grp = df.groupby("stock_id")
    for h in [1, 2, 3, 5]:
        entry = grp["close"].shift(-1)
        exit_ = grp["close"].shift(-(1 + h))
        df[f"fwd_{h}d"] = (exit_ - entry) / entry

    print(f"[Data] {len(df):,} 筆，{df['stock_id'].nunique()} 檔")
    return df


def assign_month_position(df: pd.DataFrame) -> pd.DataFrame:
    """標記每個交易日在月內的位置"""
    # 取得每月的交易日列表
    trading_dates = sorted(df["date"].unique())
    date_info = pd.DataFrame({"date": trading_dates})
    date_info["ym"] = date_info["date"].dt.to_period("M")

    # 計算月內位置
    date_info["day_in_month"] = date_info.groupby("ym").cumcount() + 1
    date_info["days_in_month"] = date_info.groupby("ym")["date"].transform("count")
    date_info["days_from_end"] = date_info["days_in_month"] - date_info["day_in_month"]

    df = df.merge(date_info[["date", "day_in_month", "days_in_month", "days_from_end"]],
                  on="date", how="left")
    return df


def _ttest(arr: np.ndarray):
    if len(arr) < 10:
        return np.nan, np.nan
    t, p = stats.ttest_1samp(arr, 0)
    return float(t), float(p)


def _stars(p: float) -> str:
    if np.isnan(p):
        return ""
    return "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else ""


# ═══════════════════════════════════════════════════════════════════
# 1. 月位置 vs 報酬：完整分析
# ═══════════════════════════════════════════════════════════════════
def test_month_position(df: pd.DataFrame) -> None:
    print(f"\n{'='*90}")
    print(f"  1. 月內位置 vs 報酬（全體股票每日截面中位數報酬）")
    print(f"{'='*90}")

    # 每日全市場中位數報酬
    daily_mkt = df.groupby("date").agg(
        median_ret=("daily_ret", "median"),
        day_in_month=("day_in_month", "first"),
        days_from_end=("days_from_end", "first"),
    ).reset_index()

    # 月末 N 交易日 vs 其他
    for n in [1, 2, 3, 5]:
        end_days = daily_mkt[daily_mkt["days_from_end"] < n]["median_ret"].dropna().values
        start_days = daily_mkt[daily_mkt["day_in_month"] <= n]["median_ret"].dropna().values
        mid_days = daily_mkt[
            (daily_mkt["day_in_month"] > n) & (daily_mkt["days_from_end"] >= n)
        ]["median_ret"].dropna().values

        end_mean = np.mean(end_days) * 100
        start_mean = np.mean(start_days) * 100
        mid_mean = np.mean(mid_days) * 100

        _, p_end = _ttest(end_days - np.mean(mid_days))
        _, p_start = _ttest(start_days - np.mean(mid_days))

        print(f"\n  N={n} 交易日:")
        print(f"    月末{n}日: {end_mean:+.4f}%/日  (N={len(end_days)})  "
              f"vs 月中: {mid_mean:+.4f}%  差異={end_mean-mid_mean:+.4f}%  "
              f"p={p_end:.4f} {_stars(p_end)}")
        print(f"    月初{n}日: {start_mean:+.4f}%/日  (N={len(start_days)})  "
              f"vs 月中: {mid_mean:+.4f}%  差異={start_mean-mid_mean:+.4f}%  "
              f"p={p_start:.4f} {_stars(p_start)}")


# ═══════════════════════════════════════════════════════════════════
# 2. 分年度 OOS
# ═══════════════════════════════════════════════════════════════════
def test_yearly_oos(df: pd.DataFrame) -> None:
    print(f"\n{'='*90}")
    print(f"  2. 分年度 OOS：月末/月初 3 日 vs 月中（每日中位數報酬 %）")
    print(f"{'='*90}")

    daily_mkt = df.groupby("date").agg(
        median_ret=("daily_ret", "median"),
        day_in_month=("day_in_month", "first"),
        days_from_end=("days_from_end", "first"),
    ).reset_index()
    daily_mkt["year"] = daily_mkt["date"].dt.year

    n = 3
    daily_mkt["pos"] = "中"
    daily_mkt.loc[daily_mkt["days_from_end"] < n, "pos"] = "末"
    daily_mkt.loc[daily_mkt["day_in_month"] <= n, "pos"] = "初"

    years = sorted(daily_mkt["year"].unique())
    print(f"\n  {'年度':>6s}  {'月末3日':>10s}  {'月初3日':>10s}  {'月中':>10s}  "
          f"{'末-中':>10s}  {'初-中':>10s}")
    print(f"  {'-'*65}")

    for yr in years:
        yd = daily_mkt[daily_mkt["year"] == yr]
        end_m = yd[yd["pos"] == "末"]["median_ret"].mean() * 100
        start_m = yd[yd["pos"] == "初"]["median_ret"].mean() * 100
        mid_m = yd[yd["pos"] == "中"]["median_ret"].mean() * 100
        print(f"  {yr:>6}  {end_m:>+10.4f}%  {start_m:>+10.4f}%  {mid_m:>+10.4f}%  "
              f"{end_m-mid_m:>+10.4f}%  {start_m-mid_m:>+10.4f}%")

    # 全期
    end_all = daily_mkt[daily_mkt["pos"] == "末"]["median_ret"].mean() * 100
    start_all = daily_mkt[daily_mkt["pos"] == "初"]["median_ret"].mean() * 100
    mid_all = daily_mkt[daily_mkt["pos"] == "中"]["median_ret"].mean() * 100
    print(f"  {'全期':>6s}  {end_all:>+10.4f}%  {start_all:>+10.4f}%  {mid_all:>+10.4f}%  "
          f"{end_all-mid_all:>+10.4f}%  {start_all-mid_all:>+10.4f}%")


# ═══════════════════════════════════════════════════════════════════
# 3. 累積報酬比較：月末進場 vs 任意日進場
# ═══════════════════════════════════════════════════════════════════
def test_entry_timing(df: pd.DataFrame) -> None:
    print(f"\n{'='*90}")
    print(f"  3. 進場時點：月末 3 日 vs 月中 vs 月初 3 日 進場後 1d/2d/3d/5d 報酬")
    print(f"     （個股截面中位數）")
    print(f"{'='*90}")

    n = 3
    positions = {
        "月末3日": df[df["days_from_end"] < n],
        "月初3日": df[df["day_in_month"] <= n],
        "月中": df[(df["day_in_month"] > n) & (df["days_from_end"] >= n)],
    }

    print(f"\n  {'位置':<10s}", end="")
    for h in [1, 2, 3, 5]:
        print(f"  {'fwd_'+str(h)+'d':>12s}", end="")
    print(f"  {'N':>10s}")
    print(f"  {'-'*65}")

    for label, subset in positions.items():
        print(f"  {label:<10s}", end="")
        for h in [1, 2, 3, 5]:
            # 每日截面中位數的均值
            daily_med = subset.groupby("date")[f"fwd_{h}d"].median()
            m = daily_med.mean() * 100
            _, p = _ttest(daily_med.dropna().values)
            print(f"  {m:>+10.4f}%{_stars(p):2s}", end="")
        print(f"  {len(subset):>10,}")

    # 差異檢定
    print(f"\n  差異檢定（月末 - 月中）:")
    for h in [1, 2, 3, 5]:
        end_daily = positions["月末3日"].groupby("date")[f"fwd_{h}d"].median().dropna()
        mid_daily = positions["月中"].groupby("date")[f"fwd_{h}d"].median().dropna()
        # 直接比較均值
        diff = end_daily.mean() - mid_daily.mean()
        t, p = stats.ttest_ind(end_daily.values, mid_daily.values, equal_var=False)
        print(f"    fwd_{h}d: 差異={diff*100:+.4f}%  t={t:.2f}  p={p:.4f} {_stars(p)}")


# ═══════════════════════════════════════════════════════════════════
# 4. 月末效應 × 星期幾
# ═══════════════════════════════════════════════════════════════════
def test_weekday_interaction(df: pd.DataFrame) -> None:
    print(f"\n{'='*90}")
    print(f"  4. 月末效應 × 星期幾")
    print(f"{'='*90}")

    df["weekday"] = df["date"].dt.day_name()
    n = 3
    end_data = df[df["days_from_end"] < n]

    daily_med = end_data.groupby(["date", "weekday"])["daily_ret"].median().reset_index()

    weekday_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    for wd in weekday_order:
        wd_data = daily_med[daily_med["weekday"] == wd]["daily_ret"].dropna().values
        if len(wd_data) < 10:
            continue
        m = np.mean(wd_data) * 100
        _, p = _ttest(wd_data)
        print(f"  月末3日 × {wd:10s}: {m:+.4f}%/日  N={len(wd_data)}  "
              f"p={p:.4f} {_stars(p)}")


# ═══════════════════════════════════════════════════════════════════
# 5. 月份效應
# ═══════════════════════════════════════════════════════════════════
def test_monthly_seasonality(df: pd.DataFrame) -> None:
    print(f"\n{'='*90}")
    print(f"  5. 月份效應（全體月報酬中位數）")
    print(f"{'='*90}")

    # 每月報酬：每支股票每月的報酬
    df["ym"] = df["date"].dt.to_period("M")
    df["month"] = df["date"].dt.month

    monthly = df.groupby(["stock_id", "ym"]).agg(
        month_ret=("daily_ret", lambda x: (1 + x).prod() - 1),
        month=("month", "first"),
    ).reset_index()

    # 每月截面中位數
    monthly_med = monthly.groupby("ym").agg(
        median_ret=("month_ret", "median"),
        month=("month", "first"),
    ).reset_index()

    overall = monthly_med["median_ret"].mean()

    print(f"\n  {'月份':>6s}  {'月報酬中位數':>14s}  {'vs全期':>10s}  {'N月':>6s}  {'p值':>8s}")
    print(f"  {'-'*55}")

    for m in range(1, 13):
        m_data = monthly_med[monthly_med["month"] == m]["median_ret"].dropna().values
        if len(m_data) < 2:
            continue
        m_mean = np.mean(m_data) * 100
        diff = (np.mean(m_data) - overall) * 100
        _, p = _ttest(m_data - overall)
        print(f"  {m:>4d}月  {m_mean:>+14.3f}%  {diff:>+10.3f}%  {len(m_data):>6}  "
              f"{p:>8.4f} {_stars(p)}")

    df.drop(columns=["ym", "month"], inplace=True)


# ═══════════════════════════════════════════════════════════════════
# 6. 可操作性分析
# ═══════════════════════════════════════════════════════════════════
def test_actionability(df: pd.DataFrame) -> None:
    print(f"\n{'='*90}")
    print(f"  6. 可操作性分析：月末買入 + 月初賣出策略")
    print(f"     模擬：月末倒數第 3 日收盤買入，月初第 3 日收盤賣出")
    print(f"{'='*90}")

    # 標記月末倒數第 3 日為 entry，月初第 3 日為 exit
    df["ym"] = df["date"].dt.to_period("M")

    # 取每月的交易日，找倒數第 3 日和下月第 3 日
    trading_dates = sorted(df["date"].unique())
    date_df = pd.DataFrame({"date": trading_dates})
    date_df["ym"] = date_df["date"].dt.to_period("M")
    date_df["day_in_month"] = date_df.groupby("ym").cumcount() + 1
    date_df["days_in_month"] = date_df.groupby("ym")["date"].transform("count")
    date_df["days_from_end"] = date_df["days_in_month"] - date_df["day_in_month"]

    # 入場日：每月倒數第 3 交易日
    entry_dates = date_df[date_df["days_from_end"] == 2]["date"].tolist()
    # 出場日：每月第 3 交易日
    exit_dates = date_df[date_df["day_in_month"] == 3]["date"].tolist()

    # 配對：入場月 M 的倒數第 3 日 → 出場 M+1 月的第 3 日
    trades = []
    for entry_d in entry_dates:
        entry_ym = entry_d.to_period("M")
        next_ym = entry_ym + 1
        exits = [d for d in exit_dates if d.to_period("M") == next_ym]
        if exits:
            trades.append((entry_d, exits[0]))

    if not trades:
        print("  (無法配對交易)")
        df.drop(columns=["ym"], inplace=True)
        return

    # 計算每筆交易的市場中位數報酬
    results = []
    for entry_d, exit_d in trades:
        entry_prices = df[df["date"] == entry_d].set_index("stock_id")["close"]
        exit_prices = df[df["date"] == exit_d].set_index("stock_id")["close"]
        common = entry_prices.index.intersection(exit_prices.index)
        if len(common) < 100:
            continue
        rets = (exit_prices[common] - entry_prices[common]) / entry_prices[common]
        results.append({
            "entry": entry_d,
            "exit": exit_d,
            "hold_days": (exit_d - entry_d).days,
            "median_ret": rets.median(),
            "mean_ret": rets.mean(),
            "win_rate": (rets > 0).mean(),
        })

    if not results:
        print("  (無有效交易)")
        df.drop(columns=["ym"], inplace=True)
        return

    res_df = pd.DataFrame(results)
    res_df["year"] = res_df["entry"].dt.year

    print(f"\n  共 {len(res_df)} 筆月末→月初交易")
    print(f"\n  {'年度':>6s}  {'交易數':>6s}  {'中位數報酬':>12s}  {'勝率':>8s}")
    print(f"  {'-'*40}")

    for yr in sorted(res_df["year"].unique()):
        yr_data = res_df[res_df["year"] == yr]
        m = yr_data["median_ret"].mean() * 100
        wr = yr_data["win_rate"].mean() * 100
        print(f"  {yr:>6}  {len(yr_data):>6}  {m:>+12.3f}%  {wr:>7.1f}%")

    overall_m = res_df["median_ret"].mean() * 100
    overall_wr = res_df["win_rate"].mean() * 100
    _, p = _ttest(res_df["median_ret"].values)
    print(f"  {'全期':>6s}  {len(res_df):>6}  {overall_m:>+12.3f}%  {overall_wr:>7.1f}%  "
          f"p={p:.4f} {_stars(p)}")

    # 對比：隨機 5 日持有的報酬
    random_5d_med = df.groupby("date")["fwd_5d"].median().dropna()
    rand_mean = random_5d_med.mean() * 100
    print(f"\n  對比：任意日買入持有 5d 的中位數報酬: {rand_mean:+.3f}%")
    print(f"  月末策略超額: {overall_m - rand_mean:+.3f}%")

    df.drop(columns=["ym"], inplace=True)


def main() -> None:
    print("=" * 90)
    print("  月底-月初 Timing 效應 OOS 驗證")
    print("=" * 90)

    df = load_data()
    df = assign_month_position(df)

    test_month_position(df)
    test_yearly_oos(df)
    test_entry_timing(df)
    test_weekday_interaction(df)
    test_monthly_seasonality(df)
    test_actionability(df)

    print(f"\n{'='*90}")
    print(f"  研究完成")
    print(f"{'='*90}")


if __name__ == "__main__":
    main()

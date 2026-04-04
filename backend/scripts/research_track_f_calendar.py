"""
Track F: 日曆效應與季節性因子篩選
假說：台股有已知的季節性模式，可能產生可預測的超額報酬。
候選因子/效應：
  1. turn_of_month   — 月初效應（每月前 3 個交易日 vs 其他日）
  2. month_effect     — 特定月份效應（哪些月份歷史上表現好）
  3. pre_revenue      — 營收公布前效應（10 號前 vs 10 號後）
  4. quarter_end      — 季末效應（機構作帳）
  5. day_of_week      — 星期效應（週一 vs 週五）
  6. post_holiday     — 長假後效應
  7. earnings_season  — 財報季效應（3/5/8/11 月）
  8. dividend_season  — 除息旺季效應（7-9 月）

方法：不用因子 IC，改用事件研究法：
  - 在特定日曆條件下，持有 20d 的平均報酬 vs 非條件日的報酬
  - Bootstrap 檢定顯著性
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
HOLD = 20


def load_data() -> pd.DataFrame:
    print("載入 stock_prices ...", flush=True)
    sql = text("""
        SELECT stock_id, date, close
        FROM stock_prices
        WHERE date >= '2023-03-01' AND close > 0
        ORDER BY stock_id, date
    """)
    df = pd.read_sql(sql, engine)
    df["date"] = pd.to_datetime(df["date"])

    # Forward return
    df = df.sort_values(["stock_id", "date"])
    g = df.groupby("stock_id")
    df["exit"] = g["close"].shift(-HOLD)
    df["fwd_ret"] = (df["exit"] - df["close"]) / df["close"]

    # 日曆欄位
    df["year"] = df["date"].dt.year
    df["month"] = df["date"].dt.month
    df["day"] = df["date"].dt.day
    df["dow"] = df["date"].dt.dayofweek  # 0=Mon, 4=Fri
    df["quarter"] = df["date"].dt.quarter

    # 每月第幾個交易日
    df["td_of_month"] = df.groupby(["stock_id", df["date"].dt.to_period("M")]).cumcount() + 1
    # 每月倒數第幾個交易日
    month_sizes = df.groupby(["stock_id", df["date"].dt.to_period("M")])["date"].transform("count")
    df["td_from_end"] = month_sizes - df["td_of_month"] + 1

    print(f"  載入 {len(df):,} 筆 ({df['stock_id'].nunique()} 檔)")
    return df


def test_calendar_effect(
    df: pd.DataFrame,
    name: str,
    condition_col: str,
    condition_val,
    baseline_desc: str = "其他日",
) -> dict | None:
    """事件研究法：比較條件日 vs 非條件日的 20d 報酬"""
    valid = df.dropna(subset=["fwd_ret"])

    if isinstance(condition_val, list):
        cond_mask = valid[condition_col].isin(condition_val)
    else:
        cond_mask = valid[condition_col] == condition_val

    cond_ret = valid.loc[cond_mask, "fwd_ret"]
    base_ret = valid.loc[~cond_mask, "fwd_ret"]

    if len(cond_ret) < 100 or len(base_ret) < 100:
        return None

    # 用每日截面中位數避免大股票主導
    cond_daily = valid.loc[cond_mask].groupby("date")["fwd_ret"].median()
    base_daily = valid.loc[~cond_mask].groupby("date")["fwd_ret"].median()

    mean_cond = cond_daily.mean()
    mean_base = base_daily.mean()
    diff = mean_cond - mean_base

    # Welch's t-test on daily medians
    t_stat, p_val = stats.ttest_ind(cond_daily, base_daily, equal_var=False)

    return {
        "name": name,
        "n_cond_days": len(cond_daily),
        "n_base_days": len(base_daily),
        "cond_ret": mean_cond * 100,
        "base_ret": mean_base * 100,
        "diff": diff * 100,
        "t_stat": t_stat,
        "p_val": p_val,
        "baseline_desc": baseline_desc,
    }


def run_research(df: pd.DataFrame) -> None:
    print(f"\n{'=' * 110}")
    print("  Track F: 日曆效應與季節性研究")
    print(f"{'=' * 110}")

    results = []

    # ── 1. 月初效應（前 3 個交易日）──
    df["is_turn_of_month"] = df["td_of_month"] <= 3
    r = test_calendar_effect(df, "月初前3日", "is_turn_of_month", True)
    if r:
        results.append(r)

    # 月底效應（倒數 3 個交易日）
    df["is_month_end"] = df["td_from_end"] <= 3
    r = test_calendar_effect(df, "月底後3日", "is_month_end", True)
    if r:
        results.append(r)

    # ── 2. 月份效應 ──
    for m in range(1, 13):
        r = test_calendar_effect(df, f"{m}月", "month", m, f"非{m}月")
        if r:
            results.append(r)

    # ── 3. 營收公布前效應（1~10 號 vs 11~31 號）──
    df["pre_revenue"] = df["day"] <= 10
    r = test_calendar_effect(df, "營收公布前(1-10號)", "pre_revenue", True, "11-31號")
    if r:
        results.append(r)

    # ── 4. 季末效應（3/6/9/12 月）──
    df["is_quarter_end_month"] = df["month"].isin([3, 6, 9, 12])
    r = test_calendar_effect(df, "季末月", "is_quarter_end_month", True, "非季末月")
    if r:
        results.append(r)

    # ── 5. 星期效應 ──
    dow_names = {0: "一", 1: "二", 2: "三", 3: "四", 4: "五"}
    for d in range(5):
        r = test_calendar_effect(df, f"週{dow_names[d]}", "dow", d, f"非週{dow_names[d]}")
        if r:
            results.append(r)

    # ── 6. 財報季效應（3/5/8/11 月）──
    df["is_earnings_season"] = df["month"].isin([3, 5, 8, 11])
    r = test_calendar_effect(df, "財報季(3/5/8/11月)", "is_earnings_season", True, "非財報季")
    if r:
        results.append(r)

    # ── 7. 除息旺季（7-9 月）──
    df["is_div_season"] = df["month"].isin([7, 8, 9])
    r = test_calendar_effect(df, "除息旺季(7-9月)", "is_div_season", True, "非除息旺季")
    if r:
        results.append(r)

    # ── 8. 年初效應（1 月）vs 年末效應（12 月）──
    # Already covered in month_effect

    # ── 結果表 ──
    print(
        f"\n  {'效應':>25} {'條件日':>6} {'基準日':>6}"
        f" {'條件ret':>8} {'基準ret':>8} {'差異':>8} {'t值':>7} {'p值':>7} {'判定':>6}"
    )
    print("  " + "─" * 100)

    for r in sorted(results, key=lambda x: -abs(x["diff"])):
        sig = "★★★" if r["p_val"] < 0.01 else \
              "★★" if r["p_val"] < 0.05 else \
              "★" if r["p_val"] < 0.10 else "—"
        print(
            f"  {r['name']:>25} {r['n_cond_days']:>6} {r['n_base_days']:>6}"
            f" {r['cond_ret']:>+7.2f}% {r['base_ret']:>+7.2f}%"
            f" {r['diff']:>+7.2f}% {r['t_stat']:>+6.2f} {r['p_val']:>7.4f} {sig:>6}"
        )

    # ── 顯著效應詳細分析 ──
    significant = [r for r in results if r["p_val"] < 0.10]
    if significant:
        print(f"\n  ── 顯著效應（p < 0.10）──")
        for r in sorted(significant, key=lambda x: x["p_val"]):
            print(f"    {r['name']}: 條件日報酬 {r['cond_ret']:+.2f}% vs {r['baseline_desc']} {r['base_ret']:+.2f}%"
                  f" (差 {r['diff']:+.2f}%, t={r['t_stat']:+.2f}, p={r['p_val']:.4f})")

    # ── 月份效應 heatmap ──
    print(f"\n  ── 月份報酬 heatmap（20d 中位數報酬 %）──")
    valid = df.dropna(subset=["fwd_ret"])
    monthly_daily_median = valid.groupby(["date", "month"])["fwd_ret"].median().reset_index()
    month_avg = monthly_daily_median.groupby("month")["fwd_ret"].mean() * 100

    overall_avg = month_avg.mean()
    for m in range(1, 13):
        ret = month_avg.get(m, 0)
        delta = ret - overall_avg
        bar = "+" * int(max(0, delta * 20)) if delta > 0 else "-" * int(max(0, -delta * 20))
        print(f"    {m:>2}月: {ret:>+6.2f}% (Δ{delta:>+5.2f}%) |{bar}")

    # ── 星期效應 ──
    print(f"\n  ── 星期效應（20d 中位數報酬 %）──")
    dow_daily_median = valid.groupby(["date", "dow"])["fwd_ret"].median().reset_index()
    dow_avg = dow_daily_median.groupby("dow")["fwd_ret"].mean() * 100

    overall_avg = dow_avg.mean()
    for d in range(5):
        ret = dow_avg.get(d, 0)
        delta = ret - overall_avg
        bar = "+" * int(max(0, delta * 30)) if delta > 0 else "-" * int(max(0, -delta * 30))
        print(f"    週{dow_names[d]}: {ret:>+6.2f}% (Δ{delta:>+5.2f}%) |{bar}")

    print(f"\n{'=' * 110}")
    print("  Track F 完成")
    print(f"{'=' * 110}\n")


if __name__ == "__main__":
    df = load_data()
    run_research(df)

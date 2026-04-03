"""
研究：營收驚喜因子 IC 分析
從現有 stock_revenue_history 計算衍生因子，測試預測力

因子候選：
1. rev_surprise: 實際營收 vs 近3個月平均（驚喜程度）
2. rev_accel: 營收加速度（本月YoY - 上月YoY）
3. rev_mom_3m: 近3個月營收動量（vs 前3個月）
4. rev_beat_streak: 連續幾個月 YoY > 0
5. rev_yoy: 原始年增率（baseline，已在模型中）
"""
from __future__ import annotations
import os, warnings
import numpy as np
import pandas as pd
from scipy import stats
from sqlalchemy import create_engine, text

warnings.filterwarnings("ignore")
PG_URL = os.getenv("PG_URL", "postgresql://alphaforge:alphaforge_secret@10.0.4.3:5433/alphaforge")
engine = create_engine(PG_URL)


def load_revenue() -> pd.DataFrame:
    sql = text("""
        SELECT stock_id, year, month, revenue, revenue_yoy, revenue_mom
        FROM stock_revenue_history
        WHERE revenue > 0
        ORDER BY stock_id, year, month
    """)
    df = pd.read_sql(sql, engine)
    # 建立日期欄（用每月10日，因為營收最晚10號公布）
    df["announce_date"] = pd.to_datetime(
        df["year"].astype(str) + "-" + df["month"].astype(str).str.zfill(2) + "-10"
    )
    df = df.sort_values(["stock_id", "announce_date"])
    return df


def compute_revenue_factors(rev: pd.DataFrame) -> pd.DataFrame:
    """計算營收衍生因子"""
    g = rev.groupby("stock_id")

    # 1. rev_surprise: 實際營收 vs 近3個月移動平均（%偏差）
    rev["rev_ma3"] = g["revenue"].transform(lambda x: x.rolling(3, min_periods=2).mean().shift(1))
    rev["rev_surprise"] = (rev["revenue"] - rev["rev_ma3"]) / rev["rev_ma3"] * 100

    # 2. rev_accel: 營收加速度（本月YoY - 上月YoY）
    rev["rev_accel"] = g["revenue_yoy"].diff()

    # 3. rev_mom_3m: 近3月平均營收 vs 前3月平均營收
    rev["rev_sum3"] = g["revenue"].transform(lambda x: x.rolling(3, min_periods=2).sum())
    rev["rev_sum3_prev"] = g["rev_sum3"].shift(3)
    rev["rev_mom_3m"] = (rev["rev_sum3"] - rev["rev_sum3_prev"]) / rev["rev_sum3_prev"] * 100

    # 4. rev_beat_streak: 連續幾個月 YoY > 0
    def streak(s):
        result = []
        count = 0
        for v in s:
            if v is not None and v > 0:
                count += 1
            else:
                count = 0
            result.append(count)
        return result
    rev["rev_beat_streak"] = g["revenue_yoy"].transform(streak)

    # 5. rev_yoy: 原始（baseline）
    # 已有

    return rev


def load_prices() -> pd.DataFrame:
    sql = text("""
        SELECT stock_id, date, close
        FROM stock_features
        WHERE close > 0 AND date >= '2023-06-01'
        ORDER BY stock_id, date
    """)
    df = pd.read_sql(sql, engine)
    df["date"] = pd.to_datetime(df["date"])
    return df


def merge_and_test(rev: pd.DataFrame, prices: pd.DataFrame):
    """將營收因子 merge 到每日價格，計算 IC"""

    # 營收因子 forward fill 到每日（營收公布後生效直到下次公布）
    rev_factors = rev[["stock_id", "announce_date", "rev_surprise", "rev_accel",
                        "rev_mom_3m", "rev_beat_streak", "revenue_yoy"]].copy()
    rev_factors = rev_factors.rename(columns={"announce_date": "date"})

    # merge_asof: 每個交易日配對最近一次營收公布
    prices = prices.sort_values(["stock_id", "date"])
    rev_factors = rev_factors.sort_values(["stock_id", "date"])

    merged_parts = []
    for sid, grp_p in prices.groupby("stock_id"):
        grp_r = rev_factors[rev_factors["stock_id"] == sid]
        if grp_r.empty:
            continue
        m = pd.merge_asof(grp_p, grp_r.drop(columns=["stock_id"]),
                          on="date", direction="backward")
        merged_parts.append(m)

    if not merged_parts:
        print("No data after merge")
        return

    df = pd.concat(merged_parts, ignore_index=True)
    df = df.sort_values(["stock_id", "date"])

    # 計算 20d forward return (gap=1)
    df["entry"] = df.groupby("stock_id")["close"].shift(-1)
    df["exit"] = df.groupby("stock_id")["close"].shift(-21)
    df["fwd_20d"] = (df["exit"] - df["entry"]) / df["entry"]

    # 過濾有效資料
    df = df.dropna(subset=["fwd_20d"])

    factors = ["rev_surprise", "rev_accel", "rev_mom_3m", "rev_beat_streak", "revenue_yoy"]

    print(f"\n[Data] {len(df):,} 筆，{df['date'].min().date()} ~ {df['date'].max().date()}")
    print(f"[Coverage] " + ", ".join(f"{f}: {df[f].notna().mean():.0%}" for f in factors))

    # 每因子做 rank + IC
    for f in factors:
        df[f"{f}_rank"] = df.groupby("date")[f].rank(pct=True, na_option="keep")

    # 按季計算 IC
    df["quarter"] = df["date"].dt.to_period("Q")
    quarters = sorted(df["quarter"].unique())

    print(f"\n{'=' * 90}")
    print(f"  營收衍生因子 IC 分析（20d forward return, gap=1）")
    print(f"{'=' * 90}")
    print(f"\n  {'因子':>18} {'avgIC':>7} {'|IC|':>6} {'正比':>5}", end="")
    for q in quarters:
        print(f" {str(q):>8}", end="")
    print()
    print("  " + "─" * (38 + 9 * len(quarters)))

    summary = []
    for f in factors:
        rc = f"{f}_rank"
        q_ics = []
        for q in quarters:
            qdf = df[df["quarter"] == q]
            daily_ics = []
            for _, grp in qdf.groupby("date"):
                if len(grp) < 50:
                    continue
                vals = grp[rc].values
                rets = grp["fwd_20d"].values
                valid = (~np.isnan(vals)) & (~np.isnan(rets))
                if valid.sum() < 30:
                    continue
                ic, _ = stats.spearmanr(vals[valid], rets[valid])
                if not np.isnan(ic):
                    daily_ics.append(ic)
            q_ics.append(np.mean(daily_ics) if daily_ics else np.nan)

        valid_ics = [x for x in q_ics if not np.isnan(x)]
        if not valid_ics:
            continue

        avg_ic = np.mean(valid_ics)
        abs_ic = abs(avg_ic)
        pos_ratio = sum(1 for x in valid_ics if x > 0) / len(valid_ics)

        if abs_ic > 0.005 and pos_ratio >= 0.6:
            mark = " ★"
        elif abs_ic > 0.005 and pos_ratio <= 0.4:
            mark = " ◆"
        else:
            mark = "  "

        print(f"  {f:>18} {avg_ic:>+7.4f} {abs_ic:>6.4f} {pos_ratio:>4.0%}", end="")
        for ic in q_ics:
            if np.isnan(ic):
                print(f" {'---':>8}", end="")
            else:
                print(f" {ic:>+8.4f}", end="")
        print(mark)

        summary.append({"factor": f, "avg_ic": avg_ic, "pos_ratio": pos_ratio, "n_q": len(valid_ics)})

    # 和現有 revenue_yoy 比較
    print(f"\n  === 和現有 revenue_yoy（已在模型中）比較 ===")
    sdf = pd.DataFrame(summary)
    baseline = sdf[sdf["factor"] == "revenue_yoy"]
    if not baseline.empty:
        bl_ic = baseline.iloc[0]["avg_ic"]
        bl_pos = baseline.iloc[0]["pos_ratio"]
        for _, row in sdf.iterrows():
            if row["factor"] == "revenue_yoy":
                continue
            delta_ic = row["avg_ic"] - bl_ic
            print(f"  {row['factor']:>18}: IC {row['avg_ic']:+.4f} (vs baseline {bl_ic:+.4f}, "
                  f"Δ={delta_ic:+.4f}), 正比 {row['pos_ratio']:.0%}")

    # 判定
    print(f"\n  === 結論 ===")
    useful = [r for r in summary if r["factor"] != "revenue_yoy"
              and abs(r["avg_ic"]) > 0.005 and r["pos_ratio"] >= 0.6]
    if useful:
        names = ", ".join(r["factor"] for r in useful)
        print(f"  ★ 有效新因子: {names}")
        print(f"  建議加入模型訓練")
    else:
        print(f"  ✗ 沒有營收衍生因子比現有 revenue_yoy 明顯更好")
        print(f"  不建議更動")


def main():
    print("Loading revenue data...")
    rev = load_revenue()
    print(f"  {len(rev):,} 筆營收記錄")

    rev = compute_revenue_factors(rev)

    print("Loading price data...")
    prices = load_prices()
    print(f"  {len(prices):,} 筆價格記錄")

    merge_and_test(rev, prices)


if __name__ == "__main__":
    main()

"""
因子 IC 穩定性分析 — 按維度拆解（5d / 10d / 20d baseline）
目標：找出 5d 和 10d 各自有效的因子，而非套用 20d 的 15 因子
"""
from __future__ import annotations

import os
import warnings

import numpy as np
import pandas as pd
from scipy import stats
from sqlalchemy import create_engine, text

warnings.filterwarnings("ignore")

PG_URL = os.getenv("PG_URL", "postgresql://alphaforge:alphaforge_secret@10.0.4.3:5433/alphaforge")
engine = create_engine(PG_URL)

# 全量因子（DB 裡所有可能有用的）
RAW_FACTORS = [
    # 技術面
    "rsi14", "rsi2", "k", "d", "macd_dif", "macd_osc",
    "bias5", "bias10", "bias20", "bb_pctb", "vol_ratio",
    "price_vs_high20", "ma_trend", "sector_rs",
    "atr_pct",
    # 基本面
    "roe", "yield_rate", "pb_ratio", "revenue_yoy",
    # 籌碼面 — 原始
    "foreign_net_buy", "foreign_buy_5d", "foreign_buy_10d", "foreign_buy_20d",
    "trust_net_buy", "trust_buy_5d", "trust_buy_10d", "trust_buy_20d",
    "dealer_net_buy", "dealer_buy_5d", "dealer_buy_10d", "dealer_buy_20d",
    "margin_chg_5d",
    "foreign_hold_pct", "foreign_hold_chg_5d",
    "etf_net_flow_5d",
    # 市場
    "market_breadth", "market_trend",
]

# 衍生因子（反向投信、日漲跌動量等）
DERIVED = {
    "neg_trust_net_buy":  ("trust_net_buy",  -1),
    "neg_trust_buy_5d":   ("trust_buy_5d",   -1),
    "neg_trust_buy_10d":  ("trust_buy_10d",  -1),
    "neg_trust_buy_20d":  ("trust_buy_20d",  -1),
    "neg_dealer_net_buy": ("dealer_net_buy",  -1),
    "neg_dealer_buy_5d":  ("dealer_buy_5d",   -1),
}


def load_data() -> pd.DataFrame:
    cols = list(set(
        ["stock_id", "date", "close", "change_pct", "volume",
         "ma5", "ma10", "ma20", "ma60"] + RAW_FACTORS
    ))
    sql = text(f"SELECT {', '.join(cols)} FROM stock_features "
               f"WHERE close > 0 AND date >= '2023-03-01' ORDER BY date, stock_id")
    df = pd.read_sql(sql, engine)
    df["date"] = pd.to_datetime(df["date"])

    # 衍生因子
    for name, (src, mult) in DERIVED.items():
        if src in df.columns:
            df[name] = df[src].fillna(0) * mult

    # 短期動量因子
    df = df.sort_values(["stock_id", "date"])
    df["ret_1d"] = df["change_pct"]  # 日報酬
    df["ret_5d"] = df.groupby("stock_id")["close"].pct_change(5)  # 5 日動量
    df["ret_10d"] = df.groupby("stock_id")["close"].pct_change(10)
    df["vol_chg_5d"] = df.groupby("stock_id")["volume"].pct_change(5)  # 量能 5d 變化

    print(f"[Data] {len(df):,} 筆，{df['date'].min().date()} ~ {df['date'].max().date()}")
    print(f"[Data] 每日股票數：{df.groupby('date')['stock_id'].nunique().median():.0f} (中位數)")
    return df


def compute_factor_ic(df: pd.DataFrame, forward_days: int) -> pd.DataFrame:
    """逐因子、逐季計算 IC"""
    df = df.sort_values(["stock_id", "date"]).copy()
    df["forward_close"] = df.groupby("stock_id")["close"].shift(-forward_days)
    df["forward_return"] = (df["forward_close"] - df["close"]) / df["close"]
    df = df.dropna(subset=["forward_return"])

    all_factors = RAW_FACTORS + list(DERIVED.keys()) + ["ret_1d", "ret_5d", "ret_10d", "vol_chg_5d"]

    # 分位數排名
    for f in all_factors:
        if f in df.columns:
            df[f"{f}_rank"] = df.groupby("date")[f].rank(pct=True, na_option="keep")

    # 按季計算每因子 IC
    df["quarter"] = df["date"].dt.to_period("Q")
    quarters = sorted(df["quarter"].unique())

    rows = []
    for f in all_factors:
        rc = f"{f}_rank"
        if rc not in df.columns:
            continue

        q_ics = []
        for q in quarters:
            qdf = df[df["quarter"] == q]
            daily_ics = []
            for _, grp in qdf.groupby("date"):
                if len(grp) < 50:
                    continue
                vals = grp[rc].values
                rets = grp["forward_return"].values
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
        pos_ratio = sum(1 for x in valid_ics if x > 0) / len(valid_ics)
        abs_avg = abs(avg_ic)
        # 穩定性分數 = |IC| × 正比例（或負比例）
        if avg_ic >= 0:
            stability = abs_avg * pos_ratio
        else:
            neg_ratio = sum(1 for x in valid_ics if x < 0) / len(valid_ics)
            stability = abs_avg * neg_ratio

        coverage = df[f].notna().mean() if f in df.columns else 0

        rows.append({
            "factor": f,
            "avg_ic": avg_ic,
            "abs_ic": abs_avg,
            "pos_ratio": pos_ratio,
            "stability": stability,
            "min_ic": min(valid_ics),
            "max_ic": max(valid_ics),
            "n_quarters": len(valid_ics),
            "coverage": coverage,
            "q_ics": q_ics,
        })

    result = pd.DataFrame(rows).sort_values("stability", ascending=False)
    return result, quarters


def print_results(result: pd.DataFrame, quarters, forward_days: int):
    print(f"\n{'=' * 100}")
    print(f"  {forward_days}d 因子 IC 穩定性分析（逐季）")
    print(f"{'=' * 100}")

    # 表頭
    print(f"\n  {'因子':>22} {'avgIC':>7} {'|IC|':>6} {'正比':>5} {'穩定':>6} {'覆蓋':>5} ", end="")
    for q in quarters:
        print(f" {str(q):>8}", end="")
    print()
    print("  " + "─" * (55 + 9 * len(quarters)))

    for _, row in result.iterrows():
        f = row["factor"]
        avg_ic = row["avg_ic"]
        # 標記
        if row["stability"] > 0.005 and row["pos_ratio"] >= 0.6 and avg_ic > 0:
            mark = " ★"
        elif row["stability"] > 0.005 and (1 - row["pos_ratio"]) >= 0.6 and avg_ic < 0:
            mark = " ◆"  # 穩定負 IC（可反向使用）
        else:
            mark = "  "

        print(f"  {f:>22} {avg_ic:>+7.4f} {row['abs_ic']:>6.4f} "
              f"{row['pos_ratio']:>4.0%} {row['stability']:>6.4f} "
              f"{row['coverage']:>4.0%}", end="")
        for ic in row["q_ics"]:
            if np.isnan(ic):
                print(f" {'---':>8}", end="")
            else:
                print(f" {ic:>+8.4f}", end="")
        print(mark)

    # 分類
    strong_pos = result[(result["avg_ic"] > 0.005) & (result["pos_ratio"] >= 0.6)]
    strong_neg = result[(result["avg_ic"] < -0.005) & (result["pos_ratio"] <= 0.4)]
    noise = result[(result["abs_ic"] < 0.005) | ((result["pos_ratio"] > 0.35) & (result["pos_ratio"] < 0.65))]

    print(f"\n  ★ 穩定正 IC (avg>0.005, ≥60%正): {', '.join(strong_pos['factor'].tolist()) or '無'}")
    print(f"  ◆ 穩定負 IC (avg<-0.005, ≤40%正): {', '.join(strong_neg['factor'].tolist()) or '無'}")
    print(f"  ─ 噪音 (|IC|<0.005 or 方向不穩): {len(noise)} 個因子")


def main():
    df = load_data()

    for fwd in [5, 10, 20]:
        result, quarters = compute_factor_ic(df, fwd)
        print_results(result, quarters, fwd)

        # 輸出候選因子
        candidates = result[
            ((result["avg_ic"] > 0.005) & (result["pos_ratio"] >= 0.6)) |
            ((result["avg_ic"] < -0.005) & (result["pos_ratio"] <= 0.4))
        ]
        print(f"\n  {fwd}d 候選因子 ({len(candidates)} 個):")
        for _, row in candidates.iterrows():
            direction = "正向" if row["avg_ic"] > 0 else "反向"
            print(f"    {row['factor']:>22}  IC={row['avg_ic']:>+.4f}  穩定={row['pos_ratio']:.0%}  [{direction}]")
        print()


if __name__ == "__main__":
    main()

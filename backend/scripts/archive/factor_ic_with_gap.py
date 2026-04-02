"""
因子 IC 穩定性分析 — 加入 gap 消除機械性負相關
gap=1: 因子取 T 日，forward return 從 T+1 算起 → (close_{T+1+fwd} - close_{T+1}) / close_{T+1}
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

RAW_FACTORS = [
    "rsi14", "rsi2", "k", "d", "macd_dif", "macd_osc",
    "bias5", "bias10", "bias20", "bb_pctb", "vol_ratio",
    "price_vs_high20", "ma_trend", "sector_rs",
    "atr_pct",
    "roe", "yield_rate", "pb_ratio", "revenue_yoy",
    "foreign_net_buy", "foreign_buy_5d", "foreign_buy_10d", "foreign_buy_20d",
    "trust_net_buy", "trust_buy_5d", "trust_buy_10d", "trust_buy_20d",
    "dealer_net_buy", "dealer_buy_5d", "dealer_buy_10d", "dealer_buy_20d",
    "margin_chg_5d",
    "foreign_hold_pct", "foreign_hold_chg_5d",
    "etf_net_flow_5d",
    "market_breadth", "market_trend",
]

DERIVED = {
    "neg_trust_net_buy":  ("trust_net_buy",  -1),
    "neg_trust_buy_5d":   ("trust_buy_5d",   -1),
    "neg_trust_buy_10d":  ("trust_buy_10d",  -1),
    "neg_trust_buy_20d":  ("trust_buy_20d",  -1),
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

    for name, (src, mult) in DERIVED.items():
        if src in df.columns:
            df[name] = df[src].fillna(0) * mult

    df = df.sort_values(["stock_id", "date"])
    df["ret_1d"] = df["change_pct"]
    df["ret_5d"] = df.groupby("stock_id")["close"].pct_change(5)
    df["ret_10d"] = df.groupby("stock_id")["close"].pct_change(10)
    df["vol_chg_5d"] = df.groupby("stock_id")["volume"].pct_change(5)

    print(f"[Data] {len(df):,} 筆，{df['date'].min().date()} ~ {df['date'].max().date()}")
    return df


def compute_forward_return_with_gap(df: pd.DataFrame, forward_days: int, gap: int = 1) -> pd.DataFrame:
    """
    forward return 從 T+gap 開始算：
    return = (close_{T+gap+forward_days} - close_{T+gap}) / close_{T+gap}

    這樣因子(T日) 和 forward return 沒有共用價格點
    """
    df = df.sort_values(["stock_id", "date"]).copy()
    # close_{T+gap}
    df["entry_close"] = df.groupby("stock_id")["close"].shift(-(gap))
    # close_{T+gap+forward_days}
    df["exit_close"] = df.groupby("stock_id")["close"].shift(-(gap + forward_days))
    df["forward_return"] = (df["exit_close"] - df["entry_close"]) / df["entry_close"]
    return df


def compute_factor_ic(df: pd.DataFrame, forward_days: int, gap: int) -> tuple:
    df = compute_forward_return_with_gap(df, forward_days, gap)
    df = df.dropna(subset=["forward_return"])

    all_factors = RAW_FACTORS + list(DERIVED.keys()) + ["ret_1d", "ret_5d", "ret_10d", "vol_chg_5d"]

    for f in all_factors:
        if f in df.columns:
            df[f"{f}_rank"] = df.groupby("date")[f].rank(pct=True, na_option="keep")

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
        coverage = df[f].notna().mean() if f in df.columns else 0

        rows.append({
            "factor": f,
            "avg_ic": avg_ic,
            "abs_ic": abs_avg,
            "pos_ratio": pos_ratio,
            "min_ic": min(valid_ics),
            "max_ic": max(valid_ics),
            "n_quarters": len(valid_ics),
            "coverage": coverage,
            "q_ics": q_ics,
        })

    result = pd.DataFrame(rows).sort_values("abs_ic", ascending=False)
    return result, quarters


def print_results(result: pd.DataFrame, quarters, forward_days: int, gap: int):
    print(f"\n{'=' * 100}")
    print(f"  {forward_days}d 因子 IC（gap={gap}d，消除機械性相關）")
    print(f"{'=' * 100}")

    print(f"\n  {'因子':>22} {'avgIC':>7} {'|IC|':>6} {'正比':>5} {'覆蓋':>5} ", end="")
    for q in quarters:
        print(f" {str(q):>8}", end="")
    print()
    print("  " + "─" * (45 + 9 * len(quarters)))

    for _, row in result.iterrows():
        f = row["factor"]
        avg_ic = row["avg_ic"]
        if abs(avg_ic) > 0.005 and row["pos_ratio"] >= 0.6 and avg_ic > 0:
            mark = " ★"
        elif abs(avg_ic) > 0.005 and row["pos_ratio"] <= 0.4 and avg_ic < 0:
            mark = " ◆"
        else:
            mark = "  "

        print(f"  {f:>22} {avg_ic:>+7.4f} {row['abs_ic']:>6.4f} "
              f"{row['pos_ratio']:>4.0%} {row['coverage']:>4.0%}", end="")
        for ic in row["q_ics"]:
            if np.isnan(ic):
                print(f" {'---':>8}", end="")
            else:
                print(f" {ic:>+8.4f}", end="")
        print(mark)

    strong_pos = result[(result["avg_ic"] > 0.005) & (result["pos_ratio"] >= 0.6)]
    strong_neg = result[(result["avg_ic"] < -0.005) & (result["pos_ratio"] <= 0.4)]

    print(f"\n  ★ 穩定正 IC: {', '.join(strong_pos['factor'].tolist()) or '無'}")
    print(f"  ◆ 穩定負 IC: {', '.join(strong_neg['factor'].tolist()) or '無'}")

    return strong_pos, strong_neg


def main():
    df = load_data()

    for fwd in [5, 10, 20]:
        for gap in [0, 1, 2]:
            result, quarters = compute_factor_ic(df, fwd, gap)
            sp, sn = print_results(result, quarters, fwd, gap)

        # gap=0 vs gap=1 比較摘要
        print(f"\n  === {fwd}d gap 影響摘要 ===")
        r0, _ = compute_factor_ic(df, fwd, 0)
        r1, _ = compute_factor_ic(df, fwd, 1)
        merged = r0[["factor", "avg_ic"]].merge(
            r1[["factor", "avg_ic"]], on="factor", suffixes=("_g0", "_g1")
        )
        merged["delta"] = merged["avg_ic_g1"] - merged["avg_ic_g0"]
        merged = merged.sort_values("delta", key=abs, ascending=False)
        print(f"\n  {'因子':>22} {'gap=0':>8} {'gap=1':>8} {'差異':>8}")
        print("  " + "─" * 48)
        for _, row in merged.head(15).iterrows():
            print(f"  {row['factor']:>22} {row['avg_ic_g0']:>+8.4f} {row['avg_ic_g1']:>+8.4f} {row['delta']:>+8.4f}")


if __name__ == "__main__":
    main()

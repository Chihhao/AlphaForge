"""
Track H: 因子相關性與正交性分析
目的：了解贏家因子（high_52w_ratio, neg_ivol_20d, yield_x_roe, neg_skew_20d）
      與現有 9 因子的相關性。高相關 = ML 模型已隱式捕捉 → 不太可能增加 alpha。

分析：
  1. 全樣本 Spearman 相關矩陣
  2. 逐月相關穩定性
  3. 新因子與 baseline fwd_ret 的 partial IC（控制 baseline 後的殘餘 IC）
  4. VIF 分析（多重共線性）
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
HOLD, GAP = 20, 1

BASE = [
    "roe", "yield_rate", "pb_ratio", "revenue_yoy",
    "rev_surprise", "rev_accel",
    "foreign_hold_chg_5d", "dealer_buy_20d", "vol_ratio",
]
NEW_FACTORS = ["high_52w_ratio", "neg_ivol_20d", "yield_x_roe", "neg_skew_20d"]


def load_data() -> pd.DataFrame:
    print("載入資料 ...", flush=True)
    feature_cols = list(set(
        ["stock_id", "date", "close", "yield_rate", "roe"] + BASE
    ))
    sql_feat = text(f"""
        SELECT {', '.join(feature_cols)}
        FROM stock_features
        WHERE close > 0 AND date >= '2022-06-01'
        ORDER BY stock_id, date
    """)
    feat = pd.read_sql(sql_feat, engine)
    feat["date"] = pd.to_datetime(feat["date"])

    sql_price = text("""
        SELECT stock_id, date, close AS p_close, high
        FROM stock_prices
        WHERE date >= '2022-01-01' AND close > 0
        ORDER BY stock_id, date
    """)
    price = pd.read_sql(sql_price, engine)
    price["date"] = pd.to_datetime(price["date"])
    price = price.sort_values(["stock_id", "date"])
    gp = price.groupby("stock_id")

    price["high_52w"] = gp["high"].transform(lambda x: x.rolling(250, min_periods=60).max())
    price["high_52w_ratio"] = price["p_close"] / price["high_52w"]

    price["ret"] = gp["p_close"].pct_change()
    daily_mkt = price.groupby("date")["ret"].median()
    price["mkt_ret"] = price["date"].map(daily_mkt)
    price["ivol_20d"] = gp.apply(
        lambda x: (x["ret"] - x["mkt_ret"]).rolling(20, min_periods=10).std()
    ).reset_index(level=0, drop=True)
    price["neg_ivol_20d"] = -price["ivol_20d"]

    price["skew_20d"] = gp["ret"].transform(lambda x: x.rolling(20, min_periods=15).skew())
    price["neg_skew_20d"] = -price["skew_20d"]

    new_cols = ["stock_id", "date", "high_52w_ratio", "neg_ivol_20d", "neg_skew_20d"]
    df = pd.merge(feat, price[new_cols], on=["stock_id", "date"], how="left")
    df["yield_x_roe"] = df["yield_rate"] * df["roe"]

    df = df.sort_values(["stock_id", "date"])
    g = df.groupby("stock_id")
    df["entry"] = g["close"].shift(-GAP)
    df["exit"] = g["close"].shift(-(GAP + HOLD))
    df["fwd_ret"] = (df["exit"] - df["entry"]) / df["entry"]
    df = df[df["date"] >= "2023-03-01"].copy()
    df["ym"] = df["date"].dt.to_period("M")

    print(f"  {len(df):,} 筆")
    return df


def run_analysis(df: pd.DataFrame) -> None:
    all_factors = BASE + NEW_FACTORS
    valid = df.dropna(subset=all_factors + ["fwd_ret"])
    print(f"\n有效筆數: {len(valid):,}")

    # ═══════════════════════════════════════════
    #  1. Spearman 相關矩陣
    # ═══════════════════════════════════════════
    print(f"\n{'=' * 120}")
    print("  Track H: 因子相關性分析")
    print(f"{'=' * 120}")

    # 用每日截面的 rank 再算相關，避免時間序列偽相關
    # 取一天快照
    sample_date = valid["date"].max()
    snapshot = valid[valid["date"] == sample_date].copy()
    for f in all_factors:
        snapshot[f"{f}_r"] = snapshot[f].rank(pct=True)

    rank_cols = [f"{f}_r" for f in all_factors]
    corr = snapshot[rank_cols].corr(method="spearman")

    # 顯示新因子 vs baseline 的相關
    print(f"\n  ── 新因子 vs Baseline 9 因子相關性（最新截面 Spearman rank）──")
    print(f"  {'新因子':>20}", end="")
    for b in BASE:
        print(f" {b[:8]:>9}", end="")
    print()
    print("  " + "─" * (20 + 9 * len(BASE) + len(BASE)))

    for nf in NEW_FACTORS:
        print(f"  {nf:>20}", end="")
        for b in BASE:
            c = corr.loc[f"{nf}_r", f"{b}_r"]
            marker = "**" if abs(c) > 0.5 else " *" if abs(c) > 0.3 else "  "
            print(f" {c:>+7.3f}{marker}", end="")
        print()

    # 新因子之間的相關
    print(f"\n  ── 新因子之間的相關 ──")
    print(f"  {'':>20}", end="")
    for nf in NEW_FACTORS:
        print(f" {nf[:12]:>13}", end="")
    print()
    for nf1 in NEW_FACTORS:
        print(f"  {nf1:>20}", end="")
        for nf2 in NEW_FACTORS:
            c = corr.loc[f"{nf1}_r", f"{nf2}_r"]
            print(f" {c:>+13.3f}", end="")
        print()

    # ═══════════════════════════════════════════
    #  2. 每月相關穩定性
    # ═══════════════════════════════════════════
    print(f"\n  ── 新因子 vs Baseline 月平均相關（跨時間穩定性）──")
    months = sorted(valid["ym"].unique())

    for nf in NEW_FACTORS:
        monthly_corrs: dict[str, list] = {b: [] for b in BASE}
        for ym in months:
            month_data = valid[valid["ym"] == ym]
            if len(month_data) < 200:
                continue
            for b in BASE:
                sub = month_data.dropna(subset=[nf, b])
                if len(sub) < 100:
                    continue
                c, _ = stats.spearmanr(sub[nf], sub[b])
                if not np.isnan(c):
                    monthly_corrs[b].append(c)

        print(f"\n    {nf}:")
        for b in BASE:
            if monthly_corrs[b]:
                mc = np.array(monthly_corrs[b])
                print(f"      vs {b:>20}: mean={np.mean(mc):+.3f}"
                      f" std={np.std(mc):.3f} range=[{np.min(mc):+.3f}, {np.max(mc):+.3f}]"
                      f" {'⚠️ 高相關' if abs(np.mean(mc)) > 0.3 else '✓ 低相關'}")

    # ═══════════════════════════════════════════
    #  3. Partial IC: 控制 baseline 後的殘餘 IC
    # ═══════════════════════════════════════════
    print(f"\n  ── Partial IC（控制 baseline 9 因子後的殘餘預測力）──")
    print(f"  {'新因子':>20} {'Raw IC':>8} {'Partial IC':>10} {'保留率':>8} {'判定':>8}")
    print("  " + "─" * 60)

    for nf in NEW_FACTORS:
        raw_ics = []
        partial_ics = []

        for ym in months:
            month_data = valid[valid["ym"] == ym]
            for d, day in month_data.groupby("date"):
                sub = day.dropna(subset=[nf, "fwd_ret"] + BASE)
                if len(sub) < 100:
                    continue

                # Raw IC
                raw_ic, _ = stats.spearmanr(sub[nf], sub["fwd_ret"])
                if np.isnan(raw_ic):
                    continue
                raw_ics.append(raw_ic)

                # Partial IC: residualize new factor and fwd_ret on baseline
                from numpy.linalg import lstsq
                X_base = sub[BASE].rank(pct=True).fillna(0.5).values
                y_factor = sub[nf].rank(pct=True).values
                y_fwd = sub["fwd_ret"].values

                # Residuals
                beta_f, _, _, _ = lstsq(X_base, y_factor, rcond=None)
                resid_factor = y_factor - X_base @ beta_f

                beta_r, _, _, _ = lstsq(X_base, y_fwd, rcond=None)
                resid_ret = y_fwd - X_base @ beta_r

                pic, _ = stats.spearmanr(resid_factor, resid_ret)
                if not np.isnan(pic):
                    partial_ics.append(pic)

        if raw_ics and partial_ics:
            raw = np.mean(raw_ics)
            partial = np.mean(partial_ics)
            retention = partial / raw * 100 if abs(raw) > 0.001 else 0
            verdict = "★★★" if abs(partial) > 0.02 and retention > 50 else \
                      "★★" if abs(partial) > 0.01 and retention > 30 else \
                      "★" if abs(partial) > 0.005 else "冗餘"
            print(f"  {nf:>20} {raw:>+8.4f} {partial:>+10.4f}"
                  f" {retention:>7.0f}% {verdict:>8}")

    # ═══════════════════════════════════════════
    #  4. 最大相關因子識別
    # ═══════════════════════════════════════════
    print(f"\n  ── 每個新因子最相關的 baseline 因子 ──")
    for nf in NEW_FACTORS:
        max_corr = 0
        max_base = ""
        for b in BASE:
            sub = valid.dropna(subset=[nf, b])
            if len(sub) < 1000:
                continue
            c, _ = stats.spearmanr(sub[nf], sub[b])
            if abs(c) > abs(max_corr):
                max_corr = c
                max_base = b
        print(f"    {nf:>20} → {max_base:>20} (ρ={max_corr:+.3f})")

    print(f"\n{'=' * 120}")
    print("  Track H 完成")
    print(f"{'=' * 120}\n")


if __name__ == "__main__":
    df = load_data()
    run_analysis(df)

"""
Track G: Overlay / 事後過濾策略
假說：不改變 ML 模型，而是用新因子對 Top10% 推薦做二次篩選。
      這比加因子到 ML 更穩健（不增加模型複雜度）。

方法：
  1. 用 baseline 9 因子模型選出 Top10%
  2. 在 Top10% 中再用新因子做二次篩選（取上半 or 上 1/3）
  3. 比較過濾後 vs 未過濾的報酬

測試因子：
  A) high_52w_ratio > 中位數（近高點）
  B) neg_ivol_20d > 中位數（低波動）
  C) yield_x_roe > 中位數（高品質價值）
  D) high_52w_ratio > 中位數 AND neg_ivol_20d > 中位數（雙過濾）
  E) 上述因子複合分數 Top50%
"""
from __future__ import annotations

import os
import warnings
from typing import Dict, List

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sqlalchemy import create_engine, text

warnings.filterwarnings("ignore")
PG_URL = os.getenv(
    "PG_URL",
    "postgresql://alphaforge:alphaforge_secret@10.0.4.3:5433/alphaforge",
)
engine = create_engine(PG_URL)

HOLD, GAP, COST = 20, 1, 0.006
TRAIN_MONTHS = 12

BASE = [
    "roe", "yield_rate", "pb_ratio", "revenue_yoy",
    "rev_surprise", "rev_accel",
    "foreign_hold_chg_5d", "dealer_buy_20d", "vol_ratio",
]


def load_data() -> pd.DataFrame:
    print("載入資料 ...", flush=True)
    feature_cols = list(set(
        ["stock_id", "date", "close", "ma60", "yield_rate", "roe"] + BASE
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
        SELECT stock_id, date, close AS p_close, high, volume
        FROM stock_prices
        WHERE date >= '2022-01-01' AND close > 0 AND volume > 0
        ORDER BY stock_id, date
    """)
    price = pd.read_sql(sql_price, engine)
    price["date"] = pd.to_datetime(price["date"])

    # 計算新因子
    price = price.sort_values(["stock_id", "date"])
    gp = price.groupby("stock_id")

    # high_52w_ratio
    price["high_52w"] = gp["high"].transform(
        lambda x: x.rolling(250, min_periods=60).max()
    )
    price["high_52w_ratio"] = price["p_close"] / price["high_52w"]

    # neg_ivol_20d
    price["ret"] = gp["p_close"].pct_change()
    daily_mkt = price.groupby("date")["ret"].median()
    price["mkt_ret"] = price["date"].map(daily_mkt)
    price["excess_ret"] = price["ret"] - price["mkt_ret"]
    price["ivol_20d"] = gp["excess_ret"].transform(
        lambda x: x.rolling(20, min_periods=10).std()
    )
    price["neg_ivol_20d"] = -price["ivol_20d"]

    new_cols = ["stock_id", "date", "high_52w_ratio", "neg_ivol_20d"]
    df = pd.merge(feat, price[new_cols], on=["stock_id", "date"], how="left")

    df["yield_x_roe"] = df["yield_rate"] * df["roe"]

    df = df.sort_values(["stock_id", "date"])
    g = df.groupby("stock_id")
    df["entry"] = g["close"].shift(-GAP)
    df["exit"] = g["close"].shift(-(GAP + HOLD))
    df["fwd_ret"] = (df["exit"] - df["entry"]) / df["entry"]
    df = df[df["date"] >= "2023-03-01"].copy()
    df["ym"] = df["date"].dt.to_period("M")
    print(f"  合併完成: {len(df):,} 筆")
    return df


def train_base_model(train: pd.DataFrame) -> tuple | None:
    t = train.dropna(subset=BASE + ["fwd_ret"]).copy()
    if len(t) < 500:
        return None
    rank_cols = []
    for f in BASE:
        rc = f"{f}_r"
        t[rc] = t.groupby("date")[f].rank(pct=True)
        rank_cols.append(rc)
    X = t[rank_cols].values
    y_cls = (t["fwd_ret"] > t["fwd_ret"].median()).astype(int).values
    clf = HistGradientBoostingClassifier(max_iter=150, max_depth=4, random_state=42)
    reg = HistGradientBoostingRegressor(max_iter=150, max_depth=4, random_state=42)
    clf.fit(X, y_cls)
    reg.fit(X, t["fwd_ret"].values)
    return clf, reg, rank_cols


def score_day(clf, reg, rank_cols, day_data: pd.DataFrame) -> pd.DataFrame | None:
    s = day_data.dropna(subset=BASE).copy()
    if len(s) < 50:
        return None
    for f, rc in zip(BASE, rank_cols):
        s[rc] = s[f].rank(pct=True)
    X = s[rank_cols].values
    s["score"] = clf.predict_proba(X)[:, 1] * 0.5 + \
                 pd.Series(reg.predict(X)).rank(pct=True).values * 0.5
    return s


FILTERS = {
    "A_no_filter":      lambda top: top,
    "B_52wHigh>med":    lambda top: top[top["high_52w_ratio"] > top["high_52w_ratio"].median()],
    "C_lowVol>med":     lambda top: top[top["neg_ivol_20d"] > top["neg_ivol_20d"].median()],
    "D_yieldROE>med":   lambda top: top[top["yield_x_roe"] > top["yield_x_roe"].median()],
    "E_52w+lowVol":     lambda top: top[
        (top["high_52w_ratio"] > top["high_52w_ratio"].median()) &
        (top["neg_ivol_20d"] > top["neg_ivol_20d"].median())
    ],
    "F_composite>med":  lambda top: top[
        (top["high_52w_ratio"].rank(pct=True) +
         top["neg_ivol_20d"].rank(pct=True) +
         top["yield_x_roe"].rank(pct=True)) / 3 > 0.5
    ],
    "G_52w+yROE":       lambda top: top[
        (top["high_52w_ratio"] > top["high_52w_ratio"].median()) &
        (top["yield_x_roe"] > top["yield_x_roe"].median())
    ],
}


def run_research(df: pd.DataFrame) -> None:
    months = sorted(df["ym"].unique())
    results: Dict[str, List[dict]] = {name: [] for name in FILTERS}

    test_start = TRAIN_MONTHS
    print(f"\n測試窗口: {len(months) - test_start} 個月\n")

    for i in range(test_start, len(months)):
        test_month = months[i]
        train_months = months[i - TRAIN_MONTHS:i]
        train = df[df["ym"].isin(train_months)].copy()
        test = df[df["ym"] == test_month].copy()
        test_dates = sorted(test["date"].unique())
        if not test_dates:
            continue

        print(f"  {test_month}: {len(test_dates)} 交易日", end="", flush=True)

        models = train_base_model(train)
        if models is None:
            print(" (skip)")
            continue
        clf, reg, rank_cols = models

        for filter_name, filter_fn in FILTERS.items():
            daily_rets = []
            daily_ns = []

            for td in test_dates:
                day_data = test[test["date"] == td].copy()
                if len(day_data) < 100:
                    continue

                scored = score_day(clf, reg, rank_cols, day_data)
                if scored is None:
                    continue

                # Top 10% by ML score
                scored["rank_pct"] = scored["score"].rank(pct=True)
                top10 = scored[scored["rank_pct"] >= 0.9].copy()

                if len(top10) < 10:
                    continue

                # Apply filter
                filtered = filter_fn(top10)
                if len(filtered) < 3:
                    continue

                valid_filtered = filtered.dropna(subset=["fwd_ret"])
                if len(valid_filtered) < 3:
                    continue

                daily_rets.append(valid_filtered["fwd_ret"].mean())
                daily_ns.append(len(valid_filtered))

            if daily_rets:
                results[filter_name].append({
                    "ym": str(test_month),
                    "ret": np.mean(daily_rets),
                    "n_stocks": np.mean(daily_ns),
                })

        print(" ✓")

    # ════════════════════════════════════════════════════════════
    print(f"\n{'=' * 120}")
    print("  Track G: Overlay 策略（事後過濾）結果")
    print(f"{'=' * 120}")

    print(f"\n  {'過濾策略':>20} {'月數':>4} {'月均報酬':>8} {'報酬正':>5}"
          f" {'年化':>8} {'Sharpe':>7} {'MDD':>7} {'持股數':>6}")
    print("  " + "─" * 80)

    all_summaries = []
    for name in FILTERS:
        ms = results[name]
        if not ms:
            continue
        mdf = pd.DataFrame(ms)
        avg_ret = mdf["ret"].mean() * 100
        ret_pos = (mdf["ret"] > 0).mean()
        annual = (1 + mdf["ret"].mean()) ** 12 - 1
        sharpe = mdf["ret"].mean() / mdf["ret"].std(ddof=1) * np.sqrt(12) if mdf["ret"].std() > 0 else 0
        cum = (1 + mdf["ret"] - COST).cumprod()
        maxdd = ((cum - cum.cummax()) / cum.cummax()).min() * 100
        avg_n = mdf["n_stocks"].mean()

        all_summaries.append({
            "name": name, "n": len(mdf),
            "ret": avg_ret, "ret_pos": ret_pos,
            "annual": annual * 100, "sharpe": sharpe,
            "maxdd": maxdd, "avg_n": avg_n,
        })

        print(f"  {name:>20} {len(mdf):>4} {avg_ret:>+7.2f}%"
              f" {ret_pos:>4.0%} {annual*100:>+7.1f}% {sharpe:>7.2f}"
              f" {maxdd:>6.1f}% {avg_n:>5.0f}")

    # baseline comparison
    sdf = pd.DataFrame(all_summaries)
    if sdf.empty:
        return

    baseline_ret = sdf[sdf["name"] == "A_no_filter"]["ret"].iloc[0]

    print(f"\n  ── 排名（按月均報酬排序）──")
    ranked = sdf.sort_values("ret", ascending=False)
    for rank, (_, r) in enumerate(ranked.iterrows(), 1):
        delta = r["ret"] - baseline_ret
        marker = " ★★" if delta > 0.3 else " ★" if delta > 0.1 else ""
        print(f"  {rank}. {r['name']:>20} ret={r['ret']:+.2f}% (Δ={delta:+.2f}%)"
              f" Sharpe={r['sharpe']:.2f} N={r['avg_n']:.0f}{marker}")

    # ── 逐月對比 baseline vs best ──
    best_name = ranked.iloc[0]["name"]
    if best_name != "A_no_filter":
        print(f"\n  ── 逐月報酬：A_no_filter vs {best_name} ──")
        base_df = pd.DataFrame(results["A_no_filter"])
        best_df = pd.DataFrame(results[best_name])
        merged = pd.merge(
            base_df[["ym", "ret"]].rename(columns={"ret": "base"}),
            best_df[["ym", "ret"]].rename(columns={"ret": "best"}),
            on="ym",
        )
        for _, row in merged.iterrows():
            diff = (row["best"] - row["base"]) * 100
            bar = "+" * int(max(0, diff * 5)) if diff > 0 else "-" * int(max(0, -diff * 5))
            print(f"    {row['ym']} base={row['base']*100:+5.1f}% best={row['best']*100:+5.1f}%"
                  f" Δ={diff:+5.1f}% |{bar}")

        # 配對 t 檢定
        if len(merged) > 5:
            t_stat, p_val = stats.ttest_rel(merged["best"], merged["base"])
            print(f"\n    配對 t 檢定: t={t_stat:.3f}, p={p_val:.4f}")

    print(f"\n{'=' * 120}")
    print("  Track G 完成")
    print(f"{'=' * 120}\n")


if __name__ == "__main__":
    df = load_data()
    run_research(df)

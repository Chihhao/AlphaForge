"""
Alpha 挖掘：全面因子組合搜索

用每日截面 walk-forward，測試 8 種因子組合。
每個窗口：12 個月訓練 → 1 個月測試，每日截面計算 IC。
這樣每個窗口有 ~20 個 OOS IC 值，總計數百個。

因子組合：
A) 現有 9 因子 (baseline)
B) +neg_price_vs_high20 (錯誤分析 p=0.008)
C) +neg_price_vs_high20 + neg_foreign_buy_5d (錯誤分析組合)
D) +rsi2 (遺珠分析 p=0.003)
E) +neg_price_vs_high20 + rsi2
F) +bias20 反向 (近高點乖離 → 過熱)
G) +neg_price_vs_high20 + neg_bias20
H) 精選 11 因子 (baseline + neg_high20 + rsi2，去掉最弱因子)
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

HOLD = 20
GAP = 1
COST = 0.006
TRAIN_MONTHS = 12

BASE = [
    "roe", "yield_rate", "pb_ratio", "revenue_yoy",
    "rev_surprise", "rev_accel",
    "foreign_hold_chg_5d", "dealer_buy_20d", "vol_ratio",
]

STRATEGIES: Dict[str, List[str]] = {
    "A_base9":        BASE,
    "B_+negHigh20":   BASE + ["neg_price_vs_high20"],
    "C_+negH20+negF5": BASE + ["neg_price_vs_high20", "neg_foreign_buy_5d"],
    "D_+rsi2":        BASE + ["rsi2"],
    "E_+negH20+rsi2": BASE + ["neg_price_vs_high20", "rsi2"],
    "F_+negBias20":   BASE + ["neg_bias20"],
    "G_+negH20+negB": BASE + ["neg_price_vs_high20", "neg_bias20"],
    "H_select11":     ["roe", "pb_ratio", "revenue_yoy", "yield_rate",
                        "rev_surprise", "rev_accel",
                        "foreign_hold_chg_5d", "dealer_buy_20d",
                        "neg_price_vs_high20", "rsi2", "vol_ratio"],
}


def load_data() -> pd.DataFrame:
    cols = list(set(
        ["stock_id", "date", "close", "ma60",
         "price_vs_high20", "foreign_buy_5d", "rsi2", "bias20"]
        + BASE
    ))
    sql = text(f"""
        SELECT {', '.join(cols)}
        FROM stock_features
        WHERE close > 0 AND date >= '2023-03-01'
        ORDER BY date, stock_id
    """)
    df = pd.read_sql(sql, engine)
    df["date"] = pd.to_datetime(df["date"])

    # 衍生反向因子
    df["neg_price_vs_high20"] = -df["price_vs_high20"]
    df["neg_foreign_buy_5d"] = -df["foreign_buy_5d"]
    df["neg_bias20"] = -df["bias20"]

    # Forward return (向量化)
    df = df.sort_values(["stock_id", "date"])
    df["entry"] = df.groupby("stock_id")["close"].shift(-GAP)
    df["exit"] = df.groupby("stock_id")["close"].shift(-(GAP + HOLD))
    df["fwd_ret"] = (df["exit"] - df["entry"]) / df["entry"]

    df["ym"] = df["date"].dt.to_period("M")
    return df


def train_models(
    train: pd.DataFrame, factors: List[str]
) -> tuple | None:
    """訓練 ensemble，回傳 (clf, reg, rank_cols)，每月只訓練一次"""
    t = train.dropna(subset=factors + ["fwd_ret"]).copy()
    if len(t) < 500:
        return None

    rank_cols = []
    for f in factors:
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


def predict_day(
    clf, reg, rank_cols: List[str], factors: List[str], day_data: pd.DataFrame
) -> pd.Series | None:
    """用已訓練的模型對單日截面預測"""
    s = day_data.dropna(subset=factors).copy()
    if len(s) < 50:
        return None

    for f, rc in zip(factors, rank_cols):
        s[rc] = s[f].rank(pct=True)

    X = s[rank_cols].values
    score = clf.predict_proba(X)[:, 1] * 0.5 + \
            pd.Series(reg.predict(X)).rank(pct=True).values * 0.5
    return pd.Series(score, index=s.index)


def run_research(df: pd.DataFrame) -> None:
    months = sorted(df["ym"].unique())
    dates = sorted(df["date"].unique())

    # 每月跑一次訓練，然後在測試月的每個交易日做截面預測
    results: Dict[str, List[dict]] = {name: [] for name in STRATEGIES}

    test_start = TRAIN_MONTHS
    n_test = len(months) - test_start
    print(f"測試窗口: {n_test} 個月\n")

    for i in range(test_start, len(months)):
        test_month = months[i]
        train_months = months[i - TRAIN_MONTHS:i]

        train = df[df["ym"].isin(train_months)].copy()
        test = df[df["ym"] == test_month].copy()

        test_dates = sorted(test["date"].unique())
        if not test_dates:
            continue

        print(f"  {test_month}: {len(test_dates)} 交易日", end="", flush=True)

        for strat_name, factors in STRATEGIES.items():
            # 每月訓練一次
            models = train_models(train, factors)
            if models is None:
                continue
            clf, reg, rank_cols = models

            daily_ics = []
            daily_tops = []
            daily_bots = []
            daily_mkts = []

            for td in test_dates:
                day_data = test[test["date"] == td].copy()
                if len(day_data) < 100:
                    continue

                scores = predict_day(clf, reg, rank_cols, factors, day_data)
                if scores is None:
                    continue

                day_data.loc[scores.index, "score"] = scores
                valid = day_data.dropna(subset=["score", "fwd_ret"])
                if len(valid) < 50:
                    continue

                # IC
                ic, _ = stats.spearmanr(valid["score"], valid["fwd_ret"])
                if np.isnan(ic):
                    continue
                daily_ics.append(ic)

                # Top/Bot 10%
                valid["rank_pct"] = valid["score"].rank(pct=True)
                top10 = valid[valid["rank_pct"] >= 0.9]["fwd_ret"]
                bot10 = valid[valid["rank_pct"] <= 0.1]["fwd_ret"]
                mkt = valid["fwd_ret"]

                daily_tops.append(top10.mean())
                daily_bots.append(bot10.mean())
                daily_mkts.append(mkt.mean())

            if not daily_ics:
                continue

            results[strat_name].append({
                "ym": str(test_month),
                "ic_mean": np.mean(daily_ics),
                "ic_pos": np.mean([1 for x in daily_ics if x > 0]),
                "n_days": len(daily_ics),
                "top10": np.mean(daily_tops),
                "bot10": np.mean(daily_bots),
                "mkt": np.mean(daily_mkts),
                "excess": np.mean(daily_tops) - np.mean(daily_mkts),
                "ls": np.mean(daily_tops) - np.mean(daily_bots),
            })

        print(" ✓")

    # ════════════════════════════════════════════════════════════
    #  結果
    # ════════════════════════════════════════════════════════════
    print(f"\n{'=' * 140}")
    print(f"  全面因子組合搜索結果")
    print(f"{'=' * 140}")

    print(f"\n  {'策略':>20} {'N因子':>5} {'月數':>4} {'IC':>8} {'IC正':>5}"
          f" {'超額':>8} {'超正':>5} {'L-S':>8} {'LS正':>5} {'Bot虧':>5}"
          f" {'Sharpe':>7} {'MDD':>7}")
    print("  " + "─" * 120)

    all_summaries = []
    for strat_name in STRATEGIES:
        ms = results[strat_name]
        if not ms:
            continue
        mdf = pd.DataFrame(ms)
        n = len(mdf)

        avg_ic = mdf["ic_mean"].mean()
        ic_pos_months = (mdf["ic_mean"] > 0).mean()
        avg_excess = mdf["excess"].mean() * 100
        excess_pos = (mdf["excess"] > 0).mean()
        avg_ls = mdf["ls"].mean() * 100
        ls_pos = (mdf["ls"] > 0).mean()
        bot_neg = (mdf["bot10"] < 0).mean()

        me = mdf["excess"].values
        sharpe = np.mean(me) / np.std(me, ddof=1) * np.sqrt(12) if np.std(me, ddof=1) > 0 else 0
        cum = (1 + mdf["top10"] - COST).cumprod()
        maxdd = ((cum - cum.cummax()) / cum.cummax()).min() * 100

        nf = len(STRATEGIES[strat_name])
        all_summaries.append({
            "name": strat_name, "nf": nf, "n": n,
            "ic": avg_ic, "ic_pos": ic_pos_months,
            "excess": avg_excess, "excess_pos": excess_pos,
            "ls": avg_ls, "ls_pos": ls_pos, "bot_neg": bot_neg,
            "sharpe": sharpe, "maxdd": maxdd,
        })

        print(f"  {strat_name:>20} {nf:>5} {n:>4} {avg_ic:>+8.4f} {ic_pos_months:>4.0%}"
              f" {avg_excess:>+7.2f}% {excess_pos:>4.0%}"
              f" {avg_ls:>+7.2f}% {ls_pos:>4.0%} {bot_neg:>4.0%}"
              f" {sharpe:>7.2f} {maxdd:>6.1f}%")

    # ── 排名 ──
    sdf = pd.DataFrame(all_summaries)
    if sdf.empty:
        print("  (no results)")
        return

    baseline_ic = sdf[sdf["name"] == "A_base9"]["ic"].iloc[0]

    print(f"\n  ── 排名（按 IC 排序）──")
    ranked = sdf.sort_values("ic", ascending=False)
    for rank, (_, r) in enumerate(ranked.iterrows(), 1):
        delta = r["ic"] - baseline_ic
        marker = " ★★" if delta > 0.01 else " ★" if delta > 0.005 else ""
        print(f"  {rank}. {r['name']:>20} IC={r['ic']:+.4f} (Δ={delta:+.4f})"
              f" L-S={r['ls']:+.2f}% Sharpe={r['sharpe']:.2f}{marker}")

    # ── 最佳策略逐月/逐年詳情 ──
    best_name = ranked.iloc[0]["name"]
    if best_name != "A_base9":
        print(f"\n  ── {best_name} 逐年表現 ──")
        bdf = pd.DataFrame(results[best_name])
        bdf["year"] = bdf["ym"].apply(lambda x: x[:4])

        print(f"  {'年':>6} {'IC':>8} {'IC正':>5} {'超額':>8} {'L-S':>8} {'月數':>5}")
        print("  " + "─" * 45)
        for yr, ygrp in bdf.groupby("year"):
            print(f"  {yr:>6} {ygrp['ic_mean'].mean():>+8.4f}"
                  f" {(ygrp['ic_mean']>0).mean():>4.0%}"
                  f" {ygrp['excess'].mean()*100:>+7.2f}%"
                  f" {ygrp['ls'].mean()*100:>+7.2f}%"
                  f" {len(ygrp):>5}")

        # 配對檢定 vs baseline
        adf = pd.DataFrame(results["A_base9"])
        merged = bdf.merge(adf, on="ym", suffixes=("_best", "_base"))
        if len(merged) >= 5:
            t_ic, p_ic = stats.ttest_rel(merged["ic_mean_best"], merged["ic_mean_base"])
            t_ls, p_ls = stats.ttest_rel(merged["ls_best"], merged["ls_base"])
            print(f"\n  配對 t 檢定 vs baseline:")
            print(f"    IC:  t={t_ic:.2f}, p={p_ic:.4f} {'★★' if p_ic<0.05 else '★' if p_ic<0.1 else ''}")
            print(f"    L-S: t={t_ls:.2f}, p={p_ls:.4f} {'★★' if p_ls<0.05 else '★' if p_ls<0.1 else ''}")

    # ── 結論 ──
    print(f"\n{'=' * 140}")
    print(f"  結論")
    print(f"{'=' * 140}")

    best = ranked.iloc[0]
    delta = best["ic"] - baseline_ic

    if delta > 0.005 and best["ls"] > 0 and best["ic_pos"] >= 0.7:
        print(f"\n  ★ 找到改善方案: {best['name']}")
        print(f"    IC: {baseline_ic:+.4f} → {best['ic']:+.4f} (Δ={delta:+.4f}, +{delta/baseline_ic*100:.0f}%)")
        print(f"    L-S: {sdf[sdf['name']=='A_base9']['ls'].iloc[0]:+.2f}% → {best['ls']:+.2f}%")
        print(f"    Sharpe: {sdf[sdf['name']=='A_base9']['sharpe'].iloc[0]:.2f} → {best['sharpe']:.2f}")
        print(f"    建議更新線上模型")
    elif delta > 0:
        print(f"\n  ◎ 有改善但幅度小: {best['name']} (ΔIC={delta:+.4f})")
        print(f"    建議繼續觀察")
    else:
        print(f"\n  ✗ 所有新組合都未超越 baseline")
        print(f"    現有 9 因子已是最優")


def main() -> None:
    print("=== Alpha 挖掘：全面因子搜索 ===\n")
    df = load_data()
    print(f"Data: {len(df):,} rows, {df['date'].min().date()} ~ {df['date'].max().date()}\n")
    run_research(df)


if __name__ == "__main__":
    main()

"""
驗證：加入反向過熱因子是否提升模型 IC

錯誤分析發現的盲點：模型選中基本面好但已漲到位的股票。
測試把 price_vs_high20 和 foreign_buy_5d 取反加入模型。

策略組合：
A) 現有 9 因子（baseline）
B) 9 因子 + neg_price_vs_high20（離高點越遠越好）
C) 9 因子 + neg_foreign_buy_5d（外資近期沒追買越好）
D) 9 因子 + neg_price_vs_high20 + neg_foreign_buy_5d
E) 9 因子 + neg_price_vs_high20 + neg_foreign_buy_5d + atr_pct

Walk-forward: 12m train → 1m test, gap=1, 20d hold
指標: IC, IC正比, Top10% 超額, Long-Short, Bot10%下跌率
"""
from __future__ import annotations

import os
import warnings
from typing import Dict, List, Tuple

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

BASE_FACTORS = [
    "roe", "yield_rate", "pb_ratio", "revenue_yoy",
    "rev_surprise", "rev_accel",
    "foreign_hold_chg_5d", "dealer_buy_20d", "vol_ratio",
]

STRATEGIES: Dict[str, List[str]] = {
    "A_baseline_9":     BASE_FACTORS,
    "B_+neg_high20":    BASE_FACTORS + ["neg_price_vs_high20"],
    "C_+neg_frgn5d":    BASE_FACTORS + ["neg_foreign_buy_5d"],
    "D_+both":          BASE_FACTORS + ["neg_price_vs_high20", "neg_foreign_buy_5d"],
    "E_+both+atr":      BASE_FACTORS + ["neg_price_vs_high20", "neg_foreign_buy_5d", "atr_pct"],
}


def load_data() -> pd.DataFrame:
    all_needed = list(set(
        ["stock_id", "date", "close", "ma60",
         "price_vs_high20", "foreign_buy_5d", "atr_pct"]
        + BASE_FACTORS
    ))
    sql = text(f"""
        SELECT {', '.join(all_needed)}
        FROM stock_features
        WHERE close > 0 AND date >= '2023-03-01'
        ORDER BY date, stock_id
    """)
    df = pd.read_sql(sql, engine)
    df["date"] = pd.to_datetime(df["date"])

    # 反向因子
    df["neg_price_vs_high20"] = -df["price_vs_high20"]
    df["neg_foreign_buy_5d"] = -df["foreign_buy_5d"]

    return df


def run_walkforward(df: pd.DataFrame) -> None:
    df["ym"] = df["date"].dt.to_period("M")
    months = sorted(df["ym"].unique())

    results: Dict[str, List[dict]] = {name: [] for name in STRATEGIES}

    print(f"Walk-Forward: {TRAIN_MONTHS}m train → 1m test")
    print(f"測試月數: {len(months) - TRAIN_MONTHS}")

    for i in range(TRAIN_MONTHS, len(months)):
        test_month = months[i]
        train_months = months[i - TRAIN_MONTHS:i]

        train = df[df["ym"].isin(train_months)].copy()
        test = df[df["ym"] == test_month].copy()

        # Forward return
        for sub in [train, test]:
            sub["entry"] = sub.groupby("stock_id")["close"].shift(-GAP)
            sub["exit"] = sub.groupby("stock_id")["close"].shift(-(GAP + HOLD))
            sub["fwd_ret"] = (sub["exit"] - sub["entry"]) / sub["entry"]

        # 用每月最後一天的截面做測試（模擬月底選股）
        test_last = test.groupby("stock_id").last().reset_index()
        train = train.dropna(subset=["fwd_ret"])

        if len(train) < 1000 or len(test_last) < 100:
            continue

        for strat_name, factors in STRATEGIES.items():
            t_train = train.dropna(subset=factors + ["fwd_ret"]).copy()
            t_test = test_last.dropna(subset=factors).copy()

            if len(t_train) < 500 or len(t_test) < 80:
                continue

            # Rank
            rank_cols = []
            for f in factors:
                rc = f"{f}_r"
                t_train[rc] = t_train.groupby("date")[f].rank(pct=True)
                t_test[rc] = t_test[f].rank(pct=True)
                rank_cols.append(rc)

            X_train = t_train[rank_cols].values
            X_test = t_test[rank_cols].values
            y_cls = (t_train["fwd_ret"] > t_train["fwd_ret"].median()).astype(int).values
            y_reg = t_train["fwd_ret"].values

            # Ensemble
            clf = HistGradientBoostingClassifier(max_iter=200, max_depth=4, random_state=42)
            reg = HistGradientBoostingRegressor(max_iter=200, max_depth=4, random_state=42)
            clf.fit(X_train, y_cls)
            reg.fit(X_train, y_reg)

            clf_prob = clf.predict_proba(X_test)[:, 1]
            reg_rank = pd.Series(reg.predict(X_test)).rank(pct=True).values
            t_test["score"] = clf_prob * 0.5 + reg_rank * 0.5

            # 排名
            t_test["rank_pct"] = t_test["score"].rank(pct=True)
            top10 = t_test[t_test["rank_pct"] >= 0.9]
            bot10 = t_test[t_test["rank_pct"] <= 0.1]

            # 已知 fwd_ret 的子集
            top10_r = top10.dropna(subset=["fwd_ret"])
            bot10_r = bot10.dropna(subset=["fwd_ret"])
            all_r = t_test.dropna(subset=["fwd_ret"])

            if len(top10_r) < 5 or len(all_r) < 30:
                continue

            # IC
            ic_vals = all_r[["score", "fwd_ret"]].dropna()
            ic = stats.spearmanr(ic_vals["score"], ic_vals["fwd_ret"])[0] if len(ic_vals) >= 30 else np.nan

            top_avg = top10_r["fwd_ret"].mean()
            bot_avg = bot10_r["fwd_ret"].mean() if len(bot10_r) > 0 else np.nan
            mkt_avg = all_r["fwd_ret"].mean()

            results[strat_name].append({
                "ym": str(test_month),
                "ic": ic,
                "top10": top_avg,
                "bot10": bot_avg,
                "mkt": mkt_avg,
                "excess": top_avg - mkt_avg,
                "ls": top_avg - bot_avg if not np.isnan(bot_avg) else np.nan,
                "n_top": len(top10_r),
                "n_all": len(all_r),
            })

    # ── 結果彙總 ──
    print(f"\n{'=' * 130}")
    print(f"  策略對比")
    print(f"{'=' * 130}")

    summary_rows = []
    for strat_name in STRATEGIES:
        ms = results[strat_name]
        if not ms:
            continue
        mdf = pd.DataFrame(ms)
        n = len(mdf)

        avg_ic = mdf["ic"].dropna().mean()
        ic_pos = (mdf["ic"].dropna() > 0).mean()
        avg_excess = mdf["excess"].mean() * 100
        avg_ls = mdf["ls"].dropna().mean() * 100
        ls_pos = (mdf["ls"].dropna() > 0).mean()
        excess_pos = (mdf["excess"] > 0).mean()
        bot_neg = (mdf["bot10"].dropna() < 0).mean()

        me = mdf["excess"].values
        sharpe = np.mean(me) / np.std(me, ddof=1) * np.sqrt(12) if np.std(me) > 0 else 0

        cum = (1 + mdf["top10"] - COST).cumprod()
        maxdd = ((cum - cum.cummax()) / cum.cummax()).min() * 100
        cum_ret = (cum.iloc[-1] - 1) * 100

        summary_rows.append({
            "name": strat_name,
            "n_factors": len(STRATEGIES[strat_name]),
            "months": n,
            "ic": avg_ic,
            "ic_pos": ic_pos,
            "excess": avg_excess,
            "excess_pos": excess_pos,
            "ls": avg_ls,
            "ls_pos": ls_pos,
            "bot_neg": bot_neg,
            "sharpe": sharpe,
            "maxdd": maxdd,
            "cum": cum_ret,
        })

    sdf = pd.DataFrame(summary_rows)

    print(f"\n  {'策略':>18} {'因子':>4} {'IC':>7} {'IC正':>5} {'超額':>7} {'超正':>5}"
          f" {'L-S':>7} {'LS正':>5} {'Bot虧':>5} {'Shrp':>6} {'MDD':>7} {'累積':>7}")
    print("  " + "─" * 110)

    baseline_ic = None
    for _, r in sdf.iterrows():
        if baseline_ic is None:
            baseline_ic = r["ic"]
        ic_delta = r["ic"] - baseline_ic if baseline_ic else 0
        marker = " ★" if ic_delta > 0.005 else ""

        print(f"  {r['name']:>18} {r['n_factors']:>4} {r['ic']:>+7.4f} {r['ic_pos']:>4.0%}"
              f" {r['excess']:>+6.2f}% {r['excess_pos']:>4.0%}"
              f" {r['ls']:>+6.2f}% {r['ls_pos']:>4.0%}"
              f" {r['bot_neg']:>4.0%} {r['sharpe']:>6.2f} {r['maxdd']:>6.1f}%"
              f" {r['cum']:>+6.1f}%{marker}")

    # ── 逐月明細（最佳策略 vs baseline）──
    best = sdf.loc[sdf["ic"].idxmax()]
    best_name = best["name"]
    print(f"\n  最佳策略: {best_name} (IC={best['ic']:+.4f})")

    if best_name != "A_baseline_9":
        print(f"\n  ── 逐月比較: {best_name} vs A_baseline_9 ──")
        bdf = pd.DataFrame(results[best_name])
        adf = pd.DataFrame(results["A_baseline_9"])
        merged = bdf.merge(adf, on="ym", suffixes=("_best", "_base"))

        print(f"  {'月份':>8} {'IC_base':>8} {'IC_best':>8} {'ΔIC':>8}"
              f" {'超額_base':>9} {'超額_best':>9} {'Δ超額':>8}")
        print("  " + "─" * 65)

        for _, r in merged.iterrows():
            dic = r["ic_best"] - r["ic_base"] if not np.isnan(r["ic_best"]) and not np.isnan(r["ic_base"]) else np.nan
            de = (r["excess_best"] - r["excess_base"]) * 100

            dic_str = f"{dic:>+8.4f}" if not np.isnan(dic) else f"{'N/A':>8}"
            print(f"  {r['ym']:>8} {r['ic_base']:>+8.4f} {r['ic_best']:>+8.4f} {dic_str}"
                  f" {r['excess_base']*100:>+8.2f}% {r['excess_best']*100:>+8.2f}% {de:>+7.2f}%")

        # 統計檢定
        valid = merged.dropna(subset=["ic_best", "ic_base"])
        if len(valid) >= 5:
            t, p = stats.ttest_rel(valid["ic_best"], valid["ic_base"])
            ic_improvement = (valid["ic_best"].mean() - valid["ic_base"].mean())
            print(f"\n  配對 t 檢定（IC 差異）: t={t:.2f}, p={p:.4f}")
            print(f"  IC 改善: {ic_improvement:+.4f}")
            if p < 0.05:
                print(f"  → ★★ 統計顯著，反向過熱因子確實有效")
            elif p < 0.1:
                print(f"  → ★ 邊際顯著")
            else:
                print(f"  → 差異不顯著")

    # ── 結論 ──
    print(f"\n{'=' * 130}")
    print(f"  結論")
    print(f"{'=' * 130}")

    baseline = sdf[sdf["name"] == "A_baseline_9"].iloc[0]
    improved = [r for _, r in sdf.iterrows() if r["ic"] > baseline["ic"] + 0.003]

    if improved:
        best_r = max(improved, key=lambda x: x["ic"])
        ic_gain = best_r["ic"] - baseline["ic"]
        print(f"\n  ★ 反向過熱因子有效")
        print(f"    最佳: {best_r['name']} → IC {baseline['ic']:+.4f} → {best_r['ic']:+.4f} (Δ={ic_gain:+.4f})")
        print(f"    超額: {baseline['excess']:+.2f}% → {best_r['excess']:+.2f}%")
        print(f"    L-S: {baseline['ls']:+.2f}% → {best_r['ls']:+.2f}%")
        print(f"    建議更新線上模型的因子清單")
    else:
        print(f"\n  ✗ 反向過熱因子未能顯著提升 IC")
        print(f"    不建議修改現有模型")


def main() -> None:
    print("=== 反向過熱因子 Walk-Forward 驗證 ===\n")
    df = load_data()
    print(f"Data: {len(df):,} rows, {df['date'].min().date()} ~ {df['date'].max().date()}")
    run_walkforward(df)


if __name__ == "__main__":
    main()

"""
Phase 4: 贏家因子 ML Walk-Forward 驗證

將 Phase 1 篩選出的 4 個贏家因子加入 baseline 9 因子，
用 LightGBM Ensemble 跑完整 walk-forward。

策略組合：
  A) baseline 9 因子（對照組）
  B) +high_52w_ratio（52 週高點效應，唯一正 L-S 因子）
  C) +neg_ivol_20d（低波動異象，最高 IC）
  D) +yield_x_roe（品質×價值交互，最高 t 值）
  E) +neg_skew_20d（反右偏，最高一致性）
  F) +high_52w + neg_ivol（動量+波動率）
  G) +high_52w + yield_x_roe（動量+品質）
  H) +high_52w + neg_ivol + yield_x_roe + neg_skew（全部 4 因子）
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
    "A_base9":          BASE,
    "B_+52wHigh":       BASE + ["high_52w_ratio"],
    "C_+negIVol":       BASE + ["neg_ivol_20d"],
    "D_+yieldROE":      BASE + ["yield_x_roe"],
    "E_+negSkew":       BASE + ["neg_skew_20d"],
    "F_+52w+iVol":      BASE + ["high_52w_ratio", "neg_ivol_20d"],
    "G_+52w+yROE":      BASE + ["high_52w_ratio", "yield_x_roe"],
    "H_all4_winners":   BASE + ["high_52w_ratio", "neg_ivol_20d", "yield_x_roe", "neg_skew_20d"],
}


def load_data() -> pd.DataFrame:
    print("載入資料 ...", flush=True)

    # stock_features (基本面 + 籌碼)
    feature_cols = list(set(
        ["stock_id", "date", "close", "ma60", "yield_rate", "roe"]
        + BASE
    ))
    sql_feat = text(f"""
        SELECT {', '.join(feature_cols)}
        FROM stock_features
        WHERE close > 0 AND date >= '2022-06-01'
        ORDER BY stock_id, date
    """)
    feat = pd.read_sql(sql_feat, engine)
    feat["date"] = pd.to_datetime(feat["date"])
    print(f"  features: {len(feat):,} 筆")

    # stock_prices (OHLC for new factors)
    sql_price = text("""
        SELECT stock_id, date, open, high, low, close, volume
        FROM stock_prices
        WHERE date >= '2022-01-01' AND close > 0 AND volume > 0
        ORDER BY stock_id, date
    """)
    price = pd.read_sql(sql_price, engine)
    price["date"] = pd.to_datetime(price["date"])
    print(f"  prices: {len(price):,} 筆")

    # ── 從 price 計算新因子 ──
    print("計算新因子 ...", flush=True)
    price = price.sort_values(["stock_id", "date"])
    gp = price.groupby("stock_id")

    # 1. high_52w_ratio
    price["high_52w"] = gp["high"].transform(
        lambda x: x.rolling(250, min_periods=60).max()
    )
    price["high_52w_ratio"] = price["close"] / price["high_52w"]

    # 2. neg_ivol_20d (idiosyncratic volatility)
    price["ret"] = gp["close"].pct_change()
    daily_mkt = price.groupby("date")["ret"].median()
    price["mkt_ret"] = price["date"].map(daily_mkt)
    price["excess_ret"] = price["ret"] - price["mkt_ret"]
    price["ivol_20d"] = gp["excess_ret"].transform(
        lambda x: x.rolling(20, min_periods=10).std()
    )
    price["neg_ivol_20d"] = -price["ivol_20d"]

    # 3. yield_x_roe (computed after merge with features)

    # 4. neg_skew_20d
    price["skew_20d"] = gp["ret"].transform(
        lambda x: x.rolling(20, min_periods=15).skew()
    )
    price["neg_skew_20d"] = -price["skew_20d"]

    # ── 合併 ──
    new_cols = ["stock_id", "date", "high_52w_ratio", "neg_ivol_20d", "neg_skew_20d"]
    df = pd.merge(feat, price[new_cols], on=["stock_id", "date"], how="left")

    # yield_x_roe (from features)
    df["yield_x_roe"] = df["yield_rate"] * df["roe"]

    # Forward return
    df = df.sort_values(["stock_id", "date"])
    g = df.groupby("stock_id")
    df["entry"] = g["close"].shift(-GAP)
    df["exit"] = g["close"].shift(-(GAP + HOLD))
    df["fwd_ret"] = (df["exit"] - df["entry"]) / df["entry"]

    # 過濾到有覆蓋的期間
    df = df[df["date"] >= "2023-03-01"].copy()
    df["ym"] = df["date"].dt.to_period("M")

    print(f"  合併完成: {len(df):,} 筆, 有 fwd_ret: {df.dropna(subset=['fwd_ret']).shape[0]:,}")
    return df


def train_models(
    train: pd.DataFrame, factors: List[str]
) -> tuple | None:
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

    results: Dict[str, List[dict]] = {name: [] for name in STRATEGIES}

    test_start = TRAIN_MONTHS
    n_test = len(months) - test_start
    print(f"\n測試窗口: {n_test} 個月 ({months[test_start]} ~ {months[-1]})\n")

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

                ic, _ = stats.spearmanr(valid["score"], valid["fwd_ret"])
                if np.isnan(ic):
                    continue
                daily_ics.append(ic)

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
    print("  Phase 4: 贏家因子 ML Walk-Forward 驗證")
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
    baseline_ls = sdf[sdf["name"] == "A_base9"]["ls"].iloc[0]

    print(f"\n  ── 排名（按 IC 排序）──")
    ranked = sdf.sort_values("ic", ascending=False)
    for rank, (_, r) in enumerate(ranked.iterrows(), 1):
        delta_ic = r["ic"] - baseline_ic
        delta_ls = r["ls"] - baseline_ls
        marker = " ★★" if delta_ic > 0.01 else " ★" if delta_ic > 0.005 else ""
        print(f"  {rank}. {r['name']:>20} IC={r['ic']:+.4f} (ΔIC={delta_ic:+.4f})"
              f" L-S={r['ls']:+.2f}% (ΔLS={delta_ls:+.2f}%)"
              f" Sharpe={r['sharpe']:.2f}{marker}")

    # ── 最佳策略 vs baseline 配對 t 檢定 ──
    best_name = ranked.iloc[0]["name"]
    if best_name != "A_base9":
        base_ics = pd.DataFrame(results["A_base9"])
        best_ics = pd.DataFrame(results[best_name])
        merged = pd.merge(
            base_ics[["ym", "ic_mean"]].rename(columns={"ic_mean": "base_ic"}),
            best_ics[["ym", "ic_mean"]].rename(columns={"ic_mean": "best_ic"}),
            on="ym",
        )
        if len(merged) > 5:
            diff = merged["best_ic"] - merged["base_ic"]
            t_stat, p_val = stats.ttest_rel(merged["best_ic"], merged["base_ic"])
            print(f"\n  ── {best_name} vs A_base9 配對 t 檢定 ──")
            print(f"     IC 差異均值: {diff.mean():+.4f}")
            print(f"     t = {t_stat:.3f}, p = {p_val:.4f}")
            if p_val < 0.05:
                print(f"     ✓ 統計顯著 (p < 0.05)")
            elif p_val < 0.10:
                print(f"     ~ 邊際顯著 (p < 0.10)")
            else:
                print(f"     ✗ 不顯著 (p >= 0.10)")

    # ── 逐年對比（baseline vs best）──
    if best_name != "A_base9":
        print(f"\n  ── 逐年 IC 對比：A_base9 vs {best_name} ──")
        base_df = pd.DataFrame(results["A_base9"])
        best_df = pd.DataFrame(results[best_name])
        base_df["year"] = base_df["ym"].str[:4]
        best_df["year"] = best_df["ym"].str[:4]

        print(f"  {'年':>6} {'Base IC':>8} {'Best IC':>8} {'差異':>8} {'Base L-S':>8} {'Best L-S':>8}")
        print("  " + "─" * 55)
        for yr in sorted(base_df["year"].unique()):
            b_yr = base_df[base_df["year"] == yr]
            t_yr = best_df[best_df["year"] == yr]
            b_ic = b_yr["ic_mean"].mean() if len(b_yr) else 0
            t_ic = t_yr["ic_mean"].mean() if len(t_yr) else 0
            b_ls = b_yr["ls"].mean() * 100 if len(b_yr) else 0
            t_ls = t_yr["ls"].mean() * 100 if len(t_yr) else 0
            print(f"  {yr:>6} {b_ic:>+8.4f} {t_ic:>+8.4f} {t_ic-b_ic:>+8.4f}"
                  f" {b_ls:>+7.2f}% {t_ls:>+7.2f}%")

    print(f"\n{'=' * 140}")
    print("  Phase 4 完成")
    print(f"{'=' * 140}\n")


if __name__ == "__main__":
    df = load_data()
    run_research(df)

"""
融券軋空因子 ML Walk-Forward 驗證
=================================
Partial IC 顯示 short_chg_5d (t=7.68) 和 short_chg_20d (t=11.40)
與現有 11 因子高度正交。本腳本用 LightGBM walk-forward 驗證加入後能否提升。

策略：
  A) baseline 11 因子（現有模型）
  B) +short_chg_5d（融券 5d 變化）
  C) +short_chg_20d（融券 20d 變化）
  D) +5d+20d（兩個都加）

使用: cd backend && ./.venv/bin/python scripts/research_short_squeeze_validation.py
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

# 現有 11 因子 baseline（20d 模型）
BASE = [
    "roe", "yield_rate", "pb_ratio", "revenue_yoy",
    "rev_surprise", "rev_accel",
    "foreign_hold_chg_5d", "dealer_buy_20d", "vol_ratio",
    "neg_ivol_20d", "neg_trust_net_buy",
]

STRATEGIES: Dict[str, List[str]] = {
    "A_base11":         BASE,
    "B_+short5d":       BASE + ["short_chg_5d"],
    "C_+short20d":      BASE + ["short_chg_20d"],
    "D_+short5d20d":    BASE + ["short_chg_5d", "short_chg_20d"],
}


def load_data() -> pd.DataFrame:
    print("載入資料 ...", flush=True)

    feat = pd.read_sql(text(
        "SELECT stock_id, date, close, roe, yield_rate, pb_ratio, revenue_yoy,"
        " rev_surprise, rev_accel, foreign_hold_chg_5d, dealer_buy_20d,"
        " vol_ratio, ivol_20d, trust_net_buy"
        " FROM stock_features WHERE close > 0 AND date >= :start"
        " ORDER BY stock_id, date"
    ), engine, params={"start": "2022-06-01"})
    feat["date"] = pd.to_datetime(feat["date"])
    print(f"  features: {len(feat):,}")

    chip = pd.read_sql(text(
        "SELECT stock_id, date, short_balance"
        " FROM stock_chip_data WHERE date >= :start"
        " ORDER BY stock_id, date"
    ), engine, params={"start": "2022-06-01"})
    chip["date"] = pd.to_datetime(chip["date"])
    print(f"  chip: {len(chip):,}")

    # 合併
    df = feat.merge(chip, on=["stock_id", "date"], how="left")
    df = df.sort_values(["stock_id", "date"])
    g = df.groupby("stock_id")

    # neg 翻轉
    df["neg_ivol_20d"] = -df["ivol_20d"]
    df["neg_trust_net_buy"] = -df["trust_net_buy"]

    # 新因子
    df["short_chg_5d"] = g["short_balance"].transform(
        lambda x: (x - x.shift(5)) / x.shift(5).replace(0, np.nan)
    )
    df["short_chg_20d"] = g["short_balance"].transform(
        lambda x: (x - x.shift(20)) / x.shift(20).replace(0, np.nan)
    )

    # Forward return
    df["fwd_ret"] = g["close"].transform(
        lambda x: x.shift(-GAP - HOLD) / x.shift(-GAP) - 1
    )

    df = df[df["date"] >= "2023-03-01"].copy()
    df["ym"] = df["date"].dt.to_period("M")

    print(f"  合併完成: {len(df):,}, fwd_ret 有效: {df['fwd_ret'].notna().sum():,}")
    return df


def train_models(train: pd.DataFrame, factors: List[str]):
    t = train.dropna(subset=["fwd_ret"]).copy()
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


def predict_day(clf, reg, rank_cols, factors, day_data):
    s = day_data.copy()
    if len(s) < 50:
        return None

    for f, rc in zip(factors, rank_cols):
        s[rc] = s[f].rank(pct=True)

    X = s[rank_cols].values
    score = clf.predict_proba(X)[:, 1] * 0.5 + \
            pd.Series(reg.predict(X)).rank(pct=True).values * 0.5
    return pd.Series(score, index=s.index)


def main():
    df = load_data()
    months = sorted(df["ym"].unique())

    results: Dict[str, List[dict]] = {name: [] for name in STRATEGIES}

    test_start = TRAIN_MONTHS
    n_test = len(months) - test_start
    print(f"\n測試: {n_test} 個月 ({months[test_start]} ~ {months[-1]})")

    for i in range(test_start, len(months)):
        test_month = months[i]
        train_months = months[i - TRAIN_MONTHS:i]
        train = df[df["ym"].isin(train_months)]
        test = df[df["ym"] == test_month]
        test_dates = sorted(test["date"].unique())
        if not test_dates:
            continue

        print(f"  {test_month}: {len(test_dates)}d", end="", flush=True)

        for strat_name, factors in STRATEGIES.items():
            models = train_models(train, factors)
            if models is None:
                continue
            clf, reg, rank_cols = models

            daily_ics, daily_tops, daily_bots, daily_mkts = [], [], [], []

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
                top5 = valid.nlargest(5, "score")["fwd_ret"]
                bot5 = valid.nsmallest(5, "score")["fwd_ret"]
                mkt = valid["fwd_ret"]

                daily_tops.append(top5.mean())
                daily_bots.append(bot5.mean())
                daily_mkts.append(mkt.mean())

            if not daily_ics:
                continue

            results[strat_name].append({
                "ym": str(test_month),
                "ic_mean": np.mean(daily_ics),
                "n_days": len(daily_ics),
                "top5": np.mean(daily_tops),
                "bot5": np.mean(daily_bots),
                "mkt": np.mean(daily_mkts),
                "excess": np.mean(daily_tops) - np.mean(daily_mkts),
                "ls": np.mean(daily_tops) - np.mean(daily_bots),
            })

        print(" ok")

    # 結果
    print(f"\n{'=' * 110}")
    print("  融券軋空因子 Walk-Forward 驗證結果")
    print(f"{'=' * 110}")
    print(f"  {'策略':>18} {'N因子':>5} {'月':>3} {'IC':>8} {'IC正%':>6}"
          f" {'Top5月報酬':>10} {'超額':>8} {'L-S':>8} {'Sharpe':>7} {'MDD':>7}")
    print("  " + "-" * 95)

    all_summaries = []
    for strat_name in STRATEGIES:
        ms = results[strat_name]
        if not ms:
            continue
        mdf = pd.DataFrame(ms)
        n = len(mdf)
        nf = len(STRATEGIES[strat_name])

        avg_ic = mdf["ic_mean"].mean()
        ic_pos = (mdf["ic_mean"] > 0).mean() * 100
        avg_top5 = mdf["top5"].mean() * 100
        avg_excess = mdf["excess"].mean() * 100
        avg_ls = mdf["ls"].mean() * 100

        me = mdf["excess"].values
        sharpe = np.mean(me) / np.std(me, ddof=1) * np.sqrt(12) if np.std(me, ddof=1) > 0 else 0
        cum = (1 + mdf["top5"] - COST).cumprod()
        maxdd = ((cum - cum.cummax()) / cum.cummax()).min() * 100

        print(f"  {strat_name:>18} {nf:>5} {n:>3} {avg_ic:>+.4f} {ic_pos:>5.0f}%"
              f" {avg_top5:>+9.2f}% {avg_excess:>+7.2f}% {avg_ls:>+7.2f}%"
              f" {sharpe:>7.2f} {maxdd:>+6.1f}%")

        all_summaries.append({
            "name": strat_name, "ic": avg_ic, "excess": avg_excess,
            "ls": avg_ls, "sharpe": sharpe, "mdf": mdf,
        })

    # 統計檢定
    if len(all_summaries) >= 2:
        base_mdf = all_summaries[0]["mdf"]
        print(f"\n  --- 統計檢定 (paired t-test vs baseline) ---")
        for s in all_summaries[1:]:
            test_mdf = s["mdf"]
            common = base_mdf.merge(test_mdf, on="ym", suffixes=("_b", "_t"))
            if len(common) < 5:
                continue
            t_stat, p_val = stats.ttest_rel(common["ic_mean_t"], common["ic_mean_b"])
            sig = "✓ 顯著" if p_val < 0.05 else "✗ 不顯著"
            print(f"    {s['name']:>18}: ΔIC={common['ic_mean_t'].mean() - common['ic_mean_b'].mean():+.4f}"
                  f"  t={t_stat:+.3f}  p={p_val:.4f}  {sig}")

    print(f"\n{'=' * 110}")


if __name__ == "__main__":
    main()

"""
常識過濾驗證：ROE>0 + 營收YoY>-50% 是否改善推薦品質

比較：
A) 無過濾（baseline）
B) 做多排除 ROE≤0 或 營收YoY<-50%
C) 做空排除殖利率>6%
D) 做多+做空同時過濾

用 walk-forward 每月訓練/測試，比較 Top5/Bot5 報酬和勝率。
"""
from __future__ import annotations
import os, warnings
import numpy as np
import pandas as pd
from scipy import stats
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sqlalchemy import create_engine, text

warnings.filterwarnings("ignore")
PG_URL = os.getenv("PG_URL", "postgresql://alphaforge:alphaforge_secret@10.0.4.3:5433/alphaforge")
engine = create_engine(PG_URL)

HOLD = 20
GAP = 1
TRAIN_MONTHS = 12

FACTORS = [
    "roe", "yield_rate", "pb_ratio", "revenue_yoy",
    "rev_surprise", "rev_accel",
    "foreign_hold_chg_5d", "dealer_buy_20d", "vol_ratio",
    "ivol_20d", "neg_trust_net_buy",
]


def load_data() -> pd.DataFrame:
    raw_cols = set()
    for f in FACTORS:
        raw_cols.add(f.replace("neg_", "") if f.startswith("neg_") else f)
    raw_cols.update(["stock_id", "date", "close", "ma60", "trust_net_buy"])

    sql = text(f"SELECT {', '.join(raw_cols)} FROM stock_features WHERE close > 0 AND date >= '2023-03-01' ORDER BY date, stock_id")
    print("  Loading data...")
    df = pd.read_sql(sql, engine)
    df["date"] = pd.to_datetime(df["date"])
    df["neg_trust_net_buy"] = -df["trust_net_buy"].fillna(0)

    df = df.sort_values(["stock_id", "date"])
    df["entry"] = df.groupby("stock_id")["close"].shift(-GAP)
    df["exit"] = df.groupby("stock_id")["close"].shift(-(GAP + HOLD))
    df["fwd_ret"] = (df["exit"] - df["entry"]) / df["entry"]
    df["ym"] = df["date"].dt.to_period("M")
    return df


def train_and_score(train: pd.DataFrame, test_day: pd.DataFrame):
    """訓練 ensemble，回傳 test_day 的 scores"""
    t = train.dropna(subset=["fwd_ret"]).copy()
    if len(t) < 500:
        return None

    rank_cols = []
    for f in FACTORS:
        rc = f"{f}_r"
        filled = t.groupby("date")[f].transform(lambda x: x.fillna(x.median()))
        t[rc] = t.groupby("date")[filled.name].rank(pct=True).fillna(0.5)
        rank_cols.append(rc)

    X = t[rank_cols].values
    y = (t["fwd_ret"] > t["fwd_ret"].median()).astype(int).values

    clf = HistGradientBoostingClassifier(max_iter=150, max_depth=4, random_state=42)
    reg = HistGradientBoostingRegressor(max_iter=150, max_depth=4, random_state=42)
    clf.fit(X, y)
    reg.fit(X, t["fwd_ret"].clip(-0.5, 0.5).values)

    # Score test day
    s = test_day.copy()
    for f, rc in zip(FACTORS, rank_cols):
        filled = s[f].fillna(s[f].median())
        s[rc] = filled.rank(pct=True).fillna(0.5)

    X_test = s[rank_cols].values
    prob = clf.predict_proba(X_test)[:, 1] * 0.5
    reg_pred = reg.predict(X_test)
    reg_rank = pd.Series(reg_pred, index=s.index).rank(pct=True).values
    score = prob + reg_rank * 0.5

    return pd.Series(score, index=s.index)


def apply_filters(df_day: pd.DataFrame, scores: pd.Series, filter_type: str):
    """依 filter_type 過濾後取 Top5/Bot5"""
    df_day = df_day.copy()
    df_day["score"] = scores

    valid = df_day.dropna(subset=["score", "fwd_ret"])
    if len(valid) < 50:
        return None

    # 做多候選
    long_pool = valid.copy()
    if filter_type in ("B", "D"):
        long_pool = long_pool[
            (long_pool["roe"].fillna(0) > 0) &
            (long_pool["revenue_yoy"].fillna(0) > -50)
        ]

    # 做空候選
    short_pool = valid.copy()
    if filter_type in ("C", "D"):
        short_pool = short_pool[
            short_pool["yield_rate"].fillna(0) <= 6
        ]

    top5 = long_pool.nlargest(5, "score")["fwd_ret"] if len(long_pool) >= 5 else pd.Series(dtype=float)
    bot5 = short_pool.nsmallest(5, "score")["fwd_ret"] if len(short_pool) >= 5 else pd.Series(dtype=float)

    if top5.empty and bot5.empty:
        return None

    return {
        "top5_ret": top5.mean() if not top5.empty else np.nan,
        "top5_wr": (top5 > 0).mean() if not top5.empty else np.nan,
        "bot5_ret": bot5.mean() if not bot5.empty else np.nan,
        "bot5_neg_wr": (bot5 < 0).mean() if not bot5.empty else np.nan,
        "top5_roe0": (top5.index.isin(valid[valid["roe"].fillna(0) <= 0].index)).sum() if not top5.empty else 0,
    }


def main():
    print("=" * 70)
    print("  常識過濾驗證：ROE>0 + 營收>-50% + 殖利率<6%")
    print("=" * 70)

    df = load_data()
    months = sorted(df["ym"].unique())
    print(f"  Data: {len(df):,} rows, {len(months)} months\n")

    filters = {
        "A_無過濾": "A",
        "B_做多過濾": "B",
        "C_做空過濾": "C",
        "D_雙向過濾": "D",
    }

    results = {name: [] for name in filters}

    for i in range(TRAIN_MONTHS, len(months)):
        test_month = months[i]
        train_months = months[i - TRAIN_MONTHS:i]

        train = df[df["ym"].isin(train_months)].copy()
        test = df[df["ym"] == test_month].copy()
        test_dates = sorted(test["date"].unique())
        if not test_dates:
            continue

        print(f"  {test_month} ({len(test_dates)}d)", end="", flush=True)

        # 每月訓練一次
        models_ok = False
        daily_results = {name: [] for name in filters}

        for td in test_dates:
            day_data = test[test["date"] == td]
            if len(day_data) < 100:
                continue

            if not models_ok:
                scores = train_and_score(train, day_data)
                if scores is None:
                    continue
                # 用同一個訓練好的模型，但需要每天重新 score
                # 為簡化，每月只訓練一次，每天重新 rank + predict
                models_ok = True

            scores = train_and_score(train, day_data)
            if scores is None:
                continue

            for name, ftype in filters.items():
                r = apply_filters(day_data, scores, ftype)
                if r:
                    daily_results[name].append(r)

        for name in filters:
            dr = daily_results[name]
            if dr:
                results[name].append({
                    "ym": str(test_month),
                    "top5_ret": np.nanmean([r["top5_ret"] for r in dr]),
                    "top5_wr": np.nanmean([r["top5_wr"] for r in dr]),
                    "bot5_ret": np.nanmean([r["bot5_ret"] for r in dr]),
                    "bot5_neg_wr": np.nanmean([r["bot5_neg_wr"] for r in dr]),
                    "top5_roe0": np.mean([r["top5_roe0"] for r in dr]),
                })

        print(" ✓")

    # ═══ 結果 ═══
    print(f"\n{'=' * 90}")
    print(f"  {'策略':>15} {'月數':>4} {'Top5月報酬':>10} {'做多WR':>8} {'Bot5月報酬':>10} {'做空WR':>8} {'Top5含ROE0':>10}")
    print("  " + "─" * 75)

    for name in filters:
        ms = results[name]
        if not ms:
            continue
        mdf = pd.DataFrame(ms)
        print(f"  {name:>15} {len(mdf):>4}"
              f" {mdf['top5_ret'].mean()*100:>+9.2f}%"
              f" {mdf['top5_wr'].mean()*100:>7.1f}%"
              f" {mdf['bot5_ret'].mean()*100:>+9.2f}%"
              f" {mdf['bot5_neg_wr'].mean()*100:>7.1f}%"
              f" {mdf['top5_roe0'].mean():>9.1f}")

    # 配對 t 檢定：D vs A
    a_df = pd.DataFrame(results["A_無過濾"])
    d_df = pd.DataFrame(results["D_雙向過濾"])
    if len(a_df) >= 5 and len(d_df) >= 5:
        merged = a_df.merge(d_df, on="ym", suffixes=("_a", "_d"))
        t_top, p_top = stats.ttest_rel(merged["top5_ret_d"], merged["top5_ret_a"])
        t_bot, p_bot = stats.ttest_rel(merged["bot5_ret_d"], merged["bot5_ret_a"])
        print(f"\n  配對 t 檢定 (D雙向 vs A無過濾):")
        print(f"    做多 Top5: t={t_top:.2f}, p={p_top:.4f} {'✓顯著' if p_top<0.1 else ''}")
        print(f"    做空 Bot5: t={t_bot:.2f}, p={p_bot:.4f} {'✓顯著' if p_bot<0.1 else ''}")

    # 逐年比較
    print(f"\n  ── 逐年比較：A_無過濾 vs D_雙向過濾 ──")
    print(f"  {'年':>6} {'A_Top5':>9} {'D_Top5':>9} {'Δ':>8} {'A_Bot5':>9} {'D_Bot5':>9} {'Δ':>8}")
    print("  " + "─" * 60)
    for yr in sorted(set(r["ym"][:4] for r in results["A_無過濾"])):
        a_yr = [r for r in results["A_無過濾"] if r["ym"][:4] == yr]
        d_yr = [r for r in results["D_雙向過濾"] if r["ym"][:4] == yr]
        if a_yr and d_yr:
            a_t = np.mean([r["top5_ret"] for r in a_yr]) * 100
            d_t = np.mean([r["top5_ret"] for r in d_yr]) * 100
            a_b = np.mean([r["bot5_ret"] for r in a_yr]) * 100
            d_b = np.mean([r["bot5_ret"] for r in d_yr]) * 100
            print(f"  {yr:>6} {a_t:>+8.2f}% {d_t:>+8.2f}% {d_t-a_t:>+7.2f}% {a_b:>+8.2f}% {d_b:>+8.2f}% {d_b-a_b:>+7.2f}%")


if __name__ == "__main__":
    main()

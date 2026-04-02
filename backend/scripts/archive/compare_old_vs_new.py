"""
新舊模型直接比較 — 同一時期，同一市場數據

舊模型：LogisticRegression（alpha_signal_history 中已到期的實際報酬）
新模型：LightGBM 15 穩定因子（用同期數據回算）

比較期間：2025-09 ~ 2026-03（舊信號有實際報酬的期間）
"""
from __future__ import annotations

import os
import warnings

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.ensemble import HistGradientBoostingClassifier
from sqlalchemy import create_engine, text

warnings.filterwarnings("ignore")

PG_URL = os.getenv("PG_URL", "postgresql://alphaforge:alphaforge_secret@10.0.4.3:5433/alphaforge")
engine = create_engine(PG_URL)

COST = 0.006

STABLE_15 = [
    "roe", "yield_rate", "pb_ratio", "revenue_yoy",
    "foreign_hold_chg_5d", "foreign_net_buy", "foreign_buy_5d",
    "dealer_buy_20d", "vol_ratio", "foreign_buy_10d", "price_vs_high20",
    "neg_trust_net_buy", "neg_trust_buy_5d", "neg_trust_buy_10d", "neg_trust_buy_20d",
]


def load_features():
    cols = ["stock_id", "date", "close", "ma60",
            "roe", "yield_rate", "pb_ratio", "revenue_yoy",
            "foreign_hold_chg_5d", "foreign_net_buy", "foreign_buy_5d",
            "dealer_buy_20d", "vol_ratio", "foreign_buy_10d", "price_vs_high20",
            "trust_net_buy", "trust_buy_5d", "trust_buy_10d", "trust_buy_20d"]
    sql = text(f"SELECT {', '.join(cols)} FROM stock_features WHERE close > 0 ORDER BY date, stock_id")
    df = pd.read_sql(sql, engine)
    df["date"] = pd.to_datetime(df["date"])
    # 反向投信
    for src, dst in [("trust_net_buy", "neg_trust_net_buy"), ("trust_buy_5d", "neg_trust_buy_5d"),
                     ("trust_buy_10d", "neg_trust_buy_10d"), ("trust_buy_20d", "neg_trust_buy_20d")]:
        if src in df.columns:
            df[dst] = -df[src].fillna(0)
    print(f"[Features] {len(df):,} 筆，{df['date'].min().date()} ~ {df['date'].max().date()}")
    return df


def load_old_signals():
    """載入舊 LogisticRegression 的實際績效"""
    sql = text("""
        SELECT signal_date, stock_id, stock_name, time_dimension, direction, actual_return
        FROM alpha_signal_history
        WHERE is_resolved = true AND actual_return IS NOT NULL AND direction = 'long'
    """)
    df = pd.read_sql(sql, engine)
    df["signal_date"] = pd.to_datetime(df["signal_date"])
    print(f"[Old Signals] {len(df):,} 筆，{df['signal_date'].min().date()} ~ {df['signal_date'].max().date()}")
    return df


def backtest_new_model(df_feat, test_start, test_end, forward_days=30, threshold=0.03):
    """用新 15 因子模型在指定期間做回測"""
    df = df_feat.sort_values(["stock_id", "date"]).copy()
    df["forward_close"] = df.groupby("stock_id")["close"].shift(-forward_days)
    df["forward_return"] = (df["forward_close"] - df["close"]) / df["close"]
    df["label"] = (df["forward_return"] > threshold).astype(float)

    # MA60 filter (30d production setting)
    df = df[df["close"] > df["ma60"]].copy()

    # Rank
    rank_cols = []
    for f in STABLE_15:
        if f in df.columns:
            rc = f"{f}_rank"
            df[rc] = df.groupby("date")[f].rank(pct=True, na_option="keep")
            rank_cols.append(rc)

    # Train / Test split
    gap = pd.DateOffset(months=1)
    train_end = pd.Timestamp(test_start) - gap
    train = df[df["date"] <= train_end].dropna(subset=["label"])
    test = df[(df["date"] >= pd.Timestamp(test_start)) & (df["date"] <= pd.Timestamp(test_end))].dropna(
        subset=["forward_return"])

    if len(train) < 2000 or len(test) < 200:
        print(f"  樣本不足: train={len(train)}, test={len(test)}")
        return None

    # Time weights
    base_year = train_end.year
    w = np.clip(1.0 - 0.2 * (base_year - train["date"].dt.year), 0.2, 1.0).values

    # Train
    model = HistGradientBoostingClassifier(
        max_iter=200, max_depth=4, max_leaf_nodes=15,
        learning_rate=0.01, min_samples_leaf=100,
        l2_regularization=1.0, random_state=42, verbose=0,
        class_weight="balanced")
    model.fit(train[rank_cols].values, train["label"].values, sample_weight=w)

    # Predict
    prob = model.predict_proba(test[rank_cols].values)[:, 1]
    test = test.copy()
    test["_prob"] = prob

    # 每日選 Top 10%
    daily_results = []
    for dt, grp in test.groupby("date"):
        if len(grp) < 50:
            continue
        cutoff = np.percentile(grp["_prob"].values, 90)
        top = grp[grp["_prob"] >= cutoff]
        mkt = grp

        top_ret = top["forward_return"].mean()
        mkt_ret = mkt["forward_return"].mean()
        n_picks = len(top)

        # IC
        p, r = grp["_prob"].values, grp["forward_return"].values
        valid = ~np.isnan(r)
        ic = stats.spearmanr(p[valid], r[valid])[0] if valid.sum() > 30 else 0

        daily_results.append({
            "date": dt, "top_ret": top_ret, "mkt_ret": mkt_ret,
            "excess": top_ret - mkt_ret, "n_picks": n_picks, "ic": ic,
        })

    return pd.DataFrame(daily_results)


def main():
    df_feat = load_features()
    old_signals = load_old_signals()

    print("\n" + "=" * 70)
    print("  新舊模型直接比較")
    print("=" * 70)

    # ── 舊模型績效（實際數據）──────────────────────────────────────
    for dim in ["30d", "10d"]:
        dim_data = old_signals[old_signals["time_dimension"] == dim]
        if dim_data.empty:
            continue

        fwd_days = 30 if dim == "30d" else 10

        print(f"\n{'─' * 70}")
        print(f"  {dim} 做多 比較")
        print(f"{'─' * 70}")

        # 舊模型統計
        old_ret = dim_data["actual_return"].values
        old_avg = np.mean(old_ret)
        old_median = np.median(old_ret)
        old_wr = np.mean(old_ret > 0)
        old_net = old_avg - COST * 100  # actual_return 已是百分比
        # 判斷 actual_return 的單位
        if abs(old_avg) < 1:  # 小數格式（0.001 = 0.1%）
            old_avg_pct = old_avg * 100
            old_wr = np.mean(old_ret > 0)
        else:  # 百分比格式（0.1 = 0.1%）
            old_avg_pct = old_avg
            old_wr = np.mean(old_ret > 0)

        print(f"\n  舊模型（LogisticRegression 實際績效）:")
        print(f"    筆數: {len(dim_data):,}")
        print(f"    平均報酬: {old_avg_pct:+.2f}%")
        print(f"    中位數: {old_median * 100 if abs(old_median) < 1 else old_median:+.2f}%")
        print(f"    勝率（報酬 > 0）: {old_wr:.1%}")

        # 月度報酬
        dim_data = dim_data.copy()
        dim_data["_month"] = dim_data["signal_date"].dt.to_period("M")
        monthly_old = []
        for _, grp in dim_data.groupby("_month"):
            r = grp["actual_return"].mean()
            monthly_old.append(r * 100 if abs(r) < 1 else r)
        if len(monthly_old) > 2:
            sharpe_old = np.mean(monthly_old) / np.std(monthly_old) * np.sqrt(12) if np.std(monthly_old) > 0 else 0
            print(f"    月度 Sharpe: {sharpe_old:.2f}")
            print(f"    勝月: {sum(1 for x in monthly_old if x > 0)}/{len(monthly_old)}")

        # ── 新模型回測 ────────────────────────────────────────────
        test_start = dim_data["signal_date"].min().date()
        test_end = dim_data["signal_date"].max().date()

        threshold = 0.03
        print(f"\n  新模型（LightGBM 15 因子回測，{test_start} ~ {test_end}）:")

        new_results = backtest_new_model(df_feat, test_start, test_end,
                                          forward_days=fwd_days, threshold=threshold)
        if new_results is not None and not new_results.empty:
            new_avg = new_results["top_ret"].mean() * 100
            new_mkt = new_results["mkt_ret"].mean() * 100
            new_excess = new_results["excess"].mean() * 100
            new_ic = new_results["ic"].mean()
            new_wr = (new_results["top_ret"] > 0).mean()

            print(f"    交易日數: {len(new_results)}")
            print(f"    Top 10% 平均報酬: {new_avg:+.2f}%")
            print(f"    市場平均報酬: {new_mkt:+.2f}%")
            print(f"    超額報酬: {new_excess:+.2f}%")
            print(f"    勝率（報酬 > 0）: {new_wr:.1%}")
            print(f"    平均 IC: {new_ic:+.4f}")

            # 月度
            new_results["_month"] = new_results["date"].dt.to_period("M")
            monthly_new = []
            for _, grp in new_results.groupby("_month"):
                r = grp["top_ret"].mean() * 100 - COST * 100
                monthly_new.append(r)
            if len(monthly_new) > 2:
                sharpe_new = np.mean(monthly_new) / np.std(monthly_new) * np.sqrt(12) if np.std(monthly_new) > 0 else 0
                print(f"    月度 Sharpe: {sharpe_new:.2f}")
                print(f"    勝月: {sum(1 for x in monthly_new if x > 0)}/{len(monthly_new)}")

            # ── 對比 ──────────────────────────────────────────────
            print(f"\n  {'指標':>12} {'舊(LR)':>10} {'新(LGB15)':>10} {'差異':>10}")
            print(f"  {'─' * 45}")
            print(f"  {'平均報酬':>12} {old_avg_pct:>+9.2f}% {new_avg:>+9.2f}% {new_avg - old_avg_pct:>+9.2f}%")
            print(f"  {'勝率':>12} {old_wr:>9.1%} {new_wr:>9.1%} {new_wr - old_wr:>+9.1%}")
            if len(monthly_old) > 2 and len(monthly_new) > 2:
                print(f"  {'Sharpe':>12} {sharpe_old:>10.2f} {sharpe_new:>10.2f} {sharpe_new - sharpe_old:>+10.2f}")


if __name__ == "__main__":
    main()

"""
診斷 20d 模型 Bottom 10% 為什麼還是賺錢
分析：Bot10% 的因子特徵、行業分佈、模型分數分佈
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

STABLE_15 = [
    "roe", "yield_rate", "pb_ratio", "revenue_yoy",
    "foreign_hold_chg_5d", "foreign_net_buy", "foreign_buy_5d",
    "dealer_buy_20d", "vol_ratio", "foreign_buy_10d", "price_vs_high20",
    "neg_trust_net_buy", "neg_trust_buy_5d", "neg_trust_buy_10d", "neg_trust_buy_20d",
]

FACTOR_LABELS = {
    "roe": "ROE", "yield_rate": "殖利率", "pb_ratio": "股淨比", "revenue_yoy": "營收YoY",
    "foreign_hold_chg_5d": "外資持股變化", "foreign_net_buy": "外資淨買", "foreign_buy_5d": "外資5日",
    "dealer_buy_20d": "自營20日", "vol_ratio": "量比", "foreign_buy_10d": "外資10日",
    "price_vs_high20": "距20日高", "neg_trust_net_buy": "反投信淨買",
    "neg_trust_buy_5d": "反投信5日", "neg_trust_buy_10d": "反投信10日", "neg_trust_buy_20d": "反投信20日",
}


def load_data():
    cols = ["stock_id", "date", "close", "ma60",
            "roe", "yield_rate", "pb_ratio", "revenue_yoy",
            "foreign_hold_chg_5d", "foreign_net_buy", "foreign_buy_5d",
            "dealer_buy_20d", "vol_ratio", "foreign_buy_10d", "price_vs_high20",
            "trust_net_buy", "trust_buy_5d", "trust_buy_10d", "trust_buy_20d"]
    sql = text(f"SELECT {', '.join(cols)} FROM stock_features "
               f"WHERE close > 0 AND date >= '2023-03-01' ORDER BY date, stock_id")
    df = pd.read_sql(sql, engine)
    df["date"] = pd.to_datetime(df["date"])
    for s, d in [("trust_net_buy", "neg_trust_net_buy"),
                 ("trust_buy_5d", "neg_trust_buy_5d"),
                 ("trust_buy_10d", "neg_trust_buy_10d"),
                 ("trust_buy_20d", "neg_trust_buy_20d")]:
        if s in df.columns:
            df[d] = -df[s]
    return df


def main():
    df_raw = load_data()
    df = df_raw.sort_values(["stock_id", "date"]).copy()

    # gap=1 forward return
    df["entry_close"] = df.groupby("stock_id")["close"].shift(-1)
    df["exit_close"] = df.groupby("stock_id")["close"].shift(-21)
    df["forward_return"] = (df["exit_close"] - df["entry_close"]) / df["entry_close"]
    df["label"] = np.where(df["forward_return"].isna(), np.nan,
                           (df["forward_return"] > 0.03).astype(float))

    for f in STABLE_15:
        if f in df.columns:
            df[f"{f}_rank"] = df.groupby("date")[f].rank(pct=True, na_option="keep")

    rc = [f"{f}_rank" for f in STABLE_15 if f"{f}_rank" in df.columns]

    # 用最近的一個訓練窗口
    max_date = df["date"].max()
    test_start = max_date - pd.DateOffset(months=6)
    train_end = test_start - pd.DateOffset(months=1)

    train = df[df["date"] <= train_end].dropna(subset=["label"])
    test = df[(df["date"] >= test_start)].dropna(subset=["label", "forward_return"])

    X_tr, y_tr = train[rc].values, train["label"].values
    w = np.clip(1.0 - 0.2 * (train_end.year - train["date"].dt.year), 0.2, 1.0).values

    clf = HistGradientBoostingClassifier(
        max_iter=200, max_depth=4, max_leaf_nodes=15,
        learning_rate=0.01, min_samples_leaf=100, l2_regularization=1.0,
        random_state=42, class_weight="balanced")
    clf.fit(X_tr, y_tr, sample_weight=w)

    reg = HistGradientBoostingRegressor(
        max_iter=200, max_depth=4, max_leaf_nodes=15,
        learning_rate=0.01, min_samples_leaf=100, l2_regularization=1.0,
        random_state=42)
    reg.fit(X_tr, train["forward_return"].values.clip(-0.5, 0.5), sample_weight=w)

    p_clf = clf.predict_proba(test[rc].values)[:, 1]
    p_reg = reg.predict(test[rc].values)
    rmin, rmax = reg.predict(X_tr).min(), reg.predict(X_tr).max()
    p_reg_n = np.clip((p_reg - rmin) / (rmax - rmin + 1e-9), 0, 1)
    prob = 0.5 * p_clf + 0.5 * p_reg_n

    test = test.copy()
    test["prob"] = prob
    fwd = test["forward_return"].values

    # 分 10 等分
    test["decile"] = pd.qcut(prob, 10, labels=False, duplicates="drop")

    print(f"{'=' * 70}")
    print(f"  模型分數 vs 實際報酬（10 等分）")
    print(f"{'=' * 70}")
    print(f"\n  {'分位':>4} {'平均分數':>8} {'平均報酬':>8} {'勝率':>6} {'檔數':>6} {'>3%':>6} {'<-3%':>6}")
    print(f"  {'─' * 60}")

    for d in range(10):
        mask = test["decile"] == d
        sub = test[mask]
        avg_prob = sub["prob"].mean()
        avg_ret = sub["forward_return"].mean()
        wr = (sub["forward_return"] > 0).mean()
        n = len(sub)
        big_win = (sub["forward_return"] > 0.03).mean()
        big_lose = (sub["forward_return"] < -0.03).mean()
        label = "← Bot10%" if d == 0 else ("← Top10%" if d == 9 else "")
        print(f"  D{d:>2}  {avg_prob:>8.3f} {avg_ret * 100:>+7.2f}% {wr:>5.0%} {n:>5} {big_win:>5.0%} {big_lose:>5.0%}  {label}")

    # Bot10% 因子特徵分析
    bot = test[test["decile"] == 0]
    top = test[test["decile"] == 9]
    mkt = test

    print(f"\n{'=' * 70}")
    print(f"  Bot10% vs Top10% 因子中位數比較")
    print(f"{'=' * 70}")
    print(f"\n  {'因子':>16} {'Bot10%':>8} {'Top10%':>8} {'市場':>8} {'差異':>8}")
    print(f"  {'─' * 55}")

    for f in STABLE_15:
        if f not in test.columns:
            continue
        bot_med = bot[f].median()
        top_med = top[f].median()
        mkt_med = mkt[f].median()
        if pd.isna(bot_med) or pd.isna(top_med):
            continue
        label = FACTOR_LABELS.get(f, f)
        diff = top_med - bot_med
        print(f"  {label:>16} {bot_med:>8.2f} {top_med:>8.2f} {mkt_med:>8.2f} {diff:>+8.2f}")

    # Bot10% 的 forward_return 分佈
    print(f"\n{'=' * 70}")
    print(f"  Bot10% 報酬分佈")
    print(f"{'=' * 70}")
    bot_ret = bot["forward_return"]
    print(f"  平均: {bot_ret.mean() * 100:+.2f}%")
    print(f"  中位: {bot_ret.median() * 100:+.2f}%")
    print(f"  標準差: {bot_ret.std() * 100:.2f}%")
    print(f"  大漲 >10%: {(bot_ret > 0.1).mean():.1%}")
    print(f"  小漲 0~5%: {((bot_ret >= 0) & (bot_ret <= 0.05)).mean():.1%}")
    print(f"  小跌 -5~0%: {((bot_ret >= -0.05) & (bot_ret < 0)).mean():.1%}")
    print(f"  大跌 <-10%: {(bot_ret < -0.1).mean():.1%}")

    # 逐月看 Bot10% 報酬
    print(f"\n{'=' * 70}")
    print(f"  Bot10% 逐月報酬")
    print(f"{'=' * 70}")
    bot["month"] = bot["date"].dt.to_period("M")
    monthly = bot.groupby("month")["forward_return"].agg(["mean", "count"])
    for m, row in monthly.iterrows():
        bar = "█" * int(abs(row["mean"]) * 200)
        sign = "+" if row["mean"] >= 0 else ""
        color = " ▲" if row["mean"] > 0.02 else (" ▼" if row["mean"] < -0.02 else "  ")
        print(f"  {str(m):>8} {sign}{row['mean'] * 100:>6.2f}% ({int(row['count']):>4}檔) {color} {bar}")


if __name__ == "__main__":
    main()

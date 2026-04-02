"""
Long-Short Walk-Forward 驗證
Top 10%（做多）vs Bottom 10%（做空）vs 市場平均
如果策略有真正 alpha，Bottom 10% 應該明顯比市場差
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
COST = 0.006

STABLE_15 = [
    "roe", "yield_rate", "pb_ratio", "revenue_yoy",
    "foreign_hold_chg_5d", "foreign_net_buy", "foreign_buy_5d",
    "dealer_buy_20d", "vol_ratio", "foreign_buy_10d", "price_vs_high20",
    "neg_trust_net_buy", "neg_trust_buy_5d", "neg_trust_buy_10d", "neg_trust_buy_20d",
]


def load_data() -> pd.DataFrame:
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
            df[d] = -df[s]  # 不 fillna(0)
    print(f"[Data] {len(df):,} 筆，{df['date'].min().date()} ~ {df['date'].max().date()}")
    return df


def prepare(df, forward_days, threshold, gap=1):
    df = df.sort_values(["stock_id", "date"]).copy()
    if gap > 0:
        df["entry_close"] = df.groupby("stock_id")["close"].shift(-gap)
        df["exit_close"] = df.groupby("stock_id")["close"].shift(-(gap + forward_days))
        df["forward_return"] = (df["exit_close"] - df["entry_close"]) / df["entry_close"]
    else:
        df["forward_close"] = df.groupby("stock_id")["close"].shift(-forward_days)
        df["forward_return"] = (df["forward_close"] - df["close"]) / df["close"]
    df["label"] = np.where(df["forward_return"].isna(), np.nan,
                           (df["forward_return"] > threshold).astype(float))
    for f in STABLE_15:
        if f in df.columns:
            df[f"{f}_rank"] = df.groupby("date")[f].rank(pct=True, na_option="keep")
    return df


def gen_windows(df, test_months=4, gap_months=1, min_train_months=8):
    mn, mx = df["date"].min(), df["date"].max()
    ts = mn + pd.DateOffset(months=min_train_months + gap_months)
    wins = []
    wid = 1
    while ts + pd.DateOffset(months=2) <= mx:
        te = min(ts + pd.DateOffset(months=test_months), mx)
        tr = ts - pd.DateOffset(months=gap_months)
        wins.append((wid, pd.Timestamp(tr), pd.Timestamp(ts), pd.Timestamp(te)))
        ts += pd.DateOffset(months=test_months)
        wid += 1
    return wins


def run_longshort(df_raw, forward_days, threshold, gap, dim_label):
    df = prepare(df_raw, forward_days, threshold, gap)
    rc = [f"{f}_rank" for f in STABLE_15 if f"{f}_rank" in df.columns]
    wins = gen_windows(df)

    print(f"\n{'=' * 85}")
    print(f"  {dim_label}  fwd={forward_days}d  gap={gap}  threshold={threshold:.0%}")
    print(f"{'=' * 85}")
    print(f"  {'窗口':>4} {'時期':>24} {'IC':>7} {'Top10%':>8} {'Bot10%':>8} "
          f"{'市場':>8} {'L-S差':>8} {'Top勝率':>7} {'Bot勝率':>7}")
    print(f"  {'─' * 82}")

    all_rows = []

    for wid, tr, ts, te in wins:
        train = df[df["date"] <= tr].dropna(subset=["label"])
        test = df[(df["date"] >= ts) & (df["date"] <= te)].dropna(subset=["label", "forward_return"])
        if len(train) < 2000 or len(test) < 300:
            continue

        X_tr, y_tr = train[rc].values, train["label"].values
        w = np.clip(1.0 - 0.2 * (tr.year - train["date"].dt.year), 0.2, 1.0).values

        clf = HistGradientBoostingClassifier(
            max_iter=200, max_depth=4, max_leaf_nodes=15,
            learning_rate=0.01, min_samples_leaf=100, l2_regularization=1.0,
            random_state=42, class_weight="balanced")
        clf.fit(X_tr, y_tr, sample_weight=w)

        y_reg = train["forward_return"].values.clip(-0.5, 0.5)
        reg = HistGradientBoostingRegressor(
            max_iter=200, max_depth=4, max_leaf_nodes=15,
            learning_rate=0.01, min_samples_leaf=100, l2_regularization=1.0,
            random_state=42)
        reg.fit(X_tr, y_reg, sample_weight=w)

        p_clf = clf.predict_proba(test[rc].values)[:, 1]
        p_reg = reg.predict(test[rc].values)
        rmin, rmax = reg.predict(X_tr).min(), reg.predict(X_tr).max()
        p_reg_n = np.clip((p_reg - rmin) / (rmax - rmin + 1e-9), 0, 1)
        prob = 0.5 * p_clf + 0.5 * p_reg_n

        test = test.copy()
        test["_p"] = prob
        fwd = test["forward_return"].values

        # IC
        daily_ics = []
        for _, g in test.groupby("date"):
            if len(g) < 50:
                continue
            p, r = g["_p"].values, g["forward_return"].values
            v = ~np.isnan(r)
            if v.sum() < 30:
                continue
            ic, _ = stats.spearmanr(p[v], r[v])
            if not np.isnan(ic):
                daily_ics.append(ic)
        ic = np.mean(daily_ics) if daily_ics else 0

        # Top 10% / Bottom 10% / 市場
        cut_top = np.percentile(prob, 90)
        cut_bot = np.percentile(prob, 10)
        top_mask = prob >= cut_top
        bot_mask = prob <= cut_bot
        mid_mask = ~top_mask & ~bot_mask

        top_ret = np.nanmean(fwd[top_mask])
        bot_ret = np.nanmean(fwd[bot_mask])
        mkt_ret = np.nanmean(fwd)
        ls_spread = top_ret - bot_ret
        top_wr = np.nanmean(fwd[top_mask] > 0)
        bot_wr = np.nanmean(fwd[bot_mask] > 0)

        mark = "✓" if ls_spread > 0.02 else " "
        print(f"  W{wid:>2} {ts.date()}~{te.date()} {ic:>+7.4f} "
              f"{top_ret * 100:>+7.1f}% {bot_ret * 100:>+7.1f}% "
              f"{mkt_ret * 100:>+7.1f}% {ls_spread * 100:>+7.1f}% "
              f"{top_wr:>6.0%} {bot_wr:>6.0%}  {mark}")

        all_rows.append({
            "wid": wid, "period": f"{ts.date()}~{te.date()}",
            "ic": ic, "top_ret": top_ret, "bot_ret": bot_ret,
            "mkt_ret": mkt_ret, "ls_spread": ls_spread,
            "top_wr": top_wr, "bot_wr": bot_wr,
            "top_n": int(top_mask.sum()), "bot_n": int(bot_mask.sum()),
        })

    if not all_rows:
        return

    rdf = pd.DataFrame(all_rows)
    print(f"\n  {'─' * 82}")
    print(f"  平均       {'':>24} {rdf['ic'].mean():>+7.4f} "
          f"{rdf['top_ret'].mean() * 100:>+7.1f}% {rdf['bot_ret'].mean() * 100:>+7.1f}% "
          f"{rdf['mkt_ret'].mean() * 100:>+7.1f}% {rdf['ls_spread'].mean() * 100:>+7.1f}% "
          f"{rdf['top_wr'].mean():>6.0%} {rdf['bot_wr'].mean():>6.0%}")

    # 做空勝率（Bottom 10% 跌的比例）
    bot_lose_rate = (1 - rdf['bot_wr']).mean()
    top_win_rate = rdf['top_wr'].mean()
    ls_positive = (rdf['ls_spread'] > 0).sum()

    print(f"\n  === 策略有效性判定 ===")
    print(f"  Top10% 平均報酬:  {rdf['top_ret'].mean() * 100:+.2f}%  (做多賺)")
    print(f"  Bot10% 平均報酬:  {rdf['bot_ret'].mean() * 100:+.2f}%  (做空標的)")
    print(f"  市場平均報酬:     {rdf['mkt_ret'].mean() * 100:+.2f}%")
    print(f"  Long-Short 價差:  {rdf['ls_spread'].mean() * 100:+.2f}%  ({ls_positive}/{len(rdf)} 窗口正)")
    print(f"  Top10% 勝率:      {top_win_rate:.0%}")
    print(f"  Bot10% 下跌率:    {bot_lose_rate:.0%}")
    print(f"  Top vs 市場:      {(rdf['top_ret'].mean() - rdf['mkt_ret'].mean()) * 100:+.2f}%")
    print(f"  Bot vs 市場:      {(rdf['bot_ret'].mean() - rdf['mkt_ret'].mean()) * 100:+.2f}%")

    if rdf['ls_spread'].mean() > 0.02 and ls_positive >= len(rdf) * 0.7:
        print(f"\n  ★ 結論：策略能有效分辨好壞股，long-short 價差穩定為正")
    elif rdf['ls_spread'].mean() > 0.01:
        print(f"\n  △ 結論：策略有一定分辨力，但不夠穩定")
    else:
        print(f"\n  ✗ 結論：策略無法有效分辨好壞股，可能只是搭牛市順風車")

    return rdf


def main():
    df = load_data()

    # 20d (現有主力)
    run_longshort(df, forward_days=20, threshold=0.03, gap=1, dim_label="20d Ensemble")

    # 10d
    run_longshort(df, forward_days=10, threshold=0.03, gap=1, dim_label="10d Ensemble")


if __name__ == "__main__":
    main()

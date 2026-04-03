"""
20d + 10d 共振 Walk-Forward 驗證
只推薦「同時被 20d 和 10d 模型選中 Top10%」的股票
對比：20d 單獨、10d 單獨、共振
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
            df[d] = -df[s]
    print(f"[Data] {len(df):,} 筆，{df['date'].min().date()} ~ {df['date'].max().date()}")
    return df


def compute_ranks(df: pd.DataFrame) -> pd.DataFrame:
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


def train_ensemble(train_df, rc, train_end):
    X_tr = train_df[rc].values
    y_tr = train_df["label"].values
    w = np.clip(1.0 - 0.2 * (train_end.year - train_df["date"].dt.year), 0.2, 1.0).values

    clf = HistGradientBoostingClassifier(
        max_iter=200, max_depth=4, max_leaf_nodes=15,
        learning_rate=0.01, min_samples_leaf=100, l2_regularization=1.0,
        random_state=42, class_weight="balanced")
    clf.fit(X_tr, y_tr, sample_weight=w)

    y_reg = train_df["forward_return"].values.clip(-0.5, 0.5)
    reg = HistGradientBoostingRegressor(
        max_iter=200, max_depth=4, max_leaf_nodes=15,
        learning_rate=0.01, min_samples_leaf=100, l2_regularization=1.0,
        random_state=42)
    reg.fit(X_tr, y_reg, sample_weight=w)

    return clf, reg


def predict_ensemble(clf, reg, X_test, X_train):
    p_clf = clf.predict_proba(X_test)[:, 1]
    p_reg = reg.predict(X_test)
    rmin, rmax = reg.predict(X_train).min(), reg.predict(X_train).max()
    p_reg_n = np.clip((p_reg - rmin) / (rmax - rmin + 1e-9), 0, 1)
    return 0.5 * p_clf + 0.5 * p_reg_n


def main():
    df_raw = load_data()

    # 準備兩個維度的資料（都用 MA60 過濾，gap=1）
    results_all = {}

    for fwd_days, dim_label in [(20, "20d"), (10, "10d")]:
        df = df_raw.sort_values(["stock_id", "date"]).copy()
        # gap=1 forward return
        df["entry_close"] = df.groupby("stock_id")["close"].shift(-1)
        df["exit_close"] = df.groupby("stock_id")["close"].shift(-(1 + fwd_days))
        df[f"fwd_{dim_label}"] = (df["exit_close"] - df["entry_close"]) / df["entry_close"]
        df["forward_return"] = df[f"fwd_{dim_label}"]
        df["label"] = np.where(df["forward_return"].isna(), np.nan,
                               (df["forward_return"] > 0.03).astype(float))
        # MA60 過濾
        df = df[df["close"] > df["ma60"]].copy()
        df = compute_ranks(df)
        results_all[dim_label] = df

    rc = [f"{f}_rank" for f in STABLE_15 if f"{f}_rank" in results_all["20d"].columns]
    wins = gen_windows(results_all["20d"])

    print(f"\n{'=' * 95}")
    print(f"  20d + 10d 共振 Walk-Forward 驗證（gap=1, MA60）")
    print(f"{'=' * 95}")
    print(f"\n  {'窗口':>4} {'時期':>24}  {'20d Top':>8} {'10d Top':>8} {'共振':>8} "
          f"{'市場':>8} {'共振WR':>7} {'共振N':>6} {'20d WR':>7} {'10d WR':>7}")
    print(f"  {'─' * 92}")

    summary_rows = []

    for wid, tr, ts, te in wins:
        # 20d 模型
        df20 = results_all["20d"]
        train20 = df20[df20["date"] <= tr].dropna(subset=["label"])
        test20 = df20[(df20["date"] >= ts) & (df20["date"] <= te)].dropna(subset=["label", "forward_return"])

        # 10d 模型
        df10 = results_all["10d"]
        train10 = df10[df10["date"] <= tr].dropna(subset=["label"])
        test10 = df10[(df10["date"] >= ts) & (df10["date"] <= te)].dropna(subset=["label", "forward_return"])

        if len(train20) < 2000 or len(test20) < 300:
            continue
        if len(train10) < 2000 or len(test10) < 300:
            continue

        # 訓練兩個模型
        clf20, reg20 = train_ensemble(train20, rc, tr)
        clf10, reg10 = train_ensemble(train10, rc, tr)

        # 預測
        prob20 = predict_ensemble(clf20, reg20, test20[rc].values, train20[rc].values)
        prob10 = predict_ensemble(clf10, reg10, test10[rc].values, train10[rc].values)

        # 對齊：找共同的 (stock_id, date) 對
        test20 = test20.copy()
        test20["_p20"] = prob20
        test20["_key"] = test20["stock_id"] + "_" + test20["date"].astype(str)

        test10 = test10.copy()
        test10["_p10"] = prob10
        test10["_key"] = test10["stock_id"] + "_" + test10["date"].astype(str)

        # merge
        merged = test20[["_key", "stock_id", "date", "_p20", "forward_return"]].merge(
            test10[["_key", "_p10"]], on="_key", how="inner"
        )
        if len(merged) < 100:
            continue

        # 20d forward return 用於評估（持有 20 天的報酬）
        fwd = merged["forward_return"].values

        # Top 10%
        cut20 = np.percentile(merged["_p20"], 90)
        cut10 = np.percentile(merged["_p10"], 90)
        top20 = merged["_p20"] >= cut20
        top10 = merged["_p10"] >= cut10
        resonance = top20 & top10  # 共振：兩個都選中

        ret_20only = np.nanmean(fwd[top20.values])
        ret_10only = np.nanmean(fwd[top10.values])
        ret_resonance = np.nanmean(fwd[resonance.values]) if resonance.sum() > 0 else np.nan
        ret_mkt = np.nanmean(fwd)
        wr_resonance = np.nanmean(fwd[resonance.values] > 0) if resonance.sum() > 0 else np.nan
        wr_20 = np.nanmean(fwd[top20.values] > 0)
        wr_10 = np.nanmean(fwd[top10.values] > 0)
        n_resonance = int(resonance.sum())

        print(f"  W{wid:>2} {ts.date()}~{te.date()} "
              f" {ret_20only * 100:>+7.1f}% {ret_10only * 100:>+7.1f}% "
              f"{ret_resonance * 100:>+7.1f}% {ret_mkt * 100:>+7.1f}% "
              f"{wr_resonance:>6.0%} {n_resonance:>5} "
              f"{wr_20:>6.0%} {wr_10:>6.0%}")

        summary_rows.append({
            "wid": wid, "ret_20": ret_20only, "ret_10": ret_10only,
            "ret_res": ret_resonance, "ret_mkt": ret_mkt,
            "wr_res": wr_resonance, "wr_20": wr_20, "wr_10": wr_10,
            "n_res": n_resonance,
        })

    if not summary_rows:
        print("  [跳過] 窗口不足")
        return

    rdf = pd.DataFrame(summary_rows)
    print(f"  {'─' * 92}")
    print(f"  平均                            "
          f" {rdf['ret_20'].mean() * 100:>+7.1f}% {rdf['ret_10'].mean() * 100:>+7.1f}% "
          f"{rdf['ret_res'].mean() * 100:>+7.1f}% {rdf['ret_mkt'].mean() * 100:>+7.1f}% "
          f"{rdf['wr_res'].mean():>6.0%} {rdf['n_res'].mean():>5.0f} "
          f"{rdf['wr_20'].mean():>6.0%} {rdf['wr_10'].mean():>6.0%}")

    print(f"\n  === 共振 vs 單獨 ===")
    print(f"  共振平均報酬:    {rdf['ret_res'].mean() * 100:+.2f}%")
    print(f"  20d 單獨平均報酬: {rdf['ret_20'].mean() * 100:+.2f}%")
    print(f"  10d 單獨平均報酬: {rdf['ret_10'].mean() * 100:+.2f}%")
    print(f"  市場平均報酬:    {rdf['ret_mkt'].mean() * 100:+.2f}%")
    print(f"  共振勝率:        {rdf['wr_res'].mean():.0%}")
    print(f"  20d 勝率:        {rdf['wr_20'].mean():.0%}")
    print(f"  10d 勝率:        {rdf['wr_10'].mean():.0%}")
    print(f"  共振平均檔數/窗口: {rdf['n_res'].mean():.0f}")

    # 共振 vs 市場超額
    excess_res = rdf['ret_res'].mean() - rdf['ret_mkt'].mean()
    excess_20 = rdf['ret_20'].mean() - rdf['ret_mkt'].mean()
    excess_10 = rdf['ret_10'].mean() - rdf['ret_mkt'].mean()
    print(f"\n  超額報酬（vs 市場）:")
    print(f"  共振: {excess_res * 100:+.2f}%")
    print(f"  20d:  {excess_20 * 100:+.2f}%")
    print(f"  10d:  {excess_10 * 100:+.2f}%")

    if rdf['ret_res'].mean() > rdf['ret_20'].mean() and rdf['wr_res'].mean() > rdf['wr_20'].mean():
        print(f"\n  ★ 共振策略優於 20d 單獨，報酬和勝率都更高")
    elif rdf['ret_res'].mean() > rdf['ret_20'].mean():
        print(f"\n  △ 共振報酬更高但勝率未明顯提升")
    else:
        print(f"\n  ✗ 共振未能顯著改善 20d 單獨表現")


if __name__ == "__main__":
    main()

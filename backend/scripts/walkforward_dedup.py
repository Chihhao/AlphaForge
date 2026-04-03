"""
Walk-Forward 回測：去重規則驗證
比較有/無去重對共振策略的影響

去重條件：同一股票在持有期（20天）內不重複推薦
"""
from __future__ import annotations
import os, warnings
import numpy as np
import pandas as pd
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
MAX_PICKS = 5
HOLD_DAYS = 20


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


def load_regime() -> pd.DataFrame:
    sql = text("SELECT date, close FROM stock_prices "
               "WHERE stock_id = '0050' AND date >= '2023-01-01' ORDER BY date")
    tw = pd.read_sql(sql, engine)
    tw["date"] = pd.to_datetime(tw["date"])
    tw["close"] = tw["close"].astype(float)
    tw["ma20"] = tw["close"].rolling(20).mean()
    tw["regime_ok"] = tw["close"] > tw["ma20"]
    return tw[["date", "regime_ok"]]


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


def simulate_daily_picks(merged: pd.DataFrame, regime: pd.DataFrame, dedup: bool):
    """逐日模擬推薦流程，回傳每筆推薦的報酬"""
    merged = merged.merge(regime, on="date", how="left")
    merged["regime_ok"] = merged["regime_ok"].fillna(True)

    dates = sorted(merged["date"].unique())
    recent_picks: dict[str, pd.Timestamp] = {}  # stock_id -> last_pick_date
    all_trades = []

    for dt in dates:
        day_df = merged[merged["date"] == dt].copy()

        # Regime filter
        if not day_df["regime_ok"].iloc[0]:
            continue

        # 共振：20d + 10d 都在 Top 10%
        cut20 = np.percentile(day_df["_p20"], 90)
        cut10 = np.percentile(day_df["_p10"], 90)
        candidates = day_df[(day_df["_p20"] >= cut20) & (day_df["_p10"] >= cut10)].copy()

        if candidates.empty:
            continue

        # 去重：排除持有期內已推薦的股票
        if dedup:
            eligible = []
            for _, row in candidates.iterrows():
                sid = row["stock_id"]
                if sid in recent_picks:
                    days_since = (pd.Timestamp(dt) - recent_picks[sid]).days
                    if days_since < HOLD_DAYS:
                        continue
                eligible.append(row)
            if not eligible:
                continue
            candidates = pd.DataFrame(eligible)

        # 按分數排序取 Top N
        candidates = candidates.sort_values("_p20", ascending=False).head(MAX_PICKS)

        for _, row in candidates.iterrows():
            sid = row["stock_id"]
            recent_picks[sid] = pd.Timestamp(dt)
            all_trades.append({
                "date": dt,
                "stock_id": sid,
                "forward_return": row["forward_return"],
                "score": row["_p20"],
            })

    return pd.DataFrame(all_trades)


def main():
    df_raw = load_data()
    regime = load_regime()

    results_all = {}
    for fwd_days, dim_label in [(20, "20d"), (10, "10d")]:
        df = df_raw.sort_values(["stock_id", "date"]).copy()
        df["entry_close"] = df.groupby("stock_id")["close"].shift(-1)
        df["exit_close"] = df.groupby("stock_id")["close"].shift(-(1 + fwd_days))
        df[f"fwd_{dim_label}"] = (df["exit_close"] - df["entry_close"]) / df["entry_close"]
        df["forward_return"] = df[f"fwd_{dim_label}"]
        df["label"] = np.where(df["forward_return"].isna(), np.nan,
                               (df["forward_return"] > 0.03).astype(float))
        df = df[df["close"] > df["ma60"]].copy()
        df = compute_ranks(df)
        results_all[dim_label] = df

    rc = [f"{f}_rank" for f in STABLE_15 if f"{f}_rank" in results_all["20d"].columns]
    wins = gen_windows(results_all["20d"])

    print(f"\n{'=' * 100}")
    print(f"  去重規則 Walk-Forward 驗證（regime=MA20, gap=1, MA60, Top5）")
    print(f"{'=' * 100}")

    summary = {"無去重": [], "去重20d": []}

    for wid, tr, ts, te in wins:
        df20 = results_all["20d"]
        train20 = df20[df20["date"] <= tr].dropna(subset=["label"])
        test20 = df20[(df20["date"] >= ts) & (df20["date"] <= te)].dropna(subset=["label", "forward_return"])

        df10 = results_all["10d"]
        train10 = df10[df10["date"] <= tr].dropna(subset=["label"])
        test10 = df10[(df10["date"] >= ts) & (df10["date"] <= te)].dropna(subset=["label", "forward_return"])

        if len(train20) < 2000 or len(test20) < 300:
            continue
        if len(train10) < 2000 or len(test10) < 300:
            continue

        clf20, reg20 = train_ensemble(train20, rc, tr)
        clf10, reg10 = train_ensemble(train10, rc, tr)

        prob20 = predict_ensemble(clf20, reg20, test20[rc].values, train20[rc].values)
        prob10 = predict_ensemble(clf10, reg10, test10[rc].values, train10[rc].values)

        test20 = test20.copy()
        test20["_p20"] = prob20
        test20["_key"] = test20["stock_id"] + "_" + test20["date"].astype(str)

        test10 = test10.copy()
        test10["_p10"] = prob10
        test10["_key"] = test10["stock_id"] + "_" + test10["date"].astype(str)

        merged = test20[["_key", "stock_id", "date", "_p20", "forward_return"]].merge(
            test10[["_key", "_p10"]], on="_key", how="inner"
        )
        if len(merged) < 100:
            continue

        # 計算市場基準（merged 中所有股票的平均報酬）
        mkt_by_date = merged.groupby("date")["forward_return"].mean()

        print(f"\n  W{wid} {ts.date()} ~ {te.date()}")
        print(f"  {'策略':<10} {'平均報酬':>8} {'勝率':>6} {'交易數':>6} {'不重複股':>8} {'每日均檔':>8}")
        print(f"  {'─' * 56}")

        for dedup, label in [(False, "無去重"), (True, "去重20d")]:
            trades = simulate_daily_picks(merged, regime, dedup)
            if trades.empty:
                print(f"  {label:<10} {'N/A':>8}")
                summary[label].append(None)
                continue

            rets = trades["forward_return"].values
            avg_ret = np.nanmean(rets)
            wr = np.nanmean(rets > 0)
            n_trades = len(trades)
            n_unique = trades["stock_id"].nunique()
            n_days = trades["date"].nunique()
            avg_per_day = n_trades / n_days if n_days > 0 else 0

            # 計算同期市場報酬（只算有推薦的日期）
            active_dates = trades["date"].unique()
            mkt_ret = mkt_by_date.reindex(active_dates).mean()

            # 逐日組合報酬
            daily_rets = trades.groupby("date")["forward_return"].mean()
            sharpe = daily_rets.mean() / daily_rets.std() * np.sqrt(252 / HOLD_DAYS) if daily_rets.std() > 0 else 0

            print(f"  {label:<10} {avg_ret*100:>+7.2f}% {wr:>5.0%} {n_trades:>5} "
                  f"{n_unique:>7} {avg_per_day:>7.1f}")

            summary[label].append({
                "wid": wid, "avg_ret": avg_ret, "wr": wr,
                "n_trades": n_trades, "n_unique": n_unique,
                "n_days": n_days, "avg_per_day": avg_per_day,
                "mkt_ret": mkt_ret, "sharpe": sharpe,
            })

    # === 總結 ===
    print(f"\n{'=' * 100}")
    print(f"  === 總結 ===")
    print(f"{'=' * 100}")
    print(f"  {'策略':<10} {'平均報酬':>8} {'超額':>8} {'勝率':>6} {'Sharpe':>8} {'總交易':>6} {'不重複股':>8} {'每日均檔':>8}")
    print(f"  {'─' * 72}")

    for label in ["無去重", "去重20d"]:
        valid = [s for s in summary[label] if s is not None]
        if not valid:
            continue
        avg_ret = np.mean([s["avg_ret"] for s in valid])
        avg_mkt = np.mean([s["mkt_ret"] for s in valid])
        avg_wr = np.mean([s["wr"] for s in valid])
        avg_sharpe = np.mean([s["sharpe"] for s in valid])
        total_trades = sum(s["n_trades"] for s in valid)
        avg_unique = np.mean([s["n_unique"] for s in valid])
        avg_per_day = np.mean([s["avg_per_day"] for s in valid])
        excess = avg_ret - avg_mkt

        print(f"  {label:<10} {avg_ret*100:>+7.2f}% {excess*100:>+7.2f}% {avg_wr:>5.0%} "
              f"{avg_sharpe:>7.2f} {total_trades:>5} {avg_unique:>7.0f} {avg_per_day:>7.1f}")

    # 逐窗口比較
    print(f"\n  === 逐窗口報酬比較 ===")
    print(f"  {'窗口':>4}  {'無去重':>10}  {'去重20d':>10}  {'差異':>8}  {'無去重股數':>10}  {'去重股數':>10}")
    print(f"  {'─' * 60}")

    for i in range(len(summary["無去重"])):
        s_no = summary["無去重"][i]
        s_dd = summary["去重20d"][i]
        if s_no is None or s_dd is None:
            continue
        diff = (s_dd["avg_ret"] - s_no["avg_ret"]) * 100
        print(f"  W{s_no['wid']:>2}   {s_no['avg_ret']*100:>+9.2f}%  {s_dd['avg_ret']*100:>+9.2f}%  "
              f"{diff:>+7.2f}%  {s_no['n_unique']:>9}  {s_dd['n_unique']:>9}")


if __name__ == "__main__":
    main()

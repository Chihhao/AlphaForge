"""
Walk-Forward Long-Short 驗證：A(現行15) vs E(穩定+營收9)
Top10% vs Bottom10% 分辨力比較，同時看最大回撤和穩定性
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

FACTOR_A = [
    "roe", "yield_rate", "pb_ratio", "revenue_yoy",
    "foreign_hold_chg_5d", "foreign_net_buy", "foreign_buy_5d",
    "dealer_buy_20d", "vol_ratio", "foreign_buy_10d", "price_vs_high20",
    "neg_trust_net_buy", "neg_trust_buy_5d", "neg_trust_buy_10d", "neg_trust_buy_20d",
]

FACTOR_E = [
    "roe", "pb_ratio", "revenue_yoy", "yield_rate",
    "rev_surprise", "rev_accel",
    "foreign_hold_chg_5d", "dealer_buy_20d", "vol_ratio",
]


def load_data() -> pd.DataFrame:
    all_factors = sorted(set(FACTOR_A + FACTOR_E))
    # neg_trust 系列是衍生欄位，DB 中只有 trust 原始欄位
    db_factors = [f for f in all_factors if not f.startswith("neg_trust")]
    trust_raw = ["trust_net_buy", "trust_buy_5d", "trust_buy_10d", "trust_buy_20d"]
    base = ["stock_id", "date", "close", "ma60"]
    cols = sorted(set(base + db_factors + trust_raw))
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
    X = train_df[rc].values
    y = train_df["label"].values
    w = np.clip(1.0 - 0.2 * (train_end.year - train_df["date"].dt.year), 0.2, 1.0).values
    clf = HistGradientBoostingClassifier(
        max_iter=200, max_depth=4, max_leaf_nodes=15,
        learning_rate=0.01, min_samples_leaf=100, l2_regularization=1.0,
        random_state=42, class_weight="balanced")
    clf.fit(X, y, sample_weight=w)
    y_reg = train_df["forward_return"].values.clip(-0.5, 0.5)
    reg = HistGradientBoostingRegressor(
        max_iter=200, max_depth=4, max_leaf_nodes=15,
        learning_rate=0.01, min_samples_leaf=100, l2_regularization=1.0,
        random_state=42)
    reg.fit(X, y_reg, sample_weight=w)
    return clf, reg


def predict_ensemble(clf, reg, X_test, X_train):
    p_clf = clf.predict_proba(X_test)[:, 1]
    p_reg = reg.predict(X_test)
    rmin, rmax = reg.predict(X_train).min(), reg.predict(X_train).max()
    p_reg_n = np.clip((p_reg - rmin) / (rmax - rmin + 1e-9), 0, 1)
    return 0.5 * p_clf + 0.5 * p_reg_n


def run_longshort(label: str, factors: list, df_raw: pd.DataFrame, windows: list):
    """跑 20d long-short walk-forward（gap=1, MA60 過濾）"""
    print(f"\n{'=' * 90}")
    print(f"  {label} — Long-Short Walk-Forward（20d, gap=1, MA60）")
    print(f"{'=' * 90}")
    print(f"  {'窗口':>4} {'期間':>24}  {'Top10%':>8} {'Bot10%':>8} {'市場':>8} {'L-S':>8} {'TopWR':>6} {'BotWR':>6} {'IC':>8}")
    print(f"  {'─' * 88}")

    rc = [f"{f}_rank" for f in factors]
    rows = []

    for wid, tr, ts, te in windows:
        df = df_raw.sort_values(["stock_id", "date"]).copy()
        df["entry_close"] = df.groupby("stock_id")["close"].shift(-1)
        df["exit_close"] = df.groupby("stock_id")["close"].shift(-21)
        df["forward_return"] = (df["exit_close"] - df["entry_close"]) / df["entry_close"]
        df["label"] = np.where(df["forward_return"].isna(), np.nan,
                               (df["forward_return"] > 0.03).astype(float))
        df = df[df["close"] > df["ma60"]].copy()

        for f in factors:
            if f in df.columns:
                df[f"{f}_rank"] = df.groupby("date")[f].rank(pct=True, na_option="keep")

        train = df[df["date"] <= tr].dropna(subset=["label"])
        test = df[(df["date"] >= ts) & (df["date"] <= te)].dropna(subset=["label", "forward_return"])

        if len(train) < 2000 or len(test) < 300:
            continue

        clf, reg = train_ensemble(train, rc, tr)
        prob = predict_ensemble(clf, reg, test[rc].values, train[rc].values)

        test = test.copy()
        test["score"] = prob

        fwd = test["forward_return"].values

        cut_top = np.percentile(prob, 90)
        cut_bot = np.percentile(prob, 10)
        top = prob >= cut_top
        bot = prob <= cut_bot

        ret_top = np.nanmean(fwd[top])
        ret_bot = np.nanmean(fwd[bot])
        ret_mkt = np.nanmean(fwd)
        ls = ret_top - ret_bot
        wr_top = np.nanmean(fwd[top] > 0)
        wr_bot = np.nanmean(fwd[bot] > 0)

        # Rank IC（每日算再平均）
        daily_ics = []
        for dt, grp in test.groupby("date"):
            if len(grp) > 20:
                ic = grp["score"].corr(grp["forward_return"], method="spearman")
                if not np.isnan(ic):
                    daily_ics.append(ic)
        avg_ic = np.mean(daily_ics) if daily_ics else np.nan
        ic_positive_pct = np.mean([ic > 0 for ic in daily_ics]) if daily_ics else np.nan

        print(f"  W{wid:>2} {ts.date()}~{te.date()}"
              f"  {ret_top*100:>+7.1f}% {ret_bot*100:>+7.1f}% {ret_mkt*100:>+7.1f}%"
              f" {ls*100:>+7.1f}% {wr_top:>5.0%} {wr_bot:>5.0%} {avg_ic:>+7.3f}")

        rows.append({
            "wid": wid, "ret_top": ret_top, "ret_bot": ret_bot,
            "ret_mkt": ret_mkt, "ls": ls,
            "wr_top": wr_top, "wr_bot": wr_bot,
            "ic": avg_ic, "ic_pos": ic_positive_pct,
        })

    if not rows:
        return None

    rdf = pd.DataFrame(rows)
    print(f"  {'─' * 88}")
    print(f"  平均                           "
          f"  {rdf['ret_top'].mean()*100:>+7.1f}% {rdf['ret_bot'].mean()*100:>+7.1f}% {rdf['ret_mkt'].mean()*100:>+7.1f}%"
          f" {rdf['ls'].mean()*100:>+7.1f}% {rdf['wr_top'].mean():>5.0%} {rdf['wr_bot'].mean():>5.0%}"
          f" {rdf['ic'].mean():>+7.3f}")

    # L-S > 0 的窗口數
    ls_win = (rdf['ls'] > 0).sum()
    ic_win = (rdf['ic'] > 0).sum()
    n = len(rdf)

    print(f"\n  L-S>0: {ls_win}/{n}  |  IC>0: {ic_win}/{n}  |  平均IC: {rdf['ic'].mean():+.4f}")

    # 逐窗口累積報酬（模擬等權 long-short portfolio）
    cum_ls = (1 + rdf["ls"]).cumprod()
    max_dd = ((cum_ls / cum_ls.cummax()) - 1).min()
    total_ret = cum_ls.iloc[-1] - 1
    sharpe = rdf["ls"].mean() / rdf["ls"].std() * np.sqrt(12 / 4) if rdf["ls"].std() > 0 else 0

    print(f"  總報酬: {total_ret*100:+.1f}%  |  MaxDD: {max_dd*100:.1f}%  |  Sharpe: {sharpe:.2f}")

    return rdf


def main():
    df_raw = load_data()
    windows = gen_windows(df_raw)

    result_a = run_longshort("A：現行 15 因子", FACTOR_A, df_raw, windows)
    result_e = run_longshort("E：穩定+營收 9 因子", FACTOR_E, df_raw, windows)

    if result_a is not None and result_e is not None:
        print(f"\n{'=' * 90}")
        print(f"  === A vs E 直接比較 ===")
        print(f"{'=' * 90}")
        print(f"  {'指標':<20} {'A(現行15)':>12} {'E(穩定+營收9)':>14} {'差異':>10}")
        print(f"  {'─' * 58}")

        metrics = [
            ("Top10% 報酬", "ret_top"),
            ("Bot10% 報酬", "ret_bot"),
            ("L-S 價差", "ls"),
            ("Top 勝率", "wr_top"),
            ("Rank IC", "ic"),
        ]
        for name, col in metrics:
            va = result_a[col].mean()
            ve = result_e[col].mean()
            diff = ve - va
            fmt = ".1f" if "ret" in col or col == "ls" else (".0f" if "wr" in col else ".4f")
            if "wr" in col:
                print(f"  {name:<20} {va*100:>11.0f}% {ve*100:>13.0f}% {diff*100:>+9.1f}pp")
            elif col == "ic":
                print(f"  {name:<20} {va:>+11.4f} {ve:>+13.4f} {diff:>+10.4f}")
            else:
                print(f"  {name:<20} {va*100:>+11.1f}% {ve*100:>+13.1f}% {diff*100:>+9.1f}pp")

        # 逐窗口 L-S 比較
        print(f"\n  逐窗口 L-S 價差：")
        print(f"  {'窗口':>4}  {'A':>10}  {'E':>10}  {'E-A':>8}  {'勝者':>6}")
        print(f"  {'─' * 42}")
        e_wins = 0
        for i in range(len(result_a)):
            a_ls = result_a.iloc[i]["ls"] * 100
            e_ls = result_e.iloc[i]["ls"] * 100
            diff = e_ls - a_ls
            winner = "E" if e_ls > a_ls else "A"
            if winner == "E":
                e_wins += 1
            wid = int(result_a.iloc[i]["wid"])
            print(f"  W{wid:>2}   {a_ls:>+9.1f}%  {e_ls:>+9.1f}%  {diff:>+7.1f}%  {winner:>5}")

        print(f"\n  E 勝出窗口: {e_wins}/{len(result_a)}")


if __name__ == "__main__":
    main()

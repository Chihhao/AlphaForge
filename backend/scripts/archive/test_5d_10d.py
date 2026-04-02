"""
5d / 10d / 30d 三維度 Walk-Forward 比較
用新的 15 穩定因子 + Ensemble (Clf+Reg)
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


def load_data():
    cols = ["stock_id", "date", "close", "ma60",
            "roe", "yield_rate", "pb_ratio", "revenue_yoy",
            "foreign_hold_chg_5d", "foreign_net_buy", "foreign_buy_5d",
            "dealer_buy_20d", "vol_ratio", "foreign_buy_10d", "price_vs_high20",
            "trust_net_buy", "trust_buy_5d", "trust_buy_10d", "trust_buy_20d"]
    sql = text(f"SELECT {', '.join(cols)} FROM stock_features WHERE close > 0 AND date >= '2023-03-01' ORDER BY date, stock_id")
    df = pd.read_sql(sql, engine)
    df["date"] = pd.to_datetime(df["date"])
    for s, d in [("trust_net_buy","neg_trust_net_buy"),("trust_buy_5d","neg_trust_buy_5d"),
                 ("trust_buy_10d","neg_trust_buy_10d"),("trust_buy_20d","neg_trust_buy_20d")]:
        if s in df.columns: df[d] = -df[s].fillna(0)
    print(f"[Data] {len(df):,} 筆，{df['date'].min().date()} ~ {df['date'].max().date()}")
    return df


def prepare(df, forward_days, threshold, ma60_filter):
    df = df.sort_values(["stock_id", "date"]).copy()
    df["forward_close"] = df.groupby("stock_id")["close"].shift(-forward_days)
    df["forward_return"] = (df["forward_close"] - df["close"]) / df["close"]
    df["label"] = (df["forward_return"] > threshold).astype(float)
    if ma60_filter:
        df = df[df["close"] > df["ma60"]].copy()
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


def run_dimension(df_raw, forward_days, threshold, ma60_filter, dim_label):
    df = prepare(df_raw, forward_days, threshold, ma60_filter)
    rc = [f"{f}_rank" for f in STABLE_15 if f"{f}_rank" in df.columns]
    wins = gen_windows(df)
    all_ics, all_excess, monthly_rets = [], [], []

    print(f"\n{'─' * 70}")
    print(f"  {dim_label}  fwd={forward_days}d  thr={threshold:.0%}  MA60={'Y' if ma60_filter else 'N'}")
    print(f"{'─' * 70}")

    for wid, tr, ts, te in wins:
        train = df[df["date"] <= tr].dropna(subset=["label"])
        test = df[(df["date"] >= ts) & (df["date"] <= te)].dropna(subset=["label","forward_return"])
        if len(train) < 2000 or len(test) < 300: continue

        X_tr, y_tr = train[rc].values, train["label"].values
        w = np.clip(1.0 - 0.2*(tr.year - train["date"].dt.year), 0.2, 1.0).values

        clf = HistGradientBoostingClassifier(max_iter=200, max_depth=4, max_leaf_nodes=15,
            learning_rate=0.01, min_samples_leaf=100, l2_regularization=1.0, random_state=42,
            verbose=0, class_weight="balanced")
        clf.fit(X_tr, y_tr, sample_weight=w)

        y_reg = train["forward_return"].values.clip(-0.5, 0.5)
        reg = HistGradientBoostingRegressor(max_iter=200, max_depth=4, max_leaf_nodes=15,
            learning_rate=0.01, min_samples_leaf=100, l2_regularization=1.0, random_state=42, verbose=0)
        reg.fit(X_tr, y_reg, sample_weight=w)

        p_clf = clf.predict_proba(test[rc].values)[:, 1]
        p_reg = reg.predict(test[rc].values)
        rmin, rmax = reg.predict(X_tr).min(), reg.predict(X_tr).max()
        p_reg_n = np.clip((p_reg - rmin) / (rmax - rmin + 1e-9), 0, 1)
        prob = 0.5 * p_clf + 0.5 * p_reg_n

        test = test.copy()
        test["_p"] = prob

        daily_ics = []
        for _, g in test.groupby("date"):
            if len(g) < 50: continue
            p, r = g["_p"].values, g["forward_return"].values
            v = ~np.isnan(r)
            if v.sum() < 30: continue
            ic, _ = stats.spearmanr(p[v], r[v])
            if not np.isnan(ic): daily_ics.append(ic)
        ic = np.mean(daily_ics) if daily_ics else 0
        ic_t = ic / (np.std(daily_ics)/np.sqrt(len(daily_ics))) if daily_ics and np.std(daily_ics)>0 else 0
        all_ics.append(ic)

        cut = np.percentile(prob, 90)
        top = prob >= cut
        fwd = test["forward_return"].values
        excess = np.nanmean(fwd[top]) - np.nanmean(fwd)
        all_excess.append(excess)
        wr = float(np.nanmean(fwd[top] > threshold))

        test["_top"] = top
        test["_m"] = test["date"].dt.to_period("M")
        for _, g in test[test["_top"]].groupby("_m"):
            monthly_rets.append(float(np.nanmean(g["forward_return"].values)) - COST)

        mark = "PASS" if ic > 0.05 and ic_t > 2 else "---"
        print(f"  W{wid} {ts.date()}~{te.date()} IC={ic:+.4f}(t={ic_t:+.1f}) "
              f"WR={wr:.0%} ex={excess*100:+.1f}% [{mark}]")

    if not all_ics: return None
    net = np.array(monthly_rets)
    ann = np.mean(net)*12
    vol = np.std(net)*np.sqrt(12)
    sh = ann/vol if vol>0 else 0
    cum = np.cumprod(1+net); pk = np.maximum.accumulate(cum); dd = np.min((cum-pk)/pk)

    print(f"\n  彙總: avgIC={np.mean(all_ics):+.4f} minIC={np.min(all_ics):+.4f} "
          f"IC>0={sum(1 for x in all_ics if x>0)/len(all_ics):.0%} "
          f"pass={sum(1 for x in all_ics if x>0.05)}/{len(all_ics)} "
          f"年化={ann*100:+.1f}% Sharpe={sh:.2f} MaxDD={dd*100:.1f}%")

    return {"dim": dim_label, "avg_ic": np.mean(all_ics), "min_ic": np.min(all_ics),
            "ic_pos": sum(1 for x in all_ics if x>0)/len(all_ics),
            "n_pass": sum(1 for x in all_ics if x>0.05), "n_win": len(all_ics),
            "ann": ann, "sharpe": sh, "max_dd": dd}


def main():
    df = load_data()
    results = []

    # 5d
    r = run_dimension(df, 5, 0.02, False, "5d Ensemble")
    if r: results.append(r)
    r = run_dimension(df, 5, 0.02, True, "5d Ensemble+MA60")
    if r: results.append(r)

    # 10d
    r = run_dimension(df, 10, 0.03, False, "10d Ensemble")
    if r: results.append(r)
    r = run_dimension(df, 10, 0.03, True, "10d Ensemble+MA60")
    if r: results.append(r)

    # 30d (baseline)
    r = run_dimension(df, 30, 0.03, True, "30d Ensemble+MA60")
    if r: results.append(r)

    # 20d (中間)
    r = run_dimension(df, 20, 0.03, True, "20d Ensemble+MA60")
    if r: results.append(r)

    print(f"\n{'=' * 70}")
    print(f"  全維度比較")
    print(f"{'=' * 70}")
    results.sort(key=lambda x: x["sharpe"], reverse=True)
    print(f"\n  {'維度':>20} {'avgIC':>7} {'minIC':>7} {'IC>0':>5} {'pass':>5} {'年化':>7} {'Sharpe':>7} {'MaxDD':>7}")
    print("  " + "─" * 70)
    for r in results:
        print(f"  {r['dim']:>20} {r['avg_ic']:>+7.4f} {r['min_ic']:>+7.4f} "
              f"{r['ic_pos']:>4.0%} {r['n_pass']}/{r['n_win']:>1} "
              f"{r['ann']*100:>+6.1f}% {r['sharpe']:>7.2f} {r['max_dd']*100:>+6.1f}%")


if __name__ == "__main__":
    main()

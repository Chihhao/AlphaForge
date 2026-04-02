"""
Walk-Forward 新舊模型比較

同一組窗口（train→test→train→test...），比較三個模型：
A) LogisticRegression 34 因子（舊）
B) GBM 34 因子（中間版）
C) GBM 15 穩定因子 + 反向投信（現在）

這樣每個模型都經歷牛市和熊市，公平比較。
"""
from __future__ import annotations
import os, warnings
import numpy as np
import pandas as pd
from scipy import stats
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier
from sqlalchemy import create_engine, text

warnings.filterwarnings("ignore")
PG_URL = os.getenv("PG_URL", "postgresql://alphaforge:alphaforge_secret@10.0.4.3:5433/alphaforge")
engine = create_engine(PG_URL)
COST = 0.006

ALL_34 = [
    "rsi14", "rsi2", "k", "d", "macd_dif", "macd_osc",
    "bias5", "bias10", "bias20", "bb_pctb", "vol_ratio",
    "yield_rate", "roe", "pb_ratio", "revenue_yoy",
    "foreign_net_buy", "foreign_buy_5d", "trust_net_buy", "trust_buy_5d",
    "margin_chg_5d", "dealer_net_buy", "dealer_buy_5d",
    "price_vs_high20", "ma_trend", "sector_rs",
    "foreign_hold_pct", "foreign_hold_chg_5d", "etf_net_flow_5d",
    "foreign_buy_10d", "foreign_buy_20d",
    "trust_buy_10d", "trust_buy_20d",
    "dealer_buy_10d", "dealer_buy_20d",
]

STABLE_15 = [
    "roe", "yield_rate", "pb_ratio", "revenue_yoy",
    "foreign_hold_chg_5d", "foreign_net_buy", "foreign_buy_5d",
    "dealer_buy_20d", "vol_ratio", "foreign_buy_10d", "price_vs_high20",
    "neg_trust_net_buy", "neg_trust_buy_5d", "neg_trust_buy_10d", "neg_trust_buy_20d",
]


def load_data():
    cols = list(set(["stock_id", "date", "close", "ma60"] + ALL_34))
    sql = text(f"SELECT {', '.join(cols)} FROM stock_features WHERE close > 0 AND date >= '2023-03-01' ORDER BY date, stock_id")
    df = pd.read_sql(sql, engine)
    df["date"] = pd.to_datetime(df["date"])
    for src, dst in [("trust_net_buy", "neg_trust_net_buy"), ("trust_buy_5d", "neg_trust_buy_5d"),
                     ("trust_buy_10d", "neg_trust_buy_10d"), ("trust_buy_20d", "neg_trust_buy_20d")]:
        if src in df.columns:
            df[dst] = -df[src].fillna(0)
    print(f"[Data] {len(df):,} 筆，{df['date'].min().date()} ~ {df['date'].max().date()}")
    return df


def prepare(df, factors, forward_days=30, threshold=0.03, ma60_filter=True):
    df = df.sort_values(["stock_id", "date"]).copy()
    df["forward_close"] = df.groupby("stock_id")["close"].shift(-forward_days)
    df["forward_return"] = (df["forward_close"] - df["close"]) / df["close"]
    df["label"] = (df["forward_return"] > threshold).astype(float)
    if ma60_filter:
        df = df[df["close"] > df["ma60"]].copy()
    rank_cols = []
    for f in factors:
        if f in df.columns:
            rc = f"{f}_rank"
            df[rc] = df.groupby("date")[f].rank(pct=True, na_option="keep")
            rank_cols.append(rc)
    return df, rank_cols


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


def eval_window(df, rank_cols, train_end, test_start, test_end, model_type="gbm"):
    train = df[df["date"] <= train_end].dropna(subset=["label"])
    test = df[(df["date"] >= test_start) & (df["date"] <= test_end)].dropna(subset=["label", "forward_return"])
    if len(train) < 2000 or len(test) < 300:
        return None

    X_tr = train[rank_cols].fillna(0.5).values
    y_tr = train["label"].values
    base_year = train_end.year
    w = np.clip(1.0 - 0.2 * (base_year - train["date"].dt.year), 0.2, 1.0).values

    if model_type == "lr":
        model = LogisticRegression(max_iter=500, C=0.1, class_weight="balanced", random_state=42)
        model.fit(X_tr, y_tr, sample_weight=w)
        prob = model.predict_proba(test[rank_cols].fillna(0.5).values)[:, 1]
    else:
        model = HistGradientBoostingClassifier(
            max_iter=200, max_depth=4, max_leaf_nodes=15,
            learning_rate=0.01, min_samples_leaf=100,
            l2_regularization=1.0, random_state=42, verbose=0,
            class_weight="balanced")
        model.fit(X_tr, y_tr, sample_weight=w)
        prob = model.predict_proba(test[rank_cols].values)[:, 1]

    test = test.copy()
    test["_p"] = prob

    # IC
    daily_ics = []
    for _, g in test.groupby("date"):
        if len(g) < 50: continue
        p, r = g["_p"].values, g["forward_return"].values
        v = ~np.isnan(r)
        if v.sum() < 30: continue
        ic, _ = stats.spearmanr(p[v], r[v])
        if not np.isnan(ic): daily_ics.append(ic)
    ic = np.mean(daily_ics) if daily_ics else 0
    ic_t = ic / (np.std(daily_ics) / np.sqrt(len(daily_ics))) if daily_ics and np.std(daily_ics) > 0 else 0

    # Top 10%
    cut = np.percentile(prob, 90)
    top = prob >= cut
    fwd = test["forward_return"].values
    top_ret = np.nanmean(fwd[top])
    mkt_ret = np.nanmean(fwd)

    wr = float(np.nanmean(fwd[top] > 0))
    thr_wr = float(np.nanmean(fwd[top] > 0.03))

    # Monthly
    test["_top"] = top
    test["_m"] = test["date"].dt.to_period("M")
    mr = [float(np.nanmean(g["forward_return"].values)) - COST for _, g in test[test["_top"]].groupby("_m")]
    sharpe = np.mean(mr) / np.std(mr) * np.sqrt(12) if len(mr) > 2 and np.std(mr) > 0 else 0

    return {"ic": ic, "ic_t": ic_t, "top_ret": top_ret, "mkt_ret": mkt_ret,
            "excess": top_ret - mkt_ret, "wr": wr, "thr_wr": thr_wr, "sharpe": sharpe,
            "n_test": len(test)}


def run_model(df_raw, factors, model_name, model_type="gbm", threshold=0.03):
    df, rc = prepare(df_raw, factors, threshold=threshold)
    wins = gen_windows(df)
    results = []
    for wid, tr, ts, te in wins:
        r = eval_window(df, rc, tr, ts, te, model_type=model_type)
        if r:
            r["wid"] = wid
            r["period"] = f"{ts.date()} ~ {te.date()}"
            results.append(r)
    return results


def main():
    df = load_data()

    models = [
        ("A: LR 34因子", ALL_34, "lr", 0.05),
        ("B: GBM 34因子", ALL_34, "gbm", 0.05),
        ("C: GBM 15穩定+反向投信", STABLE_15, "gbm", 0.03),
    ]

    all_results = {}
    for name, factors, mtype, thr in models:
        print(f"\n  跑 {name}...")
        all_results[name] = run_model(df, factors, name, model_type=mtype, threshold=thr)

    # 找共同窗口
    common_wids = None
    for name, res in all_results.items():
        wids = set(r["wid"] for r in res)
        common_wids = wids if common_wids is None else common_wids & wids
    common_wids = sorted(common_wids) if common_wids else []

    print(f"\n{'=' * 90}")
    print(f"  Walk-Forward 新舊模型比較（{len(common_wids)} 個共同窗口）")
    print(f"{'=' * 90}")

    # 逐窗口比較
    for wid in common_wids:
        rows = {name: next(r for r in res if r["wid"] == wid) for name, res in all_results.items()}
        period = list(rows.values())[0]["period"]
        print(f"\n  Window {wid}: {period}")
        print(f"  {'模型':>26} {'IC':>8} {'t':>6} {'Top10%報酬':>10} {'超額':>8} {'勝率':>6} {'Sharpe':>7}")
        print(f"  {'─' * 75}")
        for name in [m[0] for m in models]:
            r = rows[name]
            mark = " ★" if r["ic"] > 0.05 and r["ic_t"] > 2 else ""
            print(f"  {name:>26} {r['ic']:>+8.4f} {r['ic_t']:>+6.1f} {r['top_ret']*100:>+9.1f}% "
                  f"{r['excess']*100:>+7.1f}% {r['wr']:>5.0%} {r['sharpe']:>7.2f}{mark}")

    # 彙總
    print(f"\n{'=' * 90}")
    print(f"  彙總（跨所有窗口平均）")
    print(f"{'=' * 90}")
    print(f"\n  {'模型':>26} {'avgIC':>8} {'minIC':>8} {'IC>0':>6} {'pass':>5} "
          f"{'avg報酬':>8} {'avg超額':>8} {'avgWR':>6} {'Sharpe':>7}")
    print(f"  {'─' * 85}")

    for name in [m[0] for m in models]:
        res = [r for r in all_results[name] if r["wid"] in common_wids]
        ics = [r["ic"] for r in res]
        print(f"  {name:>26} {np.mean(ics):>+8.4f} {np.min(ics):>+8.4f} "
              f"{sum(1 for x in ics if x > 0)/len(ics):>5.0%} "
              f"{sum(1 for x in ics if x > 0.05)}/{len(ics):>1} "
              f"{np.mean([r['top_ret'] for r in res])*100:>+7.1f}% "
              f"{np.mean([r['excess'] for r in res])*100:>+7.1f}% "
              f"{np.mean([r['wr'] for r in res]):>5.0%} "
              f"{np.mean([r['sharpe'] for r in res]):>7.2f}")


if __name__ == "__main__":
    main()

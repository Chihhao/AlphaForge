"""
Walk-Forward 驗證：加入營收衍生因子是否提升模型績效
比較：
A) 現有 15 因子（baseline）
B) 15 因子 + rev_surprise
C) 15 因子 + rev_surprise + rev_accel
D) 15 因子 + rev_surprise + rev_accel + rev_beat_streak
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
    # 價格 + 特徵
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

    # 營收
    rev_sql = text("""
        SELECT stock_id, year, month, revenue, revenue_yoy as rev_yoy_raw
        FROM stock_revenue_history WHERE revenue > 0
        ORDER BY stock_id, year, month
    """)
    rev = pd.read_sql(rev_sql, engine)
    rev["announce_date"] = pd.to_datetime(
        rev["year"].astype(str) + "-" + rev["month"].astype(str).str.zfill(2) + "-10"
    )
    rev = rev.sort_values(["stock_id", "announce_date"])
    g = rev.groupby("stock_id")

    # rev_surprise
    rev["rev_ma3"] = g["revenue"].transform(lambda x: x.rolling(3, min_periods=2).mean().shift(1))
    rev["rev_surprise"] = (rev["revenue"] - rev["rev_ma3"]) / rev["rev_ma3"] * 100

    # rev_accel
    rev["rev_accel"] = g["rev_yoy_raw"].diff()

    # rev_beat_streak
    def streak(s):
        result = []
        count = 0
        for v in s:
            if v is not None and v > 0:
                count += 1
            else:
                count = 0
            result.append(count)
        return result
    rev["rev_beat_streak"] = g["rev_yoy_raw"].transform(streak)

    # merge_asof 到每日
    rev_factors = rev[["stock_id", "announce_date", "rev_surprise", "rev_accel", "rev_beat_streak"]].copy()
    rev_factors = rev_factors.rename(columns={"announce_date": "date"})
    rev_factors = rev_factors.sort_values(["stock_id", "date"])
    df = df.sort_values(["stock_id", "date"])

    parts = []
    for sid, grp_p in df.groupby("stock_id"):
        grp_r = rev_factors[rev_factors["stock_id"] == sid]
        if grp_r.empty:
            parts.append(grp_p)
            continue
        m = pd.merge_asof(grp_p, grp_r.drop(columns=["stock_id"]), on="date", direction="backward")
        parts.append(m)

    df = pd.concat(parts, ignore_index=True)
    df = df.sort_values(["stock_id", "date"])

    print(f"[Data] {len(df):,} 筆，{df['date'].min().date()} ~ {df['date'].max().date()}")
    print(f"[Coverage] rev_surprise: {df['rev_surprise'].notna().mean():.0%}, "
          f"rev_accel: {df['rev_accel'].notna().mean():.0%}, "
          f"rev_beat_streak: {df['rev_beat_streak'].notna().mean():.0%}")
    return df


def prepare(df, factors, forward_days=20, threshold=0.03):
    df = df.sort_values(["stock_id", "date"]).copy()
    df["forward_close"] = df.groupby("stock_id")["close"].shift(-forward_days)
    df["forward_return"] = (df["forward_close"] - df["close"]) / df["close"]
    df["label"] = (df["forward_return"] > threshold).astype(float)
    df = df[df["close"] > df["ma60"]].copy()
    for f in factors:
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


def run_strategy(df_raw, name, factors):
    df = prepare(df_raw, factors)
    rc = [f"{f}_rank" for f in factors if f"{f}_rank" in df.columns]
    wins = gen_windows(df)
    all_ics, monthly_rets = [], []

    print(f"\n{'─' * 70}")
    print(f"  {name}（{len(factors)} 因子）")
    print(f"{'─' * 70}")

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
        all_ics.append(ic)

        # Top 10%
        cut = np.percentile(prob, 90)
        top = prob >= cut
        wr = float(np.nanmean(fwd[top] > 0))

        # Monthly returns
        test["_top"] = top
        test["_m"] = test["date"].dt.to_period("M")
        for _, g in test[test["_top"]].groupby("_m"):
            monthly_rets.append(float(np.nanmean(g["forward_return"].values)) - COST)

        # Long-short
        bot = prob <= np.percentile(prob, 10)
        ls = np.nanmean(fwd[top]) - np.nanmean(fwd[bot])

        mark = "PASS" if ic > 0.05 else "---"
        print(f"  W{wid} {ts.date()}~{te.date()} IC={ic:+.4f} WR={wr:.0%} "
              f"L-S={ls * 100:+.1f}% [{mark}]")

    if not all_ics:
        return None

    net = np.array(monthly_rets)
    ann = np.mean(net) * 12
    vol = np.std(net) * np.sqrt(12) if len(net) > 1 else 0
    sh = ann / vol if vol > 0 else 0
    cum = np.cumprod(1 + net)
    pk = np.maximum.accumulate(cum)
    dd = np.min((cum - pk) / pk) if len(cum) > 0 else 0

    print(f"\n  彙總: avgIC={np.mean(all_ics):+.4f} minIC={np.min(all_ics):+.4f} "
          f"IC>0={sum(1 for x in all_ics if x > 0)}/{len(all_ics)} "
          f"年化={ann * 100:+.1f}% Sharpe={sh:.2f} MaxDD={dd * 100:.1f}%")

    return {
        "name": name, "n_factors": len(factors),
        "avg_ic": np.mean(all_ics), "min_ic": np.min(all_ics),
        "ic_pos": f"{sum(1 for x in all_ics if x > 0)}/{len(all_ics)}",
        "ann": ann, "sharpe": sh, "max_dd": dd,
    }


def main():
    df = load_data()
    results = []

    # A: baseline
    r = run_strategy(df, "A: 現有 15 因子", STABLE_15)
    if r: results.append(r)

    # B: + rev_surprise
    r = run_strategy(df, "B: +rev_surprise", STABLE_15 + ["rev_surprise"])
    if r: results.append(r)

    # C: + rev_surprise + rev_accel
    r = run_strategy(df, "C: +surprise+accel", STABLE_15 + ["rev_surprise", "rev_accel"])
    if r: results.append(r)

    # D: + 全部營收因子
    r = run_strategy(df, "D: +surprise+accel+streak",
                     STABLE_15 + ["rev_surprise", "rev_accel", "rev_beat_streak"])
    if r: results.append(r)

    # 比較表
    print(f"\n{'=' * 80}")
    print(f"  Walk-Forward 全策略比較（20d, MA60, gap=0）")
    print(f"{'=' * 80}")
    print(f"\n  {'策略':>28} {'因子':>4} {'avgIC':>7} {'minIC':>7} {'IC>0':>5} "
          f"{'年化':>7} {'Sharpe':>7} {'MaxDD':>7}")
    print("  " + "─" * 72)
    for r in results:
        print(f"  {r['name']:>28} {r['n_factors']:>4} {r['avg_ic']:>+7.4f} {r['min_ic']:>+7.4f} "
              f"{r['ic_pos']:>5} {r['ann'] * 100:>+6.1f}% {r['sharpe']:>7.2f} {r['max_dd'] * 100:>+6.1f}%")

    # 和 baseline 比較
    if len(results) >= 2:
        bl = results[0]
        print(f"\n  === vs Baseline ===")
        for r in results[1:]:
            d_ic = r["avg_ic"] - bl["avg_ic"]
            d_sh = r["sharpe"] - bl["sharpe"]
            d_ann = (r["ann"] - bl["ann"]) * 100
            verdict = "✓ 改善" if d_sh > 0.05 else ("— 持平" if abs(d_sh) <= 0.05 else "✗ 退步")
            print(f"  {r['name']:>28}: IC Δ{d_ic:+.4f}, Sharpe Δ{d_sh:+.2f}, 年化 Δ{d_ann:+.1f}%  {verdict}")


if __name__ == "__main__":
    main()

"""
Alpha 診斷 V3 — 精準聚焦：

1. 30d: Top 10% vs Top 20% vs Top 5% 選股效果
2. 10d: 用 30d 模型做前置過濾（雙模型共振）
3. 10d: 移除 MA60 + 新特徵 + 調參 的完整回測（含 Sharpe）
4. 計算每個策略的年化報酬與 Sharpe Ratio
"""
from __future__ import annotations

import os
import warnings
from datetime import date, timedelta

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.ensemble import HistGradientBoostingClassifier
from sqlalchemy import create_engine, text

warnings.filterwarnings("ignore")

PG_URL = os.getenv("PG_URL", "postgresql://alphaforge:alphaforge_secret@10.0.4.3:5433/alphaforge")
engine = create_engine(PG_URL)

LOOKBACK_DAYS = 730
TEST_MONTHS = 6
GAP_MONTHS = 1
COST = 0.006


def load_data():
    cutoff = date.today() - timedelta(days=LOOKBACK_DAYS)
    sql = text("""
        SELECT sf.stock_id, sf.date, sf.close, sf.ma5, sf.ma10, sf.ma20, sf.ma60,
               sf.change_pct, sf.rsi14, sf.rsi2, sf.k, sf.d,
               sf.macd_dif, sf.macd_osc, sf.bias5, sf.bias10, sf.bias20,
               sf.bb_pctb, sf.vol_ratio,
               sf.yield_rate, sf.roe, sf.pb_ratio, sf.revenue_yoy,
               sf.foreign_net_buy, sf.foreign_buy_5d, sf.trust_net_buy, sf.trust_buy_5d,
               sf.margin_chg_5d, sf.dealer_net_buy, sf.dealer_buy_5d,
               sf.price_vs_high20, sf.ma_trend, sf.sector_rs,
               sf.foreign_hold_pct, sf.foreign_hold_chg_5d, sf.etf_net_flow_5d,
               sf.foreign_buy_10d, sf.foreign_buy_20d,
               sf.trust_buy_10d, sf.trust_buy_20d,
               sf.dealer_buy_10d, sf.dealer_buy_20d,
               sf.atr20, sf.atr_pct, sf.market_breadth, sf.volume
        FROM stock_features sf
        WHERE sf.date >= :cutoff AND sf.close > 0
        ORDER BY sf.date, sf.stock_id
    """)
    df = pd.read_sql(sql, engine, params={"cutoff": cutoff})
    df["date"] = pd.to_datetime(df["date"])
    print(f"[Data] {len(df):,} 筆")
    return df


def add_features(df):
    g = df.groupby("stock_id")
    df["mom_5d"] = g["close"].pct_change(5)
    df["mom_20d"] = g["close"].pct_change(20)
    df["vol_adj_mom_5d"] = df["mom_5d"] / df["atr_pct"].clip(lower=0.01)
    df["inst_flow_5d"] = df["foreign_buy_5d"].fillna(0) + df["trust_buy_5d"].fillna(0)
    df["inst_flow_10d"] = df["foreign_buy_10d"].fillna(0) + df["trust_buy_10d"].fillna(0)
    df["inst_flow_20d"] = df["foreign_buy_20d"].fillna(0) + df["trust_buy_20d"].fillna(0)
    df["chip_consensus"] = (
        (df["foreign_buy_5d"].fillna(0) > 0).astype(float) +
        (df["trust_buy_5d"].fillna(0) > 0).astype(float) +
        (df["dealer_buy_5d"].fillna(0) > 0).astype(float)
    )
    df["ma60_dist"] = (df["close"] - df["ma60"]) / df["ma60"].clip(lower=1)
    df["vol_spike"] = df["vol_ratio"].clip(upper=5)
    return df


BASE_FACTORS = [
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

EXTENDED_FACTORS = BASE_FACTORS + [
    "mom_5d", "mom_20d", "vol_adj_mom_5d",
    "inst_flow_5d", "inst_flow_10d", "inst_flow_20d",
    "chip_consensus", "ma60_dist", "vol_spike",
]


def qrank(df, cols):
    df = df.copy()
    rc = []
    for c in cols:
        r = f"rank_{c}"
        df[r] = df.groupby("date")[c].rank(pct=True, method="average") * 100
        rc.append(r)
    return df, rc


def tw(dates):
    max_d = dates.max()
    d = (max_d - dates).dt.days
    w = np.exp(-0.001 * d)
    return np.clip(w, 0.2, 1.0)


def train_model(train_df, rank_cols, label_col="label", params=None):
    X = train_df[rank_cols].values
    y = train_df[label_col].values
    w = tw(train_df["date"])
    defaults = dict(
        max_iter=200, max_depth=4, max_leaf_nodes=15,
        learning_rate=0.01, min_samples_leaf=100,
        l2_regularization=1.0, random_state=42, verbose=0,
        class_weight="balanced",
    )
    if params:
        defaults.update(params)
    model = HistGradientBoostingClassifier(**defaults)
    model.fit(X, y, sample_weight=w)
    return model


def evaluate(test_df, prob, threshold, top_pct, label):
    test = test_df.copy()
    fwd = test["forward_return"].values
    cutoff_val = np.percentile(prob, (1 - top_pct) * 100)
    top_mask = prob >= cutoff_val
    top_ret = fwd[top_mask]
    n_top = top_mask.sum()

    wr = np.nanmean(top_ret > threshold)
    mkt_wr = np.nanmean(fwd > threshold)
    avg = np.nanmean(top_ret)
    avg_net = avg - COST
    mkt_avg = np.nanmean(fwd)

    # IC
    test["_prob"] = prob
    daily_ics = []
    for _, grp in test.groupby("date"):
        if len(grp) < 30:
            continue
        p = grp["_prob"].values
        r = grp["forward_return"].values
        valid = ~np.isnan(r)
        if valid.sum() < 20:
            continue
        ic, _ = stats.spearmanr(p[valid], r[valid])
        if not np.isnan(ic):
            daily_ics.append(ic)
    ic_mean = np.mean(daily_ics) if daily_ics else 0
    ic_t = ic_mean / (np.std(daily_ics) / np.sqrt(len(daily_ics))) if daily_ics and np.std(daily_ics) > 0 else 0

    # 月報酬序列 → Sharpe
    test["_top"] = top_mask
    test["_month"] = test["date"].dt.to_period("M")
    monthly_ret = []
    for _, grp in test[test["_top"]].groupby("_month"):
        m = np.nanmean(grp["forward_return"].values) - COST
        monthly_ret.append(m)
    sharpe = (np.mean(monthly_ret) / np.std(monthly_ret) * np.sqrt(12)) if len(monthly_ret) > 2 and np.std(monthly_ret) > 0 else 0

    print(f"  [{label}]")
    print(f"    IC={ic_mean:+.4f}(t={ic_t:+.2f})  WR={wr:.1%} vs {mkt_wr:.1%} (+{wr-mkt_wr:.1%})")
    print(f"    Avg={avg*100:+.2f}%  Net={avg_net*100:+.2f}%  Mkt={mkt_avg*100:+.2f}%  Excess={((avg-mkt_avg)*100):+.2f}%")
    print(f"    n_picks={n_top}  Sharpe(ann)={sharpe:.2f}  monthly_wins={sum(1 for r in monthly_ret if r>0)}/{len(monthly_ret)}")

    return {"ic": ic_mean, "ic_t": ic_t, "wr": wr, "avg_net": avg_net, "sharpe": sharpe, "n": n_top}


def run(df_raw):
    df = add_features(df_raw)
    max_date = df["date"].max()
    test_start = max_date - pd.DateOffset(months=TEST_MONTHS)
    train_end = max_date - pd.DateOffset(months=TEST_MONTHS + GAP_MONTHS)

    # ─── 30d: Top-K 分析 ──────────────────────────────────────────
    print("=" * 70)
    print("  30d: Top-K 選股分析")
    print("=" * 70)
    df_30 = df.copy()
    df_30["forward_close"] = df_30.groupby("stock_id")["close"].shift(-30)
    df_30["forward_return"] = (df_30["forward_close"] - df_30["close"]) / df_30["close"]
    df_30["label"] = (df_30["forward_return"] > 0.05).astype(float)
    df_30_up = df_30[df_30["close"] > df_30["ma60"]].copy()
    df_30_up, rc30 = qrank(df_30_up, BASE_FACTORS)
    train30 = df_30_up[df_30_up["date"] <= train_end].dropna(subset=["label"])
    test30 = df_30_up[df_30_up["date"] >= test_start].dropna(subset=["label", "forward_return"])
    model30 = train_model(train30, rc30)
    prob30 = model30.predict_proba(test30[rc30].values)[:, 1]

    for top_pct in [0.20, 0.10, 0.05]:
        evaluate(test30, prob30, 0.05, top_pct, f"30d Top{top_pct:.0%}")

    # ─── 10d: 多策略比較 ──────────────────────────────────────────
    print("\n" + "=" * 70)
    print("  10d: 策略比較")
    print("=" * 70)
    df_10 = df.copy()
    df_10["forward_close"] = df_10.groupby("stock_id")["close"].shift(-10)
    df_10["forward_return"] = (df_10["forward_close"] - df_10["close"]) / df_10["close"]
    df_10["label"] = (df_10["forward_return"] > 0.03).astype(float)

    # A: Baseline (MA60)
    df_10a = df_10[df_10["close"] > df_10["ma60"]].copy()
    avail_a = [f for f in BASE_FACTORS if f in df_10a.columns]
    df_10a, rc10a = qrank(df_10a, avail_a)
    train10a = df_10a[df_10a["date"] <= train_end].dropna(subset=["label"])
    test10a = df_10a[df_10a["date"] >= test_start].dropna(subset=["label", "forward_return"])
    model10a = train_model(train10a, rc10a)
    prob10a = model10a.predict_proba(test10a[rc10a].values)[:, 1]
    evaluate(test10a, prob10a, 0.03, 0.20, "10d A: Baseline+MA60")

    # B: 全股 + 新特徵 + 調參
    avail_b = [f for f in EXTENDED_FACTORS if f in df_10.columns]
    df_10b = df_10.copy()
    df_10b, rc10b = qrank(df_10b, avail_b)
    train10b = df_10b[df_10b["date"] <= train_end].dropna(subset=["label"])
    test10b = df_10b[df_10b["date"] >= test_start].dropna(subset=["label", "forward_return"])
    model10b = train_model(train10b, rc10b,
                           params=dict(max_iter=300, max_depth=5, max_leaf_nodes=20,
                                       min_samples_leaf=80, l2_regularization=2.0))
    prob10b = model10b.predict_proba(test10b[rc10b].values)[:, 1]
    evaluate(test10b, prob10b, 0.03, 0.20, "10d B: AllStocks+NewFeats+Tuned")
    evaluate(test10b, prob10b, 0.03, 0.10, "10d B: AllStocks+NewFeats+Tuned Top10%")

    # C: 30d 共振 — 只在 30d 做多訊號的股票中做 10d 選股
    # 在 test 期間，取每日 30d 模型 top 50% 的股票，然後用 10d 模型排序
    print("\n  --- 30d 共振策略 ---")
    df_10c = df_10.copy()
    # 需要 MA60 filter 後的 30d 預測
    df_10c_up = df_10c[df_10c["close"] > df_10c["ma60"]].copy()
    avail_c = [f for f in EXTENDED_FACTORS if f in df_10c_up.columns]
    df_10c_up, rc10c = qrank(df_10c_up, avail_c)
    train10c = df_10c_up[df_10c_up["date"] <= train_end].dropna(subset=["label"])
    test10c = df_10c_up[df_10c_up["date"] >= test_start].dropna(subset=["label", "forward_return"])

    # 30d 模型預測（用已訓練的 model30，但要對 test10c 的數據做預測）
    # 需要 30d rank columns
    df_10c_30r = df_10c_up.copy()
    rc30_available = [c for c in rc30 if c in df_10c_30r.columns]
    if len(rc30_available) == len(rc30):
        prob30_on_10c = model30.predict_proba(test10c[rc30].values)[:, 1]
        # 只保留 30d 預測 top 50% 的股票
        p50_30 = np.percentile(prob30_on_10c, 50)
        resonance_mask = prob30_on_10c >= p50_30

        # 10d 模型在這些股票中重新排序
        model10c = train_model(train10c, rc10c,
                               params=dict(max_iter=300, max_depth=5, max_leaf_nodes=20,
                                           min_samples_leaf=80, l2_regularization=2.0))
        prob10c = model10c.predict_proba(test10c[rc10c].values)[:, 1]
        # 只評估在共振範圍內的
        test10c_res = test10c[resonance_mask].copy()
        prob10c_res = prob10c[resonance_mask]
        evaluate(test10c_res, prob10c_res, 0.03, 0.20, "10d C: 30d共振 Top20%")
        evaluate(test10c_res, prob10c_res, 0.03, 0.10, "10d C: 30d共振 Top10%")

        # D: 更嚴格共振 — 30d top 30%
        p70_30 = np.percentile(prob30_on_10c, 70)
        strict_mask = prob30_on_10c >= p70_30
        test10c_strict = test10c[strict_mask].copy()
        prob10c_strict = prob10c[strict_mask]
        evaluate(test10c_strict, prob10c_strict, 0.03, 0.20, "10d D: 30d嚴格共振(Top30%) Top20%")

    print("\n" + "=" * 70)
    print("  總結：可部署策略排名（按 Sharpe 排序）")
    print("=" * 70)


if __name__ == "__main__":
    df = load_data()
    run(df)

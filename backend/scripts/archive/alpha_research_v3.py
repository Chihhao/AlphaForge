"""
Alpha Research V3 — 進階實驗

基於 Phase 3 結論（11 穩定因子 IC 100% 正），探索進一步提升空間：

實驗 1: 加入反向因子（negated trust_buy = 散戶逆向指標）
實驗 2: 基本面交互特徵（ROE×外資買、殖利率×股淨比）
實驗 3: 動態門檻（根據市場波動調整 label threshold）
實驗 4: Ensemble — Classification + Regression 加權
實驗 5: 純基本面（4 因子）vs 基本面+外資（7 因子）vs 擴展（11 因子）的報酬分解
"""
from __future__ import annotations

import os
import warnings
from datetime import date, timedelta

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sqlalchemy import create_engine, text

warnings.filterwarnings("ignore")

PG_URL = os.getenv("PG_URL", "postgresql://alphaforge:alphaforge_secret@10.0.4.3:5433/alphaforge")
engine = create_engine(PG_URL)
COST = 0.006

STABLE_11 = [
    "roe", "yield_rate", "pb_ratio", "revenue_yoy",
    "foreign_hold_chg_5d", "foreign_net_buy", "foreign_buy_5d",
    "dealer_buy_20d", "vol_ratio", "foreign_buy_10d", "price_vs_high20",
]

# 反向因子（穩定負 IC → 取負數後變正 IC）
REVERSE_FACTORS = ["trust_buy_5d", "trust_buy_10d", "trust_buy_20d", "trust_net_buy"]

# 基本面交互特徵名稱
INTERACTION_FEATURES = [
    "roe_x_foreign",       # ROE 高且外資買
    "yield_x_pb",          # 殖利率高且低股淨比（價值股）
    "rev_x_chip",          # 營收成長且法人買
    "quality_score",       # 綜合品質分數
]


def load_data():
    all_factors = set(STABLE_11 + REVERSE_FACTORS +
                      ["ma60", "close", "stock_id", "date", "volume",
                       "trust_net_buy", "trust_buy_5d", "trust_buy_10d", "trust_buy_20d"])
    cols = ", ".join(sorted(all_factors))
    sql = text(f"SELECT {cols} FROM stock_features WHERE close > 0 AND date >= '2023-03-01' ORDER BY date, stock_id")
    df = pd.read_sql(sql, engine)
    df["date"] = pd.to_datetime(df["date"])
    print(f"[Data] {len(df):,} 筆，{df['date'].min().date()} ~ {df['date'].max().date()}")
    return df


def add_reverse_factors(df):
    """將負 IC 因子取反（乘以 -1），使其成為正 IC 因子"""
    for f in REVERSE_FACTORS:
        if f in df.columns:
            df[f"neg_{f}"] = -df[f].fillna(0)
    return df


def add_interaction_features(df):
    """基本面交互特徵"""
    # ROE × 外資買超（品質 + 聰明錢共識）
    roe_rank = df.groupby("date")["roe"].rank(pct=True, na_option="keep")
    fb_rank = df.groupby("date")["foreign_buy_5d"].rank(pct=True, na_option="keep")
    df["roe_x_foreign"] = roe_rank * fb_rank

    # 殖利率 × (1/股淨比)（高殖利率低估值 = 價值股）
    yr_rank = df.groupby("date")["yield_rate"].rank(pct=True, na_option="keep")
    pb_inv_rank = df.groupby("date")["pb_ratio"].rank(pct=True, ascending=False, na_option="keep")
    df["yield_x_pb"] = yr_rank * pb_inv_rank

    # 營收 YoY × 法人合力
    rev_rank = df.groupby("date")["revenue_yoy"].rank(pct=True, na_option="keep")
    chip = df["foreign_buy_5d"].fillna(0) - df["trust_buy_5d"].fillna(0)  # 外資買 - 投信買
    chip_rank = df.groupby("date")[chip.name if hasattr(chip, 'name') else 'chip_tmp'].rank(pct=True, na_option="keep") if False else None
    # 簡化：用 foreign_net_buy rank
    fn_rank = df.groupby("date")["foreign_net_buy"].rank(pct=True, na_option="keep")
    df["rev_x_chip"] = rev_rank * fn_rank

    # 綜合品質分數（基本面 4 因子等權平均 rank）
    df["quality_score"] = (roe_rank + yr_rank +
                           df.groupby("date")["revenue_yoy"].rank(pct=True, na_option="keep") +
                           pb_inv_rank) / 4.0

    return df


def prepare(df, factors, forward_days=30, threshold=0.05, ma60_filter=True):
    df = df.sort_values(["stock_id", "date"]).copy()
    df["forward_close"] = df.groupby("stock_id")["close"].shift(-forward_days)
    df["forward_return"] = (df["forward_close"] - df["close"]) / df["close"]
    df["label"] = (df["forward_return"] > threshold).astype(float)
    if ma60_filter and "ma60" in df.columns:
        df = df[df["close"] > df["ma60"]].copy()
    rank_cols = []
    for f in factors:
        if f in df.columns:
            rc = f"{f}_rank"
            df[rc] = df.groupby("date")[f].rank(pct=True, na_option="keep")
            rank_cols.append(rc)
    return df, rank_cols


def generate_windows(df, test_months=4, gap_months=1, min_train_months=8):
    min_d, max_d = df["date"].min(), df["date"].max()
    first_test = min_d + pd.DateOffset(months=min_train_months + gap_months)
    windows = []
    ts = first_test
    wid = 1
    while ts + pd.DateOffset(months=2) <= max_d:
        te = min(ts + pd.DateOffset(months=test_months), max_d)
        tr = ts - pd.DateOffset(months=gap_months)
        windows.append((wid, pd.Timestamp(tr), pd.Timestamp(ts), pd.Timestamp(te)))
        ts += pd.DateOffset(months=test_months)
        wid += 1
    return windows


def walk_forward(df, rank_cols, strategy_name, use_regression=False, ensemble=False):
    windows = generate_windows(df)
    all_ics, all_excess, all_sharpe, monthly_rets = [], [], [], []

    for wid, train_end, test_start, test_end in windows:
        train = df[df["date"] <= train_end].dropna(subset=["label"])
        test = df[(df["date"] >= test_start) & (df["date"] <= test_end)].dropna(
            subset=["label", "forward_return"])
        if len(train) < 2000 or len(test) < 300:
            continue

        X_tr, y_tr = train[rank_cols].values, train["label"].values
        base_year = train_end.year
        w = np.clip(1.0 - 0.2 * (base_year - train["date"].dt.year), 0.2, 1.0).values

        if ensemble:
            # Classification
            clf = HistGradientBoostingClassifier(
                max_iter=200, max_depth=4, max_leaf_nodes=15,
                learning_rate=0.01, min_samples_leaf=100,
                l2_regularization=1.0, random_state=42, verbose=0,
                class_weight="balanced")
            clf.fit(X_tr, y_tr, sample_weight=w)
            p_clf = clf.predict_proba(test[rank_cols].values)[:, 1]
            # Regression
            y_reg = train["forward_return"].values.clip(-0.5, 0.5)
            reg = HistGradientBoostingRegressor(
                max_iter=200, max_depth=4, max_leaf_nodes=15,
                learning_rate=0.01, min_samples_leaf=100,
                l2_regularization=1.0, random_state=42, verbose=0)
            reg.fit(X_tr, y_reg, sample_weight=w)
            p_reg = reg.predict(test[rank_cols].values)
            p_reg_n = (p_reg - p_reg.min()) / (p_reg.max() - p_reg.min() + 1e-9)
            prob = 0.5 * p_clf + 0.5 * p_reg_n
        elif use_regression:
            y_reg = train["forward_return"].values.clip(-0.5, 0.5)
            model = HistGradientBoostingRegressor(
                max_iter=200, max_depth=4, max_leaf_nodes=15,
                learning_rate=0.01, min_samples_leaf=100,
                l2_regularization=1.0, random_state=42, verbose=0)
            model.fit(X_tr, y_reg, sample_weight=w)
            prob = model.predict(test[rank_cols].values)
        else:
            model = HistGradientBoostingClassifier(
                max_iter=200, max_depth=4, max_leaf_nodes=15,
                learning_rate=0.01, min_samples_leaf=100,
                l2_regularization=1.0, random_state=42, verbose=0,
                class_weight="balanced")
            model.fit(X_tr, y_tr, sample_weight=w)
            prob = model.predict_proba(test[rank_cols].values)[:, 1]

        test = test.copy()
        test["_prob"] = prob

        # IC
        daily_ics = []
        for _, grp in test.groupby("date"):
            if len(grp) < 50:
                continue
            p, r = grp["_prob"].values, grp["forward_return"].values
            valid = ~np.isnan(r)
            if valid.sum() < 30:
                continue
            ic, _ = stats.spearmanr(p[valid], r[valid])
            if not np.isnan(ic):
                daily_ics.append(ic)
        ic = np.mean(daily_ics) if daily_ics else 0
        ic_t = ic / (np.std(daily_ics) / np.sqrt(len(daily_ics))) if daily_ics and np.std(daily_ics) > 0 else 0
        all_ics.append(ic)

        # Top 10%
        cutoff = np.percentile(prob, 90)
        top_mask = prob >= cutoff
        fwd = test["forward_return"].values
        excess = np.nanmean(fwd[top_mask]) - np.nanmean(fwd)
        all_excess.append(excess)

        # Monthly
        test["_top"] = top_mask
        test["_month"] = test["date"].dt.to_period("M")
        for _, g in test[test["_top"]].groupby("_month"):
            monthly_rets.append(float(np.nanmean(g["forward_return"].values)) - COST)

        mark = "PASS" if ic > 0.05 and ic_t > 2 else "---"
        wr = float(np.nanmean(fwd[top_mask] > 0.05))
        mkt_wr = float(np.nanmean(fwd > 0.05))
        print(f"    W{wid} {test_start.date()}~{test_end.date()} IC={ic:+.4f}(t={ic_t:+.1f}) "
              f"WR={wr:.0%}vs{mkt_wr:.0%} ex={excess*100:+.1f}% [{mark}]")

    if not all_ics:
        return None

    net = np.array(monthly_rets)
    ann_r = np.mean(net) * 12
    ann_v = np.std(net) * np.sqrt(12)
    sharpe = ann_r / ann_v if ann_v > 0 else 0
    cum = np.cumprod(1 + net)
    peak = np.maximum.accumulate(cum)
    max_dd = np.min((cum - peak) / peak)
    win_m = sum(1 for x in net if x > 0)

    return {
        "name": strategy_name,
        "avg_ic": np.mean(all_ics), "min_ic": np.min(all_ics),
        "ic_pos": sum(1 for x in all_ics if x > 0) / len(all_ics),
        "n_pass": sum(1 for x in all_ics if x > 0.05),
        "n_win": len(all_ics),
        "avg_excess": np.mean(all_excess),
        "ann_return": ann_r, "sharpe": sharpe, "max_dd": max_dd,
        "win_month": f"{win_m}/{len(net)}",
    }


def main():
    df_raw = load_data()
    df_raw = add_reverse_factors(df_raw)
    df_raw = add_interaction_features(df_raw)
    results = []

    print("\n" + "=" * 70)
    print("  Alpha Research V3 — 進階實驗")
    print("=" * 70)

    # Baseline: 11 穩定因子 Classification（上次最佳）
    print("\n  [Baseline] 11 穩定因子 Classification")
    df_b, rc_b = prepare(df_raw, STABLE_11)
    r = walk_forward(df_b, rc_b, "Baseline: 穩定11")
    if r: results.append(r)

    # 實驗 1: + 反向因子（neg_trust）
    reverse_names = [f"neg_{f}" for f in REVERSE_FACTORS]
    factors_1 = STABLE_11 + reverse_names
    print(f"\n  [Exp 1] 穩定11 + 反向投信({len(reverse_names)}個)")
    df_1, rc_1 = prepare(df_raw, factors_1)
    r = walk_forward(df_1, rc_1, "穩定11+反向投信")
    if r: results.append(r)

    # 實驗 2: + 交互特徵
    factors_2 = STABLE_11 + INTERACTION_FEATURES
    print(f"\n  [Exp 2] 穩定11 + 交互特徵(4個)")
    df_2, rc_2 = prepare(df_raw, factors_2)
    r = walk_forward(df_2, rc_2, "穩定11+交互")
    if r: results.append(r)

    # 實驗 3: + 反向 + 交互
    factors_3 = STABLE_11 + reverse_names + INTERACTION_FEATURES
    print(f"\n  [Exp 3] 穩定11 + 反向 + 交互 (={len(factors_3)}個)")
    df_3, rc_3 = prepare(df_raw, factors_3)
    r = walk_forward(df_3, rc_3, "穩定11+反向+交互")
    if r: results.append(r)

    # 實驗 4: Ensemble（穩定11 Clf+Reg）
    print(f"\n  [Exp 4] Ensemble (Clf+Reg) 穩定11")
    r = walk_forward(df_b, rc_b, "Ensemble 穩定11", ensemble=True)
    if r: results.append(r)

    # 實驗 5: Ensemble + 反向投信
    print(f"\n  [Exp 5] Ensemble + 反向投信")
    r = walk_forward(df_1, rc_1, "Ensemble+反向投信", ensemble=True)
    if r: results.append(r)

    # 實驗 6: 純基本面 (4 因子)
    fund_only = ["roe", "yield_rate", "pb_ratio", "revenue_yoy"]
    print(f"\n  [Exp 6] 純基本面 (4因子)")
    df_6, rc_6 = prepare(df_raw, fund_only)
    r = walk_forward(df_6, rc_6, "純基本面(4)")
    if r: results.append(r)

    # 實驗 7: 基本面 + 外資 (7 因子)
    fund_chip = fund_only + ["foreign_hold_chg_5d", "foreign_net_buy", "foreign_buy_5d"]
    print(f"\n  [Exp 7] 基本面+外資 (7因子)")
    df_7, rc_7 = prepare(df_raw, fund_chip)
    r = walk_forward(df_7, rc_7, "基本面+外資(7)")
    if r: results.append(r)

    # 實驗 8: 穩定11 + 反向投信 + Regression
    print(f"\n  [Exp 8] 穩定11+反向投信 Regression")
    r = walk_forward(df_1, rc_1, "穩定11+反向 Reg", use_regression=True)
    if r: results.append(r)

    # 實驗 9: 動態門檻（thr=3%）
    print(f"\n  [Exp 9] 穩定11+反向投信 thr=3%")
    df_9, rc_9 = prepare(df_raw, factors_1, threshold=0.03)
    r = walk_forward(df_9, rc_9, "穩定+反向 thr3%")
    if r: results.append(r)

    # 實驗 10: Ensemble + 反向 + 交互
    print(f"\n  [Exp 10] Ensemble + 反向 + 交互")
    r = walk_forward(df_3, rc_3, "Ens+反向+交互", ensemble=True)
    if r: results.append(r)

    # 排名
    print(f"\n{'=' * 70}")
    print(f"  策略排名（按 IC×穩定性 排序）")
    print(f"{'=' * 70}")
    results.sort(key=lambda x: x["avg_ic"] * x["ic_pos"], reverse=True)
    print(f"\n  {'策略':>22} {'avgIC':>7} {'minIC':>7} {'IC>0':>5} {'pass':>5} "
          f"{'excess':>7} {'年化':>7} {'Sharpe':>7} {'MaxDD':>7} {'勝月':>7}")
    print("  " + "─" * 95)
    for r in results:
        print(f"  {r['name']:>22} {r['avg_ic']:>+7.4f} {r['min_ic']:>+7.4f} "
              f"{r['ic_pos']:>4.0%} {r['n_pass']}/{r['n_win']:>1} "
              f"{r['avg_excess']*100:>+6.1f}% {r['ann_return']*100:>+6.1f}% "
              f"{r['sharpe']:>7.2f} {r['max_dd']*100:>+6.1f}% {r['win_month']:>7}")


if __name__ == "__main__":
    main()

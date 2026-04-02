"""
Alpha Research V2 — 穩定因子策略深度驗證

基於 Phase 1+2 發現：
- 穩定因子 = roe, yield_rate, pb_ratio, revenue_yoy + 外資3因子
- 技術指標（RSI/MACD/KD/bias）全部是噪音，移除後 IC 更穩定
- MA60 過濾對 30d 有效

本腳本：
1. 穩定因子策略的逐窗口深度分析（含月度報酬明細）
2. 穩定因子 + Regression 混合策略
3. 敏感度分析：不同 Top-K%、不同 threshold
4. 年化報酬率與最大回撤估算
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

# ── 穩定因子（Phase 1B 發現：IC 全期正，穩定性 ≥60%）──────────────
STABLE_FACTORS = [
    "roe", "yield_rate", "pb_ratio", "revenue_yoy",  # 基本面
    "foreign_hold_chg_5d", "foreign_net_buy", "foreign_buy_5d",  # 外資動向
]

# 擴展穩定因子：加入次穩定因子（穩定性 50-70%）
EXTENDED_STABLE = STABLE_FACTORS + [
    "dealer_buy_20d", "vol_ratio", "foreign_buy_10d",  # 次穩定
    "price_vs_high20",  # 不穩定但 IC 高
]

# 全因子（對照組）
ALL_FACTORS = [
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


def load_data(start_date="2023-03-01"):
    all_cols = set(ALL_FACTORS + EXTENDED_STABLE + ["stock_id", "date", "close", "ma60", "volume"])
    cols = ", ".join(sorted(all_cols))
    sql = text(f"SELECT {cols} FROM stock_features WHERE close > 0 AND date >= :start ORDER BY date, stock_id")
    df = pd.read_sql(sql, engine, params={"start": start_date})
    df["date"] = pd.to_datetime(df["date"])
    print(f"[Data] {len(df):,} 筆，{df['date'].min().date()} ~ {df['date'].max().date()}")
    return df


def prepare(df, factors, forward_days=30, threshold=0.05):
    df = df.sort_values(["stock_id", "date"]).copy()
    df["forward_close"] = df.groupby("stock_id")["close"].shift(-forward_days)
    df["forward_return"] = (df["forward_close"] - df["close"]) / df["close"]
    df["label"] = (df["forward_return"] > threshold).astype(float)
    rank_cols = []
    for f in factors:
        if f in df.columns:
            rc = f"{f}_rank"
            df[rc] = df.groupby("date")[f].rank(pct=True, na_option="keep")
            rank_cols.append(rc)
    return df, rank_cols


def time_weights(dates, train_end_year):
    delta = train_end_year - dates.dt.year
    return np.clip(1.0 - 0.2 * delta, 0.2, 1.0).values


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


# ═══════════════════════════════════════════════════════════════════════
# 深度驗證
# ═══════════════════════════════════════════════════════════════════════
def deep_validate(df_raw, factors, strategy_name, forward_days=30, threshold=0.05,
                  ma60_filter=True, top_pct=0.10, use_regression=False):
    df, rank_cols = prepare(df_raw, factors, forward_days, threshold)
    if ma60_filter:
        df = df[df["close"] > df["ma60"]].copy()

    windows = generate_windows(df)
    print(f"\n{'─' * 70}")
    print(f"  {strategy_name}")
    print(f"  因子數={len(rank_cols)}, top={top_pct:.0%}, fwd={forward_days}d, thr={threshold:.0%}, MA60={'Y' if ma60_filter else 'N'}")
    print(f"  窗口數={len(windows)}")
    print(f"{'─' * 70}")

    all_monthly_returns = []
    all_ics = []
    window_stats = []

    for wid, train_end, test_start, test_end in windows:
        train = df[df["date"] <= train_end].dropna(subset=["label"])
        test = df[(df["date"] >= test_start) & (df["date"] <= test_end)].dropna(
            subset=["label", "forward_return"])

        if len(train) < 2000 or len(test) < 300:
            continue

        X_train, y_train = train[rank_cols].values, train["label"].values
        w = time_weights(train["date"], train_end.year)

        if use_regression:
            y_train_reg = train["forward_return"].values.clip(-0.5, 0.5)
            model = HistGradientBoostingRegressor(
                max_iter=200, max_depth=4, max_leaf_nodes=15,
                learning_rate=0.01, min_samples_leaf=100,
                l2_regularization=1.0, random_state=42, verbose=0)
            model.fit(X_train, y_train_reg, sample_weight=w)
            prob = model.predict(test[rank_cols].values)
        else:
            model = HistGradientBoostingClassifier(
                max_iter=200, max_depth=4, max_leaf_nodes=15,
                learning_rate=0.01, min_samples_leaf=100,
                l2_regularization=1.0, random_state=42, verbose=0,
                class_weight="balanced")
            model.fit(X_train, y_train, sample_weight=w)
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

        # Top picks 報酬
        cutoff = np.percentile(prob, (1 - top_pct) * 100)
        top_mask = prob >= cutoff
        fwd = test["forward_return"].values

        top_ret = fwd[top_mask]
        mkt_ret = np.nanmean(fwd)
        avg_ret = np.nanmean(top_ret)
        excess = avg_ret - mkt_ret

        wr = float(np.nanmean(top_ret > threshold))
        mkt_wr = float(np.nanmean(fwd > threshold))

        # 月度報酬
        test["_top"] = top_mask
        test["_month"] = test["date"].dt.to_period("M")
        for _, grp in test[test["_top"]].groupby("_month"):
            m_ret = float(np.nanmean(grp["forward_return"].values))
            all_monthly_returns.append({"month": str(grp["_month"].iloc[0]), "return": m_ret,
                                        "n_picks": len(grp), "window": wid})

        mark = "PASS" if ic > 0.05 and ic_t > 2 else "---"
        print(f"  W{wid} {test_start.date()}~{test_end.date()} "
              f"IC={ic:+.4f}(t={ic_t:+.1f}) WR={wr:.0%}vs{mkt_wr:.0%} "
              f"avg={avg_ret*100:+.1f}% ex={excess*100:+.1f}% n={len(test):,} [{mark}]")

        window_stats.append({
            "wid": wid, "ic": ic, "ic_t": ic_t, "wr": wr, "mkt_wr": mkt_wr,
            "avg_ret": avg_ret, "excess": excess, "n_test": len(test), "n_top": int(top_mask.sum()),
        })

    if not window_stats:
        print("  (窗口不足)")
        return None

    # 彙總
    monthly_df = pd.DataFrame(all_monthly_returns)
    net_monthly = monthly_df["return"].values - COST
    ann_return = np.mean(net_monthly) * 12
    ann_vol = np.std(net_monthly) * np.sqrt(12)
    sharpe = ann_return / ann_vol if ann_vol > 0 else 0

    # 最大回撤（月度累計）
    cum = np.cumprod(1 + net_monthly)
    peak = np.maximum.accumulate(cum)
    drawdown = (cum - peak) / peak
    max_dd = np.min(drawdown)

    # 勝月比
    win_months = np.sum(net_monthly > 0)
    total_months = len(net_monthly)

    avg_ic = np.mean(all_ics)
    min_ic = np.min(all_ics)
    ic_pos = sum(1 for x in all_ics if x > 0) / len(all_ics)
    n_pass = sum(1 for x in all_ics if x > 0.05)

    print(f"\n  彙總：")
    print(f"    IC: avg={avg_ic:+.4f} min={min_ic:+.4f} IC>0={ic_pos:.0%} pass={n_pass}/{len(window_stats)}")
    print(f"    年化報酬(扣成本): {ann_return*100:+.1f}%")
    print(f"    年化 Sharpe: {sharpe:.2f}")
    print(f"    最大月度回撤: {max_dd*100:.1f}%")
    print(f"    勝月比: {win_months}/{total_months} ({win_months/total_months:.0%})")

    return {
        "name": strategy_name, "avg_ic": avg_ic, "min_ic": min_ic,
        "ic_pos_pct": ic_pos, "n_pass": n_pass, "n_windows": len(window_stats),
        "ann_return": ann_return, "sharpe": sharpe, "max_dd": max_dd,
        "win_month_pct": win_months / total_months,
        "windows": window_stats,
    }


# ═══════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    df = load_data()
    results = []

    print("\n" + "=" * 70)
    print("  Phase 3: 穩定因子策略深度驗證")
    print("=" * 70)

    # A: 核心穩定因子 (7個) — Classification
    r = deep_validate(df, STABLE_FACTORS, "A: 穩定因子(7) Classification")
    if r: results.append(r)

    # B: 核心穩定因子 — Regression
    r = deep_validate(df, STABLE_FACTORS, "B: 穩定因子(7) Regression", use_regression=True)
    if r: results.append(r)

    # C: 擴展穩定因子 (11個) — Classification
    r = deep_validate(df, EXTENDED_STABLE, "C: 擴展穩定(11) Classification")
    if r: results.append(r)

    # D: 擴展穩定因子 — Regression
    r = deep_validate(df, EXTENDED_STABLE, "D: 擴展穩定(11) Regression", use_regression=True)
    if r: results.append(r)

    # E: Top 5%
    r = deep_validate(df, STABLE_FACTORS, "E: 穩定因子 Top5%", top_pct=0.05)
    if r: results.append(r)

    # F: Top 20%
    r = deep_validate(df, STABLE_FACTORS, "F: 穩定因子 Top20%", top_pct=0.20)
    if r: results.append(r)

    # G: threshold 3%
    r = deep_validate(df, STABLE_FACTORS, "G: 穩定因子 thr=3%", threshold=0.03)
    if r: results.append(r)

    # H: 無 MA60 過濾
    r = deep_validate(df, STABLE_FACTORS, "H: 穩定因子 no MA60", ma60_filter=False)
    if r: results.append(r)

    # I: 全因子 baseline（對照組）
    r = deep_validate(df, ALL_FACTORS, "I: 全因子(34) Baseline")
    if r: results.append(r)

    # J: Ensemble — Classification + Regression 平均
    print(f"\n{'─' * 70}")
    print(f"  J: Ensemble（穩定因子 Classification + Regression 等權平均）")
    print(f"{'─' * 70}")
    df_e, rc_e = prepare(df, STABLE_FACTORS, 30, 0.05)
    df_e = df_e[df_e["close"] > df_e["ma60"]].copy()
    windows = generate_windows(df_e)
    ens_ics = []
    ens_monthly = []
    for wid, train_end, test_start, test_end in windows:
        train = df_e[df_e["date"] <= train_end].dropna(subset=["label"])
        test = df_e[(df_e["date"] >= test_start) & (df_e["date"] <= test_end)].dropna(
            subset=["label", "forward_return"])
        if len(train) < 2000 or len(test) < 300:
            continue

        X_tr, y_tr = train[rc_e].values, train["label"].values
        w = time_weights(train["date"], train_end.year)

        # Classification
        clf = HistGradientBoostingClassifier(
            max_iter=200, max_depth=4, max_leaf_nodes=15,
            learning_rate=0.01, min_samples_leaf=100,
            l2_regularization=1.0, random_state=42, verbose=0,
            class_weight="balanced")
        clf.fit(X_tr, y_tr, sample_weight=w)
        p_clf = clf.predict_proba(test[rc_e].values)[:, 1]

        # Regression
        y_reg = train["forward_return"].values.clip(-0.5, 0.5)
        reg = HistGradientBoostingRegressor(
            max_iter=200, max_depth=4, max_leaf_nodes=15,
            learning_rate=0.01, min_samples_leaf=100,
            l2_regularization=1.0, random_state=42, verbose=0)
        reg.fit(X_tr, y_reg, sample_weight=w)
        p_reg = reg.predict(test[rc_e].values)

        # 等權混合（先 normalize 到 0-1）
        p_reg_norm = (p_reg - p_reg.min()) / (p_reg.max() - p_reg.min() + 1e-9)
        ensemble = 0.5 * p_clf + 0.5 * p_reg_norm

        test = test.copy()
        test["_prob"] = ensemble
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
        ens_ics.append(ic)

        cutoff = np.percentile(ensemble, 90)
        top_mask = ensemble >= cutoff
        fwd = test["forward_return"].values
        excess = np.nanmean(fwd[top_mask]) - np.nanmean(fwd)

        test["_top"] = top_mask
        test["_month"] = test["date"].dt.to_period("M")
        for _, grp in test[test["_top"]].groupby("_month"):
            ens_monthly.append(float(np.nanmean(grp["forward_return"].values)))

        mark = "PASS" if ic > 0.05 and ic_t > 2 else "---"
        print(f"  W{wid} {test_start.date()}~{test_end.date()} IC={ic:+.4f}(t={ic_t:+.1f}) excess={excess*100:+.1f}% [{mark}]")

    if ens_ics:
        net_m = np.array(ens_monthly) - COST
        ann_r = np.mean(net_m) * 12
        ann_v = np.std(net_m) * np.sqrt(12)
        sh = ann_r / ann_v if ann_v > 0 else 0
        cum = np.cumprod(1 + net_m)
        peak = np.maximum.accumulate(cum)
        dd = np.min((cum - peak) / peak)
        print(f"\n  彙總：IC avg={np.mean(ens_ics):+.4f} min={np.min(ens_ics):+.4f} IC>0={sum(1 for x in ens_ics if x>0)/len(ens_ics):.0%}")
        print(f"    年化={ann_r*100:+.1f}% Sharpe={sh:.2f} MaxDD={dd*100:.1f}% 勝月={sum(1 for x in net_m if x>0)}/{len(net_m)}")
        results.append({
            "name": "J: Ensemble", "avg_ic": np.mean(ens_ics), "min_ic": np.min(ens_ics),
            "ic_pos_pct": sum(1 for x in ens_ics if x > 0) / len(ens_ics),
            "n_pass": sum(1 for x in ens_ics if x > 0.05), "n_windows": len(ens_ics),
            "ann_return": ann_r, "sharpe": sh, "max_dd": dd,
            "win_month_pct": sum(1 for x in net_m if x > 0) / len(net_m),
        })

    # 最終排名
    print(f"\n{'=' * 70}")
    print(f"  最終策略排名（按 Sharpe 排序）")
    print(f"{'=' * 70}")
    results.sort(key=lambda x: x.get("sharpe", 0), reverse=True)
    print(f"\n  {'策略':>35} {'avg IC':>8} {'min IC':>8} {'IC>0':>5} {'年化':>7} {'Sharpe':>7} {'MaxDD':>7} {'勝月':>5}")
    print("  " + "─" * 95)
    for r in results:
        print(f"  {r['name']:>35} {r['avg_ic']:>+8.4f} {r['min_ic']:>+8.4f} "
              f"{r['ic_pos_pct']:>4.0%} {r['ann_return']*100:>+6.1f}% {r['sharpe']:>7.2f} "
              f"{r['max_dd']*100:>+6.1f}% {r['win_month_pct']:>4.0%}")

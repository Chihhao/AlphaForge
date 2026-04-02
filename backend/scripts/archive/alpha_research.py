"""
Alpha Research — 自主探索腳本

Phase 1: 數據品質 + 因子穩定性 + 多策略實驗
目標：找到跨時期穩定的 alpha 來源
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

COST = 0.006

FACTORS = [
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


def load_all_data() -> pd.DataFrame:
    cols = ", ".join(["stock_id", "date", "close", "ma5", "ma10", "ma20", "ma60",
                      "volume", "change_pct"] + FACTORS)
    sql = text(f"SELECT {cols} FROM stock_features WHERE close > 0 ORDER BY date, stock_id")
    df = pd.read_sql(sql, engine)
    df["date"] = pd.to_datetime(df["date"])
    print(f"[Data] {len(df):,} 筆，{df['date'].min().date()} ~ {df['date'].max().date()}")
    return df


# ═══════════════════════════════════════════════════════════════════════
# Phase 1A: 數據完整度分析
# ═══════════════════════════════════════════════════════════════════════
def check_data_completeness(df: pd.DataFrame):
    print("\n" + "=" * 70)
    print("  Phase 1A: 數據完整度分析")
    print("=" * 70)

    # 每半年的股票數與因子覆蓋率
    df["half"] = df["date"].dt.to_period("Q")
    quarters = sorted(df["half"].unique())

    print(f"\n  {'季度':>8} {'股票數':>8} {'日數':>6} {'每日均':>8}", end="")
    for f in ["foreign_buy_5d", "trust_buy_5d", "revenue_yoy", "roe", "sector_rs"]:
        print(f" {f[:10]:>10}", end="")
    print()
    print("  " + "─" * 80)

    for q in quarters:
        qdf = df[df["half"] == q]
        n_stocks = qdf["stock_id"].nunique()
        n_days = qdf["date"].nunique()
        daily_avg = len(qdf) / n_days if n_days > 0 else 0

        print(f"  {str(q):>8} {n_stocks:>8} {n_days:>6} {daily_avg:>8.0f}", end="")
        for f in ["foreign_buy_5d", "trust_buy_5d", "revenue_yoy", "roe", "sector_rs"]:
            if f in qdf.columns:
                coverage = qdf[f].notna().mean()
                print(f" {coverage:>9.0%}", end="")
            else:
                print(f" {'N/A':>9}", end="")
        print()

    # 結論：找出數據充足的起始日期
    daily_counts = df.groupby("date")["stock_id"].nunique()
    stable_dates = daily_counts[daily_counts >= 500]
    if not stable_dates.empty:
        stable_start = stable_dates.index.min()
        print(f"\n  → 每日 ≥500 檔股票的起始日期：{stable_start.date()}")
    else:
        print(f"\n  → 沒有任何日期有 ≥500 檔股票")

    return stable_dates.index.min() if not stable_dates.empty else df["date"].min()


# ═══════════════════════════════════════════════════════════════════════
# Phase 1B: 逐因子 IC 穩定性
# ═══════════════════════════════════════════════════════════════════════
def factor_ic_stability(df: pd.DataFrame, stable_start, forward_days=30):
    print("\n" + "=" * 70)
    print(f"  Phase 1B: 逐因子 {forward_days}d IC 穩定性（{stable_start.date()} 起）")
    print("=" * 70)

    df = df[df["date"] >= stable_start].copy()
    df = df.sort_values(["stock_id", "date"])
    df["forward_close"] = df.groupby("stock_id")["close"].shift(-forward_days)
    df["forward_return"] = (df["forward_close"] - df["close"]) / df["close"]
    df = df.dropna(subset=["forward_return"])

    # 分位數排名
    for f in FACTORS:
        if f in df.columns:
            df[f"{f}_rank"] = df.groupby("date")[f].rank(pct=True, na_option="keep")

    # 按半年計算每因子 IC
    df["half"] = df["date"].dt.to_period("2Q")  # 每半年
    halves = sorted(df["half"].unique())

    results = {}
    for f in FACTORS:
        rc = f"{f}_rank"
        if rc not in df.columns:
            continue
        half_ics = []
        for h in halves:
            hdf = df[df["half"] == h]
            daily_ics = []
            for _, grp in hdf.groupby("date"):
                if len(grp) < 50:
                    continue
                vals = grp[rc].values
                rets = grp["forward_return"].values
                valid = (~np.isnan(vals)) & (~np.isnan(rets))
                if valid.sum() < 30:
                    continue
                ic, _ = stats.spearmanr(vals[valid], rets[valid])
                if not np.isnan(ic):
                    daily_ics.append(ic)
            if daily_ics:
                half_ics.append(np.mean(daily_ics))
            else:
                half_ics.append(np.nan)
        results[f] = half_ics

    # 印出結果 — 按全期 IC 排序
    print(f"\n  {'因子':>22}", end="")
    for h in halves:
        print(f" {str(h):>10}", end="")
    print(f" {'全期平均':>8} {'穩定性':>6}")
    print("  " + "─" * (22 + 10 * len(halves) + 16))

    factor_scores = []
    for f, ics in results.items():
        valid_ics = [x for x in ics if not np.isnan(x)]
        if not valid_ics:
            continue
        avg = np.mean(valid_ics)
        # 穩定性：IC 為正的半年比例
        pos_ratio = sum(1 for x in valid_ics if x > 0) / len(valid_ics)
        factor_scores.append((f, avg, pos_ratio, ics))

    factor_scores.sort(key=lambda x: x[1], reverse=True)

    for f, avg, pos_ratio, ics in factor_scores:
        print(f"  {f:>22}", end="")
        for ic in ics:
            if np.isnan(ic):
                print(f" {'---':>10}", end="")
            else:
                print(f" {ic:>+10.4f}", end="")
        print(f" {avg:>+8.4f} {pos_ratio:>5.0%}")

    # 找出穩定正 IC 的因子
    stable_factors = [f for f, avg, pos, _ in factor_scores if avg > 0.01 and pos >= 0.6]
    unstable_pos = [f for f, avg, pos, _ in factor_scores if avg > 0.01 and pos < 0.6]
    negative_factors = [f for f, avg, pos, _ in factor_scores if avg < -0.01]

    print(f"\n  穩定正 IC (avg>0.01, >60%正)：{', '.join(stable_factors) if stable_factors else '無'}")
    print(f"  不穩定正 IC：{', '.join(unstable_pos) if unstable_pos else '無'}")
    print(f"  穩定負 IC：{', '.join(negative_factors) if negative_factors else '無'}")

    return stable_factors, factor_scores


# ═══════════════════════════════════════════════════════════════════════
# Phase 2: 多策略回測框架
# ═══════════════════════════════════════════════════════════════════════
def walk_forward_test(df, rank_cols, label_col, forward_days, strategy_name,
                      ma60_filter=False, model_params=None, top_pct=0.10):
    """通用 walk-forward 回測：4 個月非重疊窗口"""
    windows = generate_windows(df, min_train_months=10, test_months=4, gap_months=1)
    if not windows:
        print(f"    [{strategy_name}] 窗口不足，跳過")
        return None

    all_ics = []
    all_excess = []
    all_wr_excess = []
    all_sharpe = []
    window_results = []

    for wid, train_end, test_start, test_end in windows:
        dfw = df.copy()
        if ma60_filter and "ma60" in dfw.columns:
            dfw = dfw[dfw["close"] > dfw["ma60"]].copy()

        train = dfw[dfw["date"] <= train_end].dropna(subset=[label_col])
        test = dfw[(dfw["date"] >= test_start) & (dfw["date"] <= test_end)].dropna(
            subset=[label_col, "forward_return"])

        if len(train) < 2000 or len(test) < 500:
            continue

        X_train = train[rank_cols].values
        y_train = train[label_col].values
        # 時間衰減
        base_year = train_end.year
        delta = base_year - train["date"].dt.year
        w = np.clip(1.0 - 0.2 * delta, 0.2, 1.0).values

        params = dict(max_iter=200, max_depth=4, max_leaf_nodes=15,
                      learning_rate=0.01, min_samples_leaf=100,
                      l2_regularization=1.0, random_state=42, verbose=0,
                      class_weight="balanced")
        if model_params:
            params.update(model_params)

        model = HistGradientBoostingClassifier(**params)
        model.fit(X_train, y_train, sample_weight=w)

        X_test = test[rank_cols].values
        prob = model.predict_proba(X_test)[:, 1]

        # IC
        test = test.copy()
        test["_prob"] = prob
        daily_ics = []
        for _, grp in test.groupby("date"):
            if len(grp) < 50:
                continue
            p = grp["_prob"].values
            r = grp["forward_return"].values
            valid = ~np.isnan(r)
            if valid.sum() < 30:
                continue
            ic, _ = stats.spearmanr(p[valid], r[valid])
            if not np.isnan(ic):
                daily_ics.append(ic)
        ic = np.mean(daily_ics) if daily_ics else 0
        ic_t = ic / (np.std(daily_ics) / np.sqrt(len(daily_ics))) if daily_ics and np.std(daily_ics) > 0 else 0

        # Top picks
        cutoff = np.percentile(prob, (1 - top_pct) * 100)
        top_mask = prob >= cutoff
        fwd = test["forward_return"].values
        top_ret = fwd[top_mask]
        mkt_ret = np.nanmean(fwd)
        excess = np.nanmean(top_ret) - mkt_ret

        threshold = 0.05 if forward_days >= 30 else 0.03
        wr = float(np.nanmean(top_ret > threshold))
        mkt_wr = float(np.nanmean(fwd > threshold))

        # Monthly Sharpe
        test["_top"] = top_mask
        test["_month"] = test["date"].dt.to_period("M")
        monthly = [float(np.nanmean(g["forward_return"].values)) - COST
                   for _, g in test[test["_top"]].groupby("_month")]
        sharpe = (np.mean(monthly) / np.std(monthly) * np.sqrt(12)
                  if len(monthly) > 2 and np.std(monthly) > 0 else 0)

        all_ics.append(ic)
        all_excess.append(excess)
        all_wr_excess.append(wr - mkt_wr)
        all_sharpe.append(sharpe)
        window_results.append({
            "wid": wid, "test_start": test_start.date(), "test_end": test_end.date(),
            "ic": ic, "ic_t": ic_t, "excess": excess, "wr_excess": wr - mkt_wr,
            "sharpe": sharpe, "n_test": len(test),
        })

    if not window_results:
        return None

    avg_ic = np.mean(all_ics)
    avg_excess = np.mean(all_excess)
    avg_sharpe = np.mean(all_sharpe)
    ic_positive_pct = sum(1 for x in all_ics if x > 0) / len(all_ics)
    n_pass = sum(1 for x in all_ics if x > 0.05)

    return {
        "name": strategy_name,
        "avg_ic": avg_ic,
        "min_ic": np.min(all_ics),
        "max_ic": np.max(all_ics),
        "ic_positive_pct": ic_positive_pct,
        "n_pass": n_pass,
        "n_windows": len(window_results),
        "avg_excess": avg_excess,
        "avg_wr_excess": np.mean(all_wr_excess),
        "avg_sharpe": avg_sharpe,
        "windows": window_results,
    }


def generate_windows(df, min_train_months=10, test_months=4, gap_months=1):
    min_date = df["date"].min()
    max_date = df["date"].max()
    first_test = min_date + pd.DateOffset(months=min_train_months + gap_months)
    windows = []
    test_start = first_test
    wid = 1
    while test_start + pd.DateOffset(months=2) <= max_date:
        test_end = min(test_start + pd.DateOffset(months=test_months), max_date)
        train_end = test_start - pd.DateOffset(months=gap_months)
        windows.append((wid, pd.Timestamp(train_end), pd.Timestamp(test_start), pd.Timestamp(test_end)))
        test_start += pd.DateOffset(months=test_months)
        wid += 1
    return windows


def prepare_data(df, forward_days, threshold):
    """準備 forward return、label、rank columns"""
    df = df.sort_values(["stock_id", "date"]).copy()
    df["forward_close"] = df.groupby("stock_id")["close"].shift(-forward_days)
    df["forward_return"] = (df["forward_close"] - df["close"]) / df["close"]
    df["label"] = (df["forward_return"] > threshold).astype(float)

    rank_cols = []
    for f in FACTORS:
        if f in df.columns:
            rc = f"{f}_rank"
            df[rc] = df.groupby("date")[f].rank(pct=True, na_option="keep")
            rank_cols.append(rc)
    return df, rank_cols


def add_derived_features(df):
    """加入衍生因子"""
    g = df.groupby("stock_id")

    # 動量
    df["mom_5d"] = g["close"].pct_change(5)
    df["mom_10d"] = g["close"].pct_change(10)
    df["mom_20d"] = g["close"].pct_change(20)

    # 法人合力
    df["inst_flow_5d"] = df["foreign_buy_5d"].fillna(0) + df["trust_buy_5d"].fillna(0)
    df["inst_flow_10d"] = df["foreign_buy_10d"].fillna(0) + df["trust_buy_10d"].fillna(0)
    df["inst_flow_20d"] = df["foreign_buy_20d"].fillna(0) + df["trust_buy_20d"].fillna(0)

    # 三大法人共識度
    df["chip_consensus"] = (
        (df["foreign_buy_5d"].fillna(0) > 0).astype(float) +
        (df["trust_buy_5d"].fillna(0) > 0).astype(float) +
        (df["dealer_buy_5d"].fillna(0) > 0).astype(float)
    )
    df["chip_consensus_10d"] = (
        (df["foreign_buy_10d"].fillna(0) > 0).astype(float) +
        (df["trust_buy_10d"].fillna(0) > 0).astype(float) +
        (df["dealer_buy_10d"].fillna(0) > 0).astype(float)
    )

    # MA60 距離
    df["ma60_dist"] = (df["close"] - df["ma60"]) / df["ma60"].clip(lower=1)

    # 量能相關
    df["vol_spike"] = df["vol_ratio"].clip(upper=5)

    # RSI 超賣反轉（低 RSI + 法人買）
    df["rsi_oversold_chip"] = ((df["rsi14"] < 30).astype(float) *
                                (df["inst_flow_5d"].fillna(0) > 0).astype(float))

    # 價格位置
    df["price_ma_score"] = (
        (df["close"] > df["ma5"]).astype(float) +
        (df["close"] > df["ma10"]).astype(float) +
        (df["close"] > df["ma20"]).astype(float) +
        (df["close"] > df["ma60"]).astype(float)
    ) / 4.0

    return df


DERIVED_FACTORS = [
    "mom_5d", "mom_10d", "mom_20d",
    "inst_flow_5d", "inst_flow_10d", "inst_flow_20d",
    "chip_consensus", "chip_consensus_10d",
    "ma60_dist", "vol_spike", "rsi_oversold_chip", "price_ma_score",
]


# ═══════════════════════════════════════════════════════════════════════
# Phase 2: 多策略實驗
# ═══════════════════════════════════════════════════════════════════════
def run_experiments(df_raw, stable_start, stable_factors):
    print("\n" + "=" * 70)
    print("  Phase 2: 多策略 Walk-Forward 實驗")
    print("=" * 70)

    # 只使用數據充足的時期
    df = df_raw[df_raw["date"] >= stable_start].copy()
    df = add_derived_features(df)
    print(f"  使用數據：{stable_start.date()} ~ {df['date'].max().date()}，{len(df):,} 筆")

    all_factors = FACTORS + DERIVED_FACTORS
    results = []

    # ── 實驗 1: Baseline（全因子 + MA60）───────────────────────────────
    print("\n  [實驗 1] Baseline: 全因子 + MA60 過濾")
    df1, rc1 = prepare_with_extra(df, 30, 0.05, FACTORS)
    r1 = walk_forward_test(df1, rc1, "label", 30, "Baseline (全因子+MA60)", ma60_filter=True)
    if r1: results.append(r1)

    # ── 實驗 2: 全因子，不加 MA60 過濾 ──────────────────────────────
    print("\n  [實驗 2] 全因子，無 MA60 過濾")
    r2 = walk_forward_test(df1, rc1, "label", 30, "全因子 no MA60", ma60_filter=False)
    if r2: results.append(r2)

    # ── 實驗 3: 穩定因子子集 + MA60 ──────────────────────────────────
    if stable_factors:
        print(f"\n  [實驗 3] 穩定因子子集: {stable_factors}")
        df3, rc3 = prepare_with_extra(df, 30, 0.05, stable_factors)
        r3 = walk_forward_test(df3, rc3, "label", 30, "穩定因子+MA60", ma60_filter=True)
        if r3: results.append(r3)

    # ── 實驗 4: 全因子+衍生 + MA60 ──────────────────────────────────
    print("\n  [實驗 4] 全因子 + 衍生特徵 + MA60")
    df4, rc4 = prepare_with_extra(df, 30, 0.05, all_factors)
    r4 = walk_forward_test(df4, rc4, "label", 30, "全+衍生+MA60", ma60_filter=True)
    if r4: results.append(r4)

    # ── 實驗 5: 籌碼面因子 only ─────────────────────────────────────
    chip_factors = [
        "foreign_net_buy", "foreign_buy_5d", "foreign_buy_10d", "foreign_buy_20d",
        "trust_net_buy", "trust_buy_5d", "trust_buy_10d", "trust_buy_20d",
        "dealer_net_buy", "dealer_buy_5d", "dealer_buy_10d", "dealer_buy_20d",
        "margin_chg_5d", "foreign_hold_pct", "foreign_hold_chg_5d",
        "inst_flow_5d", "inst_flow_10d", "inst_flow_20d",
        "chip_consensus", "chip_consensus_10d",
    ]
    print("\n  [實驗 5] 純籌碼面因子")
    df5, rc5 = prepare_with_extra(df, 30, 0.05, chip_factors)
    r5 = walk_forward_test(df5, rc5, "label", 30, "純籌碼面", ma60_filter=True)
    if r5: results.append(r5)

    # ── 實驗 6: 技術面 + 動量 ───────────────────────────────────────
    tech_factors = [
        "rsi14", "rsi2", "k", "d", "macd_dif", "macd_osc",
        "bias5", "bias10", "bias20", "bb_pctb", "vol_ratio",
        "price_vs_high20", "ma_trend",
        "mom_5d", "mom_10d", "mom_20d", "ma60_dist", "price_ma_score",
    ]
    print("\n  [實驗 6] 技術面 + 動量")
    df6, rc6 = prepare_with_extra(df, 30, 0.05, tech_factors)
    r6 = walk_forward_test(df6, rc6, "label", 30, "技術+動量", ma60_filter=True)
    if r6: results.append(r6)

    # ── 實驗 7: 不同 threshold ──────────────────────────────────────
    print("\n  [實驗 7] 全因子+MA60，threshold=3%（更低門檻）")
    df7, rc7 = prepare_with_extra(df, 30, 0.03, all_factors)
    r7 = walk_forward_test(df7, rc7, "label", 30, "全+衍生 thr=3%", ma60_filter=True)
    if r7: results.append(r7)

    # ── 實驗 8: Top 20% 而非 Top 10% ──────────────────────────────
    print("\n  [實驗 8] 全因子+MA60，Top 20%")
    r8 = walk_forward_test(df4, rc4, "label", 30, "全+衍生 Top20%", ma60_filter=True, top_pct=0.20)
    if r8: results.append(r8)

    # ── 實驗 9: 更強正則化 ─────────────────────────────────────────
    print("\n  [實驗 9] 強正則化（depth=3, leaf=8, l2=3.0）")
    r9 = walk_forward_test(df4, rc4, "label", 30, "強正則化",
                           ma60_filter=True,
                           model_params=dict(max_depth=3, max_leaf_nodes=8, l2_regularization=3.0))
    if r9: results.append(r9)

    # ── 實驗 10: 20d 持有期 ──────────────────────────────────────
    print("\n  [實驗 10] 20d 持有期 + 全因子+衍生 + MA60")
    df10, rc10 = prepare_with_extra(df, 20, 0.04, all_factors)
    r10 = walk_forward_test(df10, rc10, "label", 20, "20d 全+衍生+MA60", ma60_filter=True)
    if r10: results.append(r10)

    # ── 實驗 11: 不用 class_weight 平衡 ─────────────────────────────
    print("\n  [實驗 11] 全因子+衍生+MA60，無 class_weight")
    r11 = walk_forward_test(df4, rc4, "label", 30, "無 class_weight",
                            ma60_filter=True,
                            model_params=dict(class_weight=None))
    if r11: results.append(r11)

    # ── 實驗 12: Regression（預測報酬率而非分類）────────────────────
    print("\n  [實驗 12] Regression（預測報酬率）+ MA60")
    r12 = run_regression_experiment(df, all_factors, stable_start)
    if r12: results.append(r12)

    # ── 排名 ───────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("  策略排名（按 IC 穩定性 × 平均 IC 排序）")
    print("=" * 70)
    results.sort(key=lambda x: x["avg_ic"] * x["ic_positive_pct"], reverse=True)
    print(f"\n  {'策略':>28} {'avg IC':>8} {'min IC':>8} {'IC>0%':>6} {'pass':>5} "
          f"{'excess':>8} {'WR ex':>7} {'Sharpe':>7}")
    print("  " + "─" * 90)
    for r in results:
        print(f"  {r['name']:>28} {r['avg_ic']:>+8.4f} {r['min_ic']:>+8.4f} "
              f"{r['ic_positive_pct']:>5.0%} {r['n_pass']}/{r['n_windows']:>2} "
              f"{r['avg_excess']*100:>+7.2f}% {r['avg_wr_excess']*100:>+6.1f}% "
              f"{r['avg_sharpe']:>7.2f}")

    return results


def prepare_with_extra(df, forward_days, threshold, factor_list):
    """準備指定因子的 forward return + rank columns"""
    df = df.sort_values(["stock_id", "date"]).copy()
    df["forward_close"] = df.groupby("stock_id")["close"].shift(-forward_days)
    df["forward_return"] = (df["forward_close"] - df["close"]) / df["close"]
    df["label"] = (df["forward_return"] > threshold).astype(float)

    rank_cols = []
    for f in factor_list:
        if f in df.columns:
            rc = f"{f}_rank"
            df[rc] = df.groupby("date")[f].rank(pct=True, na_option="keep")
            rank_cols.append(rc)
    return df, rank_cols


def run_regression_experiment(df, factor_list, stable_start):
    """用 regression 預測報酬率，然後用預測值排序"""
    from sklearn.ensemble import HistGradientBoostingRegressor

    df = df[df["date"] >= stable_start].copy()
    df = add_derived_features(df)
    df = df.sort_values(["stock_id", "date"])
    df["forward_close"] = df.groupby("stock_id")["close"].shift(-30)
    df["forward_return"] = (df["forward_close"] - df["close"]) / df["close"]

    # MA60 filter
    df = df[df["close"] > df["ma60"]].copy()

    rank_cols = []
    for f in factor_list:
        if f in df.columns:
            rc = f"{f}_rank"
            df[rc] = df.groupby("date")[f].rank(pct=True, na_option="keep")
            rank_cols.append(rc)

    windows = generate_windows(df, min_train_months=10, test_months=4, gap_months=1)
    all_ics = []
    all_excess = []
    window_results = []

    for wid, train_end, test_start, test_end in windows:
        train = df[df["date"] <= train_end].dropna(subset=["forward_return"])
        test = df[(df["date"] >= test_start) & (df["date"] <= test_end)].dropna(
            subset=["forward_return"])

        if len(train) < 2000 or len(test) < 500:
            continue

        X_train = train[rank_cols].values
        y_train = train["forward_return"].values.clip(-0.5, 0.5)  # clip 極端值
        base_year = train_end.year
        delta = base_year - train["date"].dt.year
        w = np.clip(1.0 - 0.2 * delta, 0.2, 1.0).values

        model = HistGradientBoostingRegressor(
            max_iter=200, max_depth=4, max_leaf_nodes=15,
            learning_rate=0.01, min_samples_leaf=100,
            l2_regularization=1.0, random_state=42, verbose=0,
        )
        model.fit(X_train, y_train, sample_weight=w)

        pred = model.predict(test[rank_cols].values)

        # IC
        test = test.copy()
        test["_pred"] = pred
        daily_ics = []
        for _, grp in test.groupby("date"):
            if len(grp) < 50:
                continue
            p = grp["_pred"].values
            r = grp["forward_return"].values
            valid = ~np.isnan(r)
            if valid.sum() < 30:
                continue
            ic, _ = stats.spearmanr(p[valid], r[valid])
            if not np.isnan(ic):
                daily_ics.append(ic)
        ic = np.mean(daily_ics) if daily_ics else 0
        ic_t = ic / (np.std(daily_ics) / np.sqrt(len(daily_ics))) if daily_ics and np.std(daily_ics) > 0 else 0

        # Excess
        top_pct = 0.10
        cutoff = np.percentile(pred, (1 - top_pct) * 100)
        top_mask = pred >= cutoff
        fwd = test["forward_return"].values
        excess = np.nanmean(fwd[top_mask]) - np.nanmean(fwd)

        wr = float(np.nanmean(fwd[top_mask] > 0.05))
        mkt_wr = float(np.nanmean(fwd > 0.05))

        all_ics.append(ic)
        all_excess.append(excess)
        window_results.append({
            "wid": wid, "test_start": test_start.date(), "test_end": test_end.date(),
            "ic": ic, "ic_t": ic_t, "excess": excess, "wr_excess": wr - mkt_wr,
            "sharpe": 0, "n_test": len(test),
        })

    if not window_results:
        return None

    return {
        "name": "Regression 30d",
        "avg_ic": np.mean(all_ics),
        "min_ic": np.min(all_ics),
        "max_ic": np.max(all_ics),
        "ic_positive_pct": sum(1 for x in all_ics if x > 0) / len(all_ics),
        "n_pass": sum(1 for x in all_ics if x > 0.05),
        "n_windows": len(window_results),
        "avg_excess": np.mean(all_excess),
        "avg_wr_excess": np.mean([w["wr_excess"] for w in window_results]),
        "avg_sharpe": 0,
        "windows": window_results,
    }


# ═══════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    df = load_all_data()

    # Phase 1A
    stable_start = check_data_completeness(df)

    # Phase 1B
    stable_factors, factor_scores = factor_ic_stability(df, stable_start)

    # Phase 2
    results = run_experiments(df, stable_start, stable_factors)

    # 最佳策略的逐窗口明細
    if results:
        best = results[0]
        print(f"\n{'=' * 70}")
        print(f"  最佳策略「{best['name']}」逐窗口明細")
        print(f"{'=' * 70}")
        for w in best["windows"]:
            mark = "PASS" if w["ic"] > 0.05 and w["ic_t"] > 2 else "FAIL"
            print(f"  W{w['wid']:>2} {w['test_start']} ~ {w['test_end']}  "
                  f"IC={w['ic']:+.4f} t={w['ic_t']:+.2f} "
                  f"excess={w['excess']*100:+.2f}%  [{mark}]")

"""
Alpha 診斷 V2 — 專注於可交易性分析

核心問題：
1. 30d baseline IC=0.10 的 alpha 在扣除成本後能獲利多少？
2. 10d 的 excess WR +13% 是否能轉化為正報酬？
3. 針對 10d 嘗試新策略：均值回歸 + 籌碼面
4. 30d + MA60 基礎上，能否疊加更多 alpha？
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

PG_URL = os.getenv(
    "PG_URL",
    "postgresql://alphaforge:alphaforge_secret@10.0.4.3:5433/alphaforge",
)
engine = create_engine(PG_URL)

LOOKBACK_DAYS = 730
TEST_MONTHS = 6
GAP_MONTHS = 1
COST = 0.006  # 來回交易成本 0.6%


def load_data() -> pd.DataFrame:
    cutoff = date.today() - timedelta(days=LOOKBACK_DAYS)
    print(f"[Data] 載入 stock_features (>= {cutoff}) ...")
    sql = text("""
        SELECT sf.stock_id, sf.date, sf.close, sf.ma5, sf.ma10, sf.ma20, sf.ma60,
               sf.change_pct,
               sf.rsi14, sf.rsi2, sf.k, sf.d,
               sf.macd_dif, sf.macd_osc,
               sf.bias5, sf.bias10, sf.bias20,
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
    print(f"[Data] {len(df):,} 筆，{df['stock_id'].nunique()} 檔，{df['date'].nunique()} 交易日")
    return df


def add_derived_features(df: pd.DataFrame) -> pd.DataFrame:
    """新增衍生特徵"""
    g = df.groupby("stock_id")
    # 動量
    df["mom_5d"] = g["close"].pct_change(5)
    df["mom_20d"] = g["close"].pct_change(20)
    # 波動率調整動量
    df["vol_adj_mom_5d"] = df["mom_5d"] / df["atr_pct"].clip(lower=0.01)
    # 外資+投信合力
    df["inst_flow_5d"] = df["foreign_buy_5d"].fillna(0) + df["trust_buy_5d"].fillna(0)
    df["inst_flow_10d"] = df["foreign_buy_10d"].fillna(0) + df["trust_buy_10d"].fillna(0)
    df["inst_flow_20d"] = df["foreign_buy_20d"].fillna(0) + df["trust_buy_20d"].fillna(0)
    # 籌碼一致性
    df["chip_consensus"] = (
        (df["foreign_buy_5d"].fillna(0) > 0).astype(float) +
        (df["trust_buy_5d"].fillna(0) > 0).astype(float) +
        (df["dealer_buy_5d"].fillna(0) > 0).astype(float)
    )
    # RSI 背離代理
    df["rsi_divergence"] = df["rsi14"] - df["price_vs_high20"] * 100
    # 短期超賣反彈指標
    df["oversold_bounce"] = ((df["rsi2"] < 20) & (df["foreign_net_buy"].fillna(0) > 0)).astype(float)
    # MA60 距離 (%) — 趨勢強度
    df["ma60_dist"] = (df["close"] - df["ma60"]) / df["ma60"].clip(lower=1)
    # 成交量突增
    df["vol_spike"] = df["vol_ratio"].clip(upper=5)
    return df


def compute_fwd(df: pd.DataFrame, days: int) -> pd.DataFrame:
    df = df.copy()
    df["forward_close"] = df.groupby("stock_id")["close"].shift(-days)
    df["forward_return"] = (df["forward_close"] - df["close"]) / df["close"]
    return df


def quantile_rank(df: pd.DataFrame, cols: list[str]) -> tuple:
    df = df.copy()
    rank_cols = []
    for c in cols:
        rc = f"rank_{c}"
        df[rc] = df.groupby("date")[c].rank(pct=True, method="average") * 100
        rank_cols.append(rc)
    return df, rank_cols


def time_weights(dates: pd.Series) -> np.ndarray:
    max_date = dates.max()
    days_ago = (max_date - dates).dt.days
    w = np.exp(-0.001 * days_ago)
    return np.clip(w, 0.2, 1.0)


def train_eval(train_df, test_df, rank_cols, label_col="label", params=None):
    X_train = train_df[rank_cols].values
    y_train = train_df[label_col].values
    w_train = time_weights(train_df["date"])
    X_test = test_df[rank_cols].values

    defaults = dict(
        max_iter=200, max_depth=4, max_leaf_nodes=15,
        learning_rate=0.01, min_samples_leaf=100,
        l2_regularization=1.0, random_state=42, verbose=0,
        class_weight="balanced",
    )
    if params:
        defaults.update(params)
    model = HistGradientBoostingClassifier(**defaults)
    model.fit(X_train, y_train, sample_weight=w_train)
    prob = model.predict_proba(X_test)[:, 1]
    return prob, model


def evaluate_profitability(
    test_df: pd.DataFrame, prob: np.ndarray, dim: str, threshold: float,
    top_pct: float = 0.20, label: str = "",
):
    """評估 Top-Quintile 的可交易性"""
    test = test_df.copy()
    test["_prob"] = prob
    fwd_ret = test["forward_return"].values

    cutoff = np.percentile(prob, (1 - top_pct) * 100)
    top_mask = prob >= cutoff
    top_ret = fwd_ret[top_mask]
    n_top = top_mask.sum()

    # 基本統計
    win_rate = np.nanmean(top_ret > threshold)
    mkt_win = np.nanmean(fwd_ret > threshold)
    avg_ret = np.nanmean(top_ret)
    avg_ret_net = avg_ret - COST
    mkt_avg = np.nanmean(fwd_ret)

    # 逐月分析（穩定度）
    test["_top"] = top_mask
    test["_month"] = test["date"].dt.to_period("M")
    monthly = []
    for month, grp in test[test["_top"]].groupby("_month"):
        m_ret = grp["forward_return"].values
        monthly.append({
            "month": str(month),
            "n": len(m_ret),
            "avg_ret": np.nanmean(m_ret) * 100,
            "avg_ret_net": (np.nanmean(m_ret) - COST) * 100,
            "win_rate": np.nanmean(m_ret > threshold),
        })
    monthly_df = pd.DataFrame(monthly)

    # IC
    daily_ics = []
    for d, grp in test.groupby("date"):
        if len(grp) < 30:
            continue
        p = grp["_prob"].values
        r = grp["forward_return"].values
        if np.std(p) < 1e-9 or np.nanstd(r) < 1e-9:
            continue
        valid = ~np.isnan(r)
        if valid.sum() < 20:
            continue
        ic, _ = stats.spearmanr(p[valid], r[valid])
        if not np.isnan(ic):
            daily_ics.append(ic)
    ic_mean = np.mean(daily_ics) if daily_ics else 0.0
    ic_t = ic_mean / (np.std(daily_ics) / np.sqrt(len(daily_ics))) if daily_ics and np.std(daily_ics) > 0 else 0.0

    # 輸出
    print(f"\n  [{label}] {dim}")
    print(f"    IC = {ic_mean:+.4f} (t={ic_t:+.2f}, n_days={len(daily_ics)})")
    print(f"    Top {top_pct:.0%}: n={n_top}, WR={win_rate:.1%} vs mkt {mkt_win:.1%} (excess={win_rate-mkt_win:+.1%})")
    print(f"    Avg Return: top={avg_ret*100:+.2f}%  net={avg_ret_net*100:+.2f}%  mkt={mkt_avg*100:+.2f}%  excess={((avg_ret-mkt_avg)*100):+.2f}%")

    if len(monthly_df) > 0:
        pos_months = (monthly_df["avg_ret_net"] > 0).sum()
        total_months = len(monthly_df)
        print(f"    月度獲利率: {pos_months}/{total_months} ({pos_months/total_months:.0%})")
        print(f"    月度報酬分布:")
        for _, row in monthly_df.iterrows():
            flag = "+" if row["avg_ret_net"] > 0 else " "
            print(f"      {row['month']}  n={row['n']:4d}  ret={row['avg_ret']:+5.2f}%  "
                  f"net={row['avg_ret_net']:+5.2f}%  WR={row['win_rate']:.0%} {flag}")

    return {
        "ic_mean": ic_mean, "ic_t": ic_t,
        "win_rate": win_rate, "mkt_win_rate": mkt_win,
        "avg_ret": avg_ret, "avg_ret_net": avg_ret_net,
        "mkt_avg_ret": mkt_avg,
        "monthly_win_pct": (monthly_df["avg_ret_net"] > 0).mean() if len(monthly_df) > 0 else 0,
    }


def run_analysis(df_raw: pd.DataFrame):
    df = add_derived_features(df_raw)
    max_date = df["date"].max()
    test_start = max_date - pd.DateOffset(months=TEST_MONTHS)
    train_end = max_date - pd.DateOffset(months=TEST_MONTHS + GAP_MONTHS)

    BASE_FACTORS = [
        "rsi14", "rsi2", "k", "d",
        "macd_dif", "macd_osc",
        "bias5", "bias10", "bias20",
        "bb_pctb", "vol_ratio",
        "yield_rate", "roe", "pb_ratio", "revenue_yoy",
        "foreign_net_buy", "foreign_buy_5d", "trust_net_buy", "trust_buy_5d",
        "margin_chg_5d", "dealer_net_buy", "dealer_buy_5d",
        "price_vs_high20", "ma_trend", "sector_rs",
        "foreign_hold_pct", "foreign_hold_chg_5d", "etf_net_flow_5d",
        "foreign_buy_10d", "foreign_buy_20d",
        "trust_buy_10d", "trust_buy_20d",
        "dealer_buy_10d", "dealer_buy_20d",
    ]

    NEW_FACTORS = BASE_FACTORS + [
        "mom_5d", "mom_20d", "vol_adj_mom_5d",
        "inst_flow_5d", "inst_flow_10d", "inst_flow_20d",
        "chip_consensus", "rsi_divergence", "ma60_dist", "vol_spike",
    ]

    print("=" * 70)
    print("  實驗 A: 30d Baseline（已知最佳） — 獲利分析")
    print("=" * 70)

    df_30 = compute_fwd(df, 30)
    df_30["label"] = (df_30["forward_return"] > 0.05).astype(float)
    df_30_up = df_30[df_30["close"] > df_30["ma60"]].copy()
    df_30_up, rcols = quantile_rank(df_30_up, BASE_FACTORS)
    train = df_30_up[df_30_up["date"] <= train_end].dropna(subset=["label"])
    test = df_30_up[df_30_up["date"] >= test_start].dropna(subset=["label", "forward_return"])
    prob, _ = train_eval(train, test, rcols)
    evaluate_profitability(test, prob, "30d", threshold=0.05, label="30d Baseline + MA60")

    print("\n" + "=" * 70)
    print("  實驗 B: 30d + 新特徵（MA60 保留） — 能否提升 30d?")
    print("=" * 70)

    available_new = [f for f in NEW_FACTORS if f in df_30_up.columns]
    df_30b = df_30[df_30["close"] > df_30["ma60"]].copy()
    df_30b, rcols_b = quantile_rank(df_30b, available_new)
    train_b = df_30b[df_30b["date"] <= train_end].dropna(subset=["label"])
    test_b = df_30b[df_30b["date"] >= test_start].dropna(subset=["label", "forward_return"])
    prob_b, _ = train_eval(train_b, test_b, rcols_b)
    evaluate_profitability(test_b, prob_b, "30d", threshold=0.05, label="30d + NewFeats + MA60")

    print("\n" + "=" * 70)
    print("  實驗 C: 10d Baseline — 獲利可行性")
    print("=" * 70)

    df_10 = compute_fwd(df, 10)
    df_10["label"] = (df_10["forward_return"] > 0.03).astype(float)

    # C1: 有 MA60 filter
    df_10_up = df_10[df_10["close"] > df_10["ma60"]].copy()
    df_10_up, rcols_10 = quantile_rank(df_10_up, BASE_FACTORS)
    train_10 = df_10_up[df_10_up["date"] <= train_end].dropna(subset=["label"])
    test_10 = df_10_up[df_10_up["date"] >= test_start].dropna(subset=["label", "forward_return"])
    prob_10, _ = train_eval(train_10, test_10, rcols_10)
    evaluate_profitability(test_10, prob_10, "10d", threshold=0.03, label="10d Baseline (MA60)")

    # C2: 無 MA60 filter
    df_10_all = df_10.copy()
    df_10_all, rcols_10a = quantile_rank(df_10_all, BASE_FACTORS)
    train_10a = df_10_all[df_10_all["date"] <= train_end].dropna(subset=["label"])
    test_10a = df_10_all[df_10_all["date"] >= test_start].dropna(subset=["label", "forward_return"])
    prob_10a, _ = train_eval(train_10a, test_10a, rcols_10a)
    evaluate_profitability(test_10a, prob_10a, "10d", threshold=0.03, label="10d No MA60")

    print("\n" + "=" * 70)
    print("  實驗 D: 10d 均值回歸策略（短期超賣 + 籌碼買超 → 反彈）")
    print("=" * 70)

    # 均值回歸特徵：超賣 + 外資投信加碼 + 波動率
    MR_FACTORS = [
        "rsi2", "rsi14", "bb_pctb", "bias5", "bias10",
        "price_vs_high20", "vol_ratio", "vol_spike",
        "foreign_net_buy", "foreign_buy_5d", "inst_flow_5d",
        "trust_net_buy", "trust_buy_5d",
        "chip_consensus", "rsi_divergence",
        "oversold_bounce", "vol_adj_mom_5d",
        "atr_pct", "ma60_dist",
    ]
    available_mr = [f for f in MR_FACTORS if f in df_10.columns]
    df_10_mr = df_10.copy()
    df_10_mr, rcols_mr = quantile_rank(df_10_mr, available_mr)
    train_mr = df_10_mr[df_10_mr["date"] <= train_end].dropna(subset=["label"])
    test_mr = df_10_mr[df_10_mr["date"] >= test_start].dropna(subset=["label", "forward_return"])
    prob_mr, _ = train_eval(train_mr, test_mr, rcols_mr)
    evaluate_profitability(test_mr, prob_mr, "10d", threshold=0.03, label="10d MeanReversion")

    # D2: 均值回歸 + 門檻 5%
    df_10_mr5 = df_10.copy()
    df_10_mr5["label"] = (df_10_mr5["forward_return"] > 0.05).astype(float)
    df_10_mr5, rcols_mr5 = quantile_rank(df_10_mr5, available_mr)
    train_mr5 = df_10_mr5[df_10_mr5["date"] <= train_end].dropna(subset=["label"])
    test_mr5 = df_10_mr5[df_10_mr5["date"] >= test_start].dropna(subset=["label", "forward_return"])
    prob_mr5, _ = train_eval(train_mr5, test_mr5, rcols_mr5)
    evaluate_profitability(test_mr5, prob_mr5, "10d", threshold=0.05, label="10d MR (thr=5%)")

    print("\n" + "=" * 70)
    print("  實驗 E: 10d + 新特徵 + 調參")
    print("=" * 70)

    available_all = [f for f in NEW_FACTORS if f in df_10.columns]
    df_10e = df_10.copy()
    df_10e, rcols_e = quantile_rank(df_10e, available_all)
    train_e = df_10e[df_10e["date"] <= train_end].dropna(subset=["label"])
    test_e = df_10e[df_10e["date"] >= test_start].dropna(subset=["label", "forward_return"])
    prob_e, _ = train_eval(train_e, test_e, rcols_e,
                           params=dict(max_iter=300, max_depth=5, max_leaf_nodes=20,
                                       min_samples_leaf=80, l2_regularization=2.0))
    evaluate_profitability(test_e, prob_e, "10d", threshold=0.03, label="10d NewFeats+TunedHP")

    print("\n" + "=" * 70)
    print("  實驗 F: 5d — 是否有任何可行策略？")
    print("=" * 70)

    df_5 = compute_fwd(df, 5)
    df_5["label"] = (df_5["forward_return"] > 0.02).astype(float)  # 用 2% 門檻
    df_5_all = df_5.copy()
    available_mr5d = [f for f in MR_FACTORS if f in df_5_all.columns]
    df_5_all, rcols_5 = quantile_rank(df_5_all, available_mr5d)
    train_5 = df_5_all[df_5_all["date"] <= train_end].dropna(subset=["label"])
    test_5 = df_5_all[df_5_all["date"] >= test_start].dropna(subset=["label", "forward_return"])
    prob_5, _ = train_eval(train_5, test_5, rcols_5,
                           params=dict(max_iter=150, max_depth=3, max_leaf_nodes=8,
                                       min_samples_leaf=200, l2_regularization=3.0))
    evaluate_profitability(test_5, prob_5, "5d", threshold=0.02, label="5d MR + LowThreshold")

    # 5d 2% 門檻 + 超賣條件
    df_5f2 = df_5.copy()
    # 只在 RSI2 < 30 時做多（超賣反彈）
    df_5f2 = df_5f2[df_5f2["rsi2"] < 30].copy()
    if len(df_5f2) > 500:
        df_5f2, rcols_5f2 = quantile_rank(df_5f2, available_mr5d)
        train_5f2 = df_5f2[df_5f2["date"] <= train_end].dropna(subset=["label"])
        test_5f2 = df_5f2[df_5f2["date"] >= test_start].dropna(subset=["label", "forward_return"])
        if len(train_5f2) > 200 and len(test_5f2) > 50:
            prob_5f2, _ = train_eval(train_5f2, test_5f2, rcols_5f2,
                                     params=dict(max_iter=100, max_depth=3, min_samples_leaf=50))
            evaluate_profitability(test_5f2, prob_5f2, "5d", threshold=0.02,
                                   label="5d RSI2<30 Oversold")
        else:
            print("  [5d RSI2<30] 資料不足")
    else:
        print("  [5d RSI2<30] 資料不足")


if __name__ == "__main__":
    df = load_data()
    run_analysis(df)

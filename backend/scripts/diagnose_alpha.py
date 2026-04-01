"""
Alpha 診斷腳本 — 本地跑 LightGBM 實驗，找出各維度 IC 弱的根因
連接 NAS PostgreSQL，做 6 組對照實驗

實驗矩陣：
  1. Baseline — 復現目前上線的訓練流程
  2. 移除 MA60 趨勢過濾（10d/30d）
  3. 維度專屬特徵子集
  4. 不同報酬門檻
  5. 超參數調整（更深樹 / 更多正則化）
  6. 新衍生特徵（動量、波動率交互）
"""
from __future__ import annotations

import os
import sys
import warnings
from collections import defaultdict
from datetime import date, timedelta

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.ensemble import HistGradientBoostingClassifier
from sqlalchemy import create_engine, text

warnings.filterwarnings("ignore")

# ─── 連線 ──────────────────────────────────────────────────────────────────────
PG_URL = os.getenv(
    "PG_URL",
    "postgresql://alphaforge:alphaforge_secret@10.0.4.3:5433/alphaforge",
)
engine = create_engine(PG_URL)

# ─── 常數 ──────────────────────────────────────────────────────────────────────
LOOKBACK_DAYS = 730
TEST_MONTHS = 6
GAP_MONTHS = 1
FORWARD_DAYS = {"5d": 5, "10d": 10, "30d": 30}
THRESHOLDS = {
    "5d": (0.03, 0.05),
    "10d": (0.03, 0.05),
    "30d": (0.05, 0.10),
}

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


# ─── 資料載入 ──────────────────────────────────────────────────────────────────
def load_data() -> pd.DataFrame:
    cutoff = date.today() - timedelta(days=LOOKBACK_DAYS)
    print(f"[Data] 載入 stock_features (>= {cutoff}) ...")
    sql = text("""
        SELECT sf.stock_id, sf.date, sf.close, sf.ma60,
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
               sf.atr_pct, sf.change_pct, sf.market_breadth
        FROM stock_features sf
        WHERE sf.date >= :cutoff AND sf.close > 0
        ORDER BY sf.date, sf.stock_id
    """)
    df = pd.read_sql(sql, engine, params={"cutoff": cutoff})
    df["date"] = pd.to_datetime(df["date"])
    print(f"[Data] 載入 {len(df):,} 筆，{df['stock_id'].nunique()} 檔股票，"
          f"{df['date'].nunique()} 個交易日")
    return df


def compute_forward_returns(df: pd.DataFrame, dim: str) -> pd.DataFrame:
    """計算前瞻報酬 + 二元標籤"""
    fwd = FORWARD_DAYS[dim]
    tlo, thi = THRESHOLDS[dim]
    df = df.copy()
    df["forward_close"] = df.groupby("stock_id")["close"].shift(-fwd)
    df["forward_return"] = (df["forward_close"] - df["close"]) / df["close"]
    df["label_lo"] = (df["forward_return"] > tlo).astype(float)
    df["label_hi"] = (df["forward_return"] > thi).astype(float)
    return df


def quantile_rank(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """跨截面百分位排名（每日 0~100）"""
    df = df.copy()
    rank_cols = []
    for c in cols:
        rc = f"rank_{c}"
        df[rc] = df.groupby("date")[c].rank(pct=True, method="average") * 100
        rank_cols.append(rc)
    return df, rank_cols


def time_decay_weights(dates: pd.Series) -> np.ndarray:
    max_date = dates.max()
    days_ago = (max_date - dates).dt.days
    w = np.exp(-0.001 * days_ago)
    w = np.clip(w, 0.2, 1.0)
    return w


def train_and_eval(
    train_df: pd.DataFrame,
    test_df: pd.DataFrame,
    rank_cols: list[str],
    label_col: str = "label_lo",
    lgb_params: dict | None = None,
) -> dict:
    """訓練 LightGBM + 評估 IC / 勝率 / Sharpe"""
    X_train = train_df[rank_cols].values
    y_train = train_df[label_col].values
    w_train = time_decay_weights(train_df["date"])

    X_test = test_df[rank_cols].values
    y_test_label = test_df[label_col].values
    y_test_ret = test_df["forward_return"].values

    if lgb_params is None:
        lgb_params = {}

    defaults = dict(
        max_iter=200, max_depth=4, max_leaf_nodes=15,
        learning_rate=0.01, min_samples_leaf=100,
        l2_regularization=1.0,
        random_state=42, verbose=0,
        class_weight="balanced",
    )
    # 轉換 LightGBM 參數名到 sklearn
    param_map = {
        "n_estimators": "max_iter",
        "num_leaves": "max_leaf_nodes",
        "min_child_samples": "min_samples_leaf",
        "reg_lambda": "l2_regularization",
    }
    for old_k, new_k in param_map.items():
        if old_k in lgb_params:
            lgb_params[new_k] = lgb_params.pop(old_k)
    # 移除 sklearn 不支援的參數
    for drop_key in ["subsample", "colsample_bytree", "reg_alpha", "is_unbalance",
                      "importance_type", "verbose"]:
        lgb_params.pop(drop_key, None)
    defaults.update(lgb_params)
    model = HistGradientBoostingClassifier(**defaults)
    model.fit(X_train, y_train, sample_weight=w_train)

    prob = model.predict_proba(X_test)[:, 1]

    # IC (Spearman)
    test_dates = test_df["date"].values
    unique_dates = np.unique(test_dates)
    daily_ics = []
    for d in unique_dates:
        mask = test_dates == d
        if mask.sum() < 30:
            continue
        ret_d = y_test_ret[mask]
        prob_d = prob[mask]
        if np.std(ret_d) < 1e-9 or np.std(prob_d) < 1e-9:
            continue
        ic, _ = stats.spearmanr(prob_d, ret_d)
        if not np.isnan(ic):
            daily_ics.append(ic)

    ic_mean = np.mean(daily_ics) if daily_ics else 0.0
    ic_std = np.std(daily_ics) if daily_ics else 1.0
    ic_t = ic_mean / (ic_std / np.sqrt(len(daily_ics))) if daily_ics and ic_std > 0 else 0.0

    # 勝率：取 top 20% 預測的實際報酬
    p80 = np.percentile(prob, 80)
    top_mask = prob >= p80
    top_ret = y_test_ret[top_mask]
    tlo = float(test_df.iloc[0].get("_threshold", 0.03))
    if "30d" in label_col or tlo >= 0.05:
        tlo = 0.05
    else:
        tlo = 0.03

    win_rate = np.mean(top_ret > tlo) if len(top_ret) > 0 else 0.0
    avg_ret = np.mean(top_ret) * 100 if len(top_ret) > 0 else 0.0
    mkt_win = np.mean(y_test_ret > tlo)

    # 特徵重要性 — 用 top-20% 預測的平均 rank 值差異作為代理
    # (HistGBM 沒有可靠的 feature_importances_ per gain)
    try:
        from sklearn.inspection import permutation_importance
        perm = permutation_importance(model, X_test[:2000], y_test_label[:2000],
                                      n_repeats=3, random_state=42, n_jobs=-1)
        imp = perm.importances_mean
    except Exception:
        imp = np.zeros(len(rank_cols))
    imp_pairs = sorted(zip(rank_cols, imp), key=lambda x: -x[1])
    top_features = [(c.replace("rank_", ""), float(v)) for c, v in imp_pairs[:10]]

    return {
        "ic_mean": ic_mean,
        "ic_t": ic_t,
        "n_days": len(daily_ics),
        "win_rate": win_rate,
        "mkt_win_rate": mkt_win,
        "excess_wr": win_rate - mkt_win,
        "avg_return_pct": avg_ret,
        "n_test": len(test_df),
        "n_top": int(top_mask.sum()),
        "top_features": top_features,
        "model": model,
    }


def split_train_test(df: pd.DataFrame):
    max_date = df["date"].max()
    test_start = max_date - pd.DateOffset(months=TEST_MONTHS)
    train_end = max_date - pd.DateOffset(months=TEST_MONTHS + GAP_MONTHS)
    train = df[df["date"] <= train_end].dropna(subset=["label_lo"])
    test = df[df["date"] >= test_start].dropna(subset=["label_lo"])
    return train, test


# ─── 實驗 ──────────────────────────────────────────────────────────────────────
def run_experiments(df_raw: pd.DataFrame):
    results = defaultdict(dict)

    for dim in ["5d", "10d", "30d"]:
        print(f"\n{'='*70}")
        print(f"  維度: {dim}")
        print(f"{'='*70}")

        df = compute_forward_returns(df_raw, dim)

        # ── Exp 1: Baseline（含 MA60 filter for 10d/30d）──
        df_exp = df.copy()
        if dim in ("10d", "30d"):
            df_exp = df_exp[df_exp["close"] > df_exp["ma60"]].copy()
        df_exp, rank_cols = quantile_rank(df_exp, BASE_FACTORS)
        train, test = split_train_test(df_exp)
        if len(train) < 200 or len(test) < 50:
            print(f"  [Exp1] 資料不足 (train={len(train)}, test={len(test)})")
            continue
        r = train_and_eval(train, test, rank_cols)
        results[dim]["1_baseline"] = r
        print(f"  [Exp1 Baseline]     IC={r['ic_mean']:+.4f} (t={r['ic_t']:.2f})  "
              f"WR={r['win_rate']:.1%} vs {r['mkt_win_rate']:.1%}  "
              f"excess={r['excess_wr']:+.1%}  avgRet={r['avg_return_pct']:+.2f}%")

        # ── Exp 2: 移除 MA60 filter ──
        df_exp2 = df.copy()
        df_exp2, rank_cols2 = quantile_rank(df_exp2, BASE_FACTORS)
        train2, test2 = split_train_test(df_exp2)
        r2 = train_and_eval(train2, test2, rank_cols2)
        results[dim]["2_no_ma60"] = r2
        print(f"  [Exp2 No MA60]      IC={r2['ic_mean']:+.4f} (t={r2['ic_t']:.2f})  "
              f"WR={r2['win_rate']:.1%} vs {r2['mkt_win_rate']:.1%}  "
              f"excess={r2['excess_wr']:+.1%}  avgRet={r2['avg_return_pct']:+.2f}%")

        # ── Exp 3: 維度專屬特徵 ──
        if dim == "5d":
            dim_factors = [
                "rsi2", "rsi14", "k", "d", "bb_pctb",
                "bias5", "bias10", "vol_ratio", "macd_osc",
                "foreign_net_buy", "trust_net_buy",
                "price_vs_high20", "change_pct", "atr_pct",
            ]
        elif dim == "10d":
            dim_factors = [
                "rsi14", "macd_dif", "macd_osc",
                "bias10", "bias20", "bb_pctb",
                "foreign_buy_5d", "foreign_buy_10d",
                "trust_buy_5d", "trust_buy_10d",
                "dealer_buy_5d", "dealer_buy_10d",
                "vol_ratio", "sector_rs", "price_vs_high20",
                "ma_trend", "revenue_yoy",
            ]
        else:
            dim_factors = BASE_FACTORS  # 30d 保持全因子

        df_exp3 = df.copy()
        available = [f for f in dim_factors if f in df_exp3.columns]
        df_exp3, rank_cols3 = quantile_rank(df_exp3, available)
        train3, test3 = split_train_test(df_exp3)
        r3 = train_and_eval(train3, test3, rank_cols3)
        results[dim]["3_dim_factors"] = r3
        print(f"  [Exp3 DimFactors]   IC={r3['ic_mean']:+.4f} (t={r3['ic_t']:.2f})  "
              f"WR={r3['win_rate']:.1%} vs {r3['mkt_win_rate']:.1%}  "
              f"excess={r3['excess_wr']:+.1%}  avgRet={r3['avg_return_pct']:+.2f}%  "
              f"({len(available)} factors)")

        # ── Exp 4: 不同門檻 ──
        alt_thresholds = {"5d": 0.02, "10d": 0.05, "30d": 0.08}
        alt_t = alt_thresholds[dim]
        df_exp4 = df.copy()
        df_exp4["label_alt"] = (df_exp4["forward_return"] > alt_t).astype(float)
        df_exp4, rank_cols4 = quantile_rank(df_exp4, BASE_FACTORS)
        train4 = df_exp4[df_exp4["date"] <= df_exp4["date"].max() - pd.DateOffset(months=TEST_MONTHS + GAP_MONTHS)]
        train4 = train4.dropna(subset=["label_alt"])
        test4 = df_exp4[df_exp4["date"] >= df_exp4["date"].max() - pd.DateOffset(months=TEST_MONTHS)]
        test4 = test4.dropna(subset=["label_alt"])
        r4 = train_and_eval(train4, test4, rank_cols4, label_col="label_alt")
        results[dim]["4_alt_threshold"] = r4
        print(f"  [Exp4 Threshold={alt_t}]  IC={r4['ic_mean']:+.4f} (t={r4['ic_t']:.2f})  "
              f"WR={r4['win_rate']:.1%} vs {r4['mkt_win_rate']:.1%}  "
              f"excess={r4['excess_wr']:+.1%}  avgRet={r4['avg_return_pct']:+.2f}%")

        # ── Exp 5: 超參數調整 ──
        tuned_params = {
            "5d": dict(n_estimators=300, max_depth=3, num_leaves=8,
                       min_child_samples=200, colsample_bytree=0.5, reg_lambda=3.0),
            "10d": dict(n_estimators=300, max_depth=5, num_leaves=20,
                        min_child_samples=80, subsample=0.7, reg_lambda=2.0),
            "30d": dict(n_estimators=400, max_depth=5, num_leaves=25,
                        min_child_samples=60, learning_rate=0.008),
        }
        df_exp5 = df.copy()
        df_exp5, rank_cols5 = quantile_rank(df_exp5, BASE_FACTORS)
        train5, test5 = split_train_test(df_exp5)
        r5 = train_and_eval(train5, test5, rank_cols5, lgb_params=tuned_params[dim])
        results[dim]["5_tuned_hp"] = r5
        print(f"  [Exp5 TunedHP]      IC={r5['ic_mean']:+.4f} (t={r5['ic_t']:.2f})  "
              f"WR={r5['win_rate']:.1%} vs {r5['mkt_win_rate']:.1%}  "
              f"excess={r5['excess_wr']:+.1%}  avgRet={r5['avg_return_pct']:+.2f}%")

        # ── Exp 6: 新衍生特徵 ──
        df_exp6 = df.copy()
        # 動量：5d/20d 報酬
        df_exp6["mom_5d"] = df_exp6.groupby("stock_id")["close"].pct_change(5)
        df_exp6["mom_20d"] = df_exp6.groupby("stock_id")["close"].pct_change(20)
        # 波動率正規化動量
        df_exp6["vol_adj_mom"] = df_exp6["mom_5d"] / (df_exp6["atr_pct"].clip(lower=0.01))
        # 外資+投信合力
        df_exp6["inst_flow_5d"] = df_exp6["foreign_buy_5d"].fillna(0) + df_exp6["trust_buy_5d"].fillna(0)
        df_exp6["inst_flow_10d"] = df_exp6["foreign_buy_10d"].fillna(0) + df_exp6["trust_buy_10d"].fillna(0)
        # RSI 背離代理：RSI 上升但價格下跌 → 潛在反彈
        df_exp6["rsi_price_div"] = df_exp6["rsi14"] - df_exp6["price_vs_high20"] * 100
        # 籌碼一致性：三大法人同向
        df_exp6["chip_consensus"] = (
            (df_exp6["foreign_buy_5d"].fillna(0) > 0).astype(float) +
            (df_exp6["trust_buy_5d"].fillna(0) > 0).astype(float) +
            (df_exp6["dealer_buy_5d"].fillna(0) > 0).astype(float)
        )
        new_factors = BASE_FACTORS + [
            "mom_5d", "mom_20d", "vol_adj_mom",
            "inst_flow_5d", "inst_flow_10d",
            "rsi_price_div", "chip_consensus",
        ]
        available6 = [f for f in new_factors if f in df_exp6.columns]
        df_exp6, rank_cols6 = quantile_rank(df_exp6, available6)
        train6, test6 = split_train_test(df_exp6)
        r6 = train_and_eval(train6, test6, rank_cols6)
        results[dim]["6_new_features"] = r6
        print(f"  [Exp6 NewFeatures]  IC={r6['ic_mean']:+.4f} (t={r6['ic_t']:.2f})  "
              f"WR={r6['win_rate']:.1%} vs {r6['mkt_win_rate']:.1%}  "
              f"excess={r6['excess_wr']:+.1%}  avgRet={r6['avg_return_pct']:+.2f}%  "
              f"({len(available6)} factors)")

        # ── Exp 7: Exp2+5+6 組合（最佳配方）──
        df_exp7 = df.copy()
        df_exp7["mom_5d"] = df_exp7.groupby("stock_id")["close"].pct_change(5)
        df_exp7["mom_20d"] = df_exp7.groupby("stock_id")["close"].pct_change(20)
        df_exp7["vol_adj_mom"] = df_exp7["mom_5d"] / (df_exp7["atr_pct"].clip(lower=0.01))
        df_exp7["inst_flow_5d"] = df_exp7["foreign_buy_5d"].fillna(0) + df_exp7["trust_buy_5d"].fillna(0)
        df_exp7["inst_flow_10d"] = df_exp7["foreign_buy_10d"].fillna(0) + df_exp7["trust_buy_10d"].fillna(0)
        df_exp7["rsi_price_div"] = df_exp7["rsi14"] - df_exp7["price_vs_high20"] * 100
        df_exp7["chip_consensus"] = (
            (df_exp7["foreign_buy_5d"].fillna(0) > 0).astype(float) +
            (df_exp7["trust_buy_5d"].fillna(0) > 0).astype(float) +
            (df_exp7["dealer_buy_5d"].fillna(0) > 0).astype(float)
        )
        combo_factors = new_factors
        available7 = [f for f in combo_factors if f in df_exp7.columns]
        df_exp7, rank_cols7 = quantile_rank(df_exp7, available7)
        train7, test7 = split_train_test(df_exp7)
        r7 = train_and_eval(train7, test7, rank_cols7, lgb_params=tuned_params[dim])
        results[dim]["7_combo"] = r7
        print(f"  [Exp7 Combo]        IC={r7['ic_mean']:+.4f} (t={r7['ic_t']:.2f})  "
              f"WR={r7['win_rate']:.1%} vs {r7['mkt_win_rate']:.1%}  "
              f"excess={r7['excess_wr']:+.1%}  avgRet={r7['avg_return_pct']:+.2f}%")

        # 列印最佳實驗的 Top 10 特徵
        best_exp = max(results[dim].items(), key=lambda x: x[1]["ic_mean"])
        print(f"\n  ★ 最佳: {best_exp[0]} (IC={best_exp[1]['ic_mean']:+.4f})")
        print(f"    Top 10 特徵:")
        for fname, fval in best_exp[1]["top_features"]:
            print(f"      {fname:25s}  gain={fval:.0f}")

    # ── 總結 ──
    print(f"\n{'='*70}")
    print("  總結")
    print(f"{'='*70}")
    for dim in ["5d", "10d", "30d"]:
        if dim not in results:
            continue
        print(f"\n  {dim}:")
        for exp_name, r in sorted(results[dim].items()):
            sig = "★" if abs(r["ic_t"]) > 2.0 else " "
            print(f"    {sig} {exp_name:20s}  IC={r['ic_mean']:+.4f} (t={r['ic_t']:+.2f})  "
                  f"WR={r['win_rate']:.1%}  excess={r['excess_wr']:+.1%}  "
                  f"avgRet={r['avg_return_pct']:+.2f}%")

    return results


if __name__ == "__main__":
    df = load_data()
    results = run_experiments(df)

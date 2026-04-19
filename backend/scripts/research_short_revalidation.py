"""Research-only: 重新驗證 5d/10d/20d short IC 顯著性 (2026-04-19 v2)。

背景: commit f21ec67 (2026-04-01) 以「全部 IC 不顯著」為由移除做空維度。
v1 腳本發現 AlphaMinerService._train_dimension 的 IC / wr_out / wr_mkt / avg_top
全部寫死 long 視角 (line 789/807/825/841), direction='short' 只改 label 沒改 metrics。
2026-04-01 當時的「不顯著」結論建立在錯誤 metric 上, 需用 short-aware metrics 重測。

本腳本不走 _train_all, 直接呼叫底層函式 (_load_features / _compute_forward_returns /
_compute_quantile_ranks / _add_weights) 取得 ranked features, 自己跑 LightGBM, 自己算:
  - IC_short = daily_spearman(prob, -forward_return) → 高 prob 預期跌, 實跌越多 IC 越高
  - wr_out_short = (top_returns < -thr_lo).mean() → 高 prob 股票實際下跌 >3% 比例
  - wr_mkt_short = (all_returns < -thr_lo).mean() → 全市場下跌 >3% 比例 (short baseline)
  - avg_top_short = -mean(top_returns) 顯示為「做空平均報酬%」(正數=賺)

不寫 DB, 不污染 snapshot。
"""
from __future__ import annotations

import os
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=UserWarning)

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

try:
    from dotenv import load_dotenv
    load_dotenv(BACKEND / ".env")
except Exception:
    pass

from app.db.database import SessionLocal  # noqa: E402
from app.services.alpha_miner_service import (  # noqa: E402
    AlphaMinerService,
    TRAINING_FACTORS,
)


SHORT_DIMENSIONS = [
    {"key": "5d_short",  "forward_days": 5,  "threshold_low": 0.03, "direction": "short"},
    {"key": "10d_short", "forward_days": 10, "threshold_low": 0.03, "direction": "short"},
    {"key": "20d_short", "forward_days": 20, "threshold_low": 0.03, "direction": "short"},
]

TEST_MONTHS = AlphaMinerService.TEST_MONTHS
GAP_MONTHS = AlphaMinerService.GAP_MONTHS


def _train_short_dim(df_base: pd.DataFrame, dim: dict, train_end, test_start):
    import lightgbm as lgb
    from scipy import stats

    thr_lo = dim["threshold_low"]
    fwd = dim["forward_days"]
    direction = dim["direction"]

    df = AlphaMinerService._compute_forward_returns(df_base, fwd, thr_lo, direction)

    factors = list(TRAINING_FACTORS.keys())
    rank_cols = [f"{f}_rank" for f in factors]
    available = [(f, rc) for f, rc in zip(factors, rank_cols) if rc in df.columns]
    factors = [a[0] for a in available]
    rank_cols = [a[1] for a in available]

    train_df = df[df["date"] <= pd.Timestamp(train_end)].dropna(subset=["label"])
    test_df = df[df["date"] >= pd.Timestamp(test_start)].dropna(subset=["label", "forward_return"])

    # MA60 趨勢過濾 (short: close < ma60)
    if "ma60" in df.columns and fwd >= 20:
        train_df = train_df[train_df["close"] < train_df["ma60"]].copy()
        test_df = test_df[test_df["close"] < test_df["ma60"]].copy()

    if len(train_df) < 200 or len(test_df) < 50:
        return None

    X_train = train_df[rank_cols].values
    y_train = train_df["label"].values
    w_train = train_df["weight"].values
    X_test = test_df[rank_cols].values

    clf = lgb.LGBMClassifier(
        n_estimators=200, max_depth=4, num_leaves=15,
        learning_rate=0.01, min_child_samples=100,
        subsample=0.8, colsample_bytree=0.8,
        reg_alpha=0.1, reg_lambda=1.0,
        random_state=42, verbose=-1, is_unbalance=True,
    )
    clf.fit(X_train, y_train, sample_weight=w_train)

    y_train_ret = train_df["forward_return"].values.clip(-0.5, 0.5)
    reg = lgb.LGBMRegressor(
        n_estimators=200, max_depth=4, num_leaves=15,
        learning_rate=0.01, min_child_samples=100,
        subsample=0.8, colsample_bytree=0.8,
        reg_alpha=0.1, reg_lambda=1.0,
        random_state=42, verbose=-1,
    )
    reg.fit(X_train, y_train_ret, sample_weight=w_train)

    p_clf_train = clf.predict_proba(X_train)[:, 1]
    p_clf_test = clf.predict_proba(X_test)[:, 1]
    p_reg_train = reg.predict(X_train)
    p_reg_test = reg.predict(X_test)

    reg_min, reg_max = p_reg_train.min(), p_reg_train.max()
    reg_range = reg_max - reg_min + 1e-9
    # short 模式下 regressor 預測 forward_return, 負值才是好訊號 → 翻號再正規化
    # 但 classifier 預測 "會大跌"=1, 機率高是好訊號
    # 為了 ensemble 一致 (都是"高=看跌強"), regressor 要翻號
    p_reg_train_n = 1.0 - (p_reg_train - reg_min) / reg_range
    p_reg_test_n = np.clip(1.0 - (p_reg_test - reg_min) / reg_range, 0, 1)

    prob_train = 0.5 * p_clf_train + 0.5 * p_reg_train_n
    prob_test = 0.5 * p_clf_test + 0.5 * p_reg_test_n

    # ── Short-aware metrics ───────────────────────────────────────────────
    # In-sample
    tr_thr = np.percentile(prob_train, 80)
    tr_mask = prob_train >= tr_thr
    tr_returns = train_df["forward_return"].values
    wr_in = float((tr_returns[tr_mask] < -thr_lo).mean()) if tr_mask.sum() > 0 else 0.0

    # Out-of-sample
    te_thr = np.percentile(prob_test, 80)
    te_mask = prob_test >= te_thr
    top_returns = test_df["forward_return"].values[te_mask]
    all_returns = test_df["forward_return"].values

    n_top = int(te_mask.sum())
    wr_out = float((top_returns < -thr_lo).mean()) if n_top > 0 else 0.0
    wr_mkt = float((all_returns < -thr_lo).mean()) if len(all_returns) > 0 else 0.0
    wr_pos = float((top_returns < 0).mean()) if n_top > 0 else 0.0  # short 視角: 下跌任意幅度
    avg_top_short = float(-np.nanmean(top_returns) * 100) if n_top > 0 else 0.0

    # IC: daily spearman(prob, -forward_return) → 正值代表 short 方向有 alpha
    test_copy = test_df.copy()
    test_copy["_prob"] = prob_test
    daily_ics = []
    for _, grp in test_copy.groupby("date"):
        if len(grp) < 10:
            continue
        if grp["_prob"].nunique() < 2 or grp["forward_return"].nunique() < 2:
            continue
        ic_d, _ = stats.spearmanr(grp["_prob"], -grp["forward_return"])
        if not np.isnan(ic_d):
            daily_ics.append(ic_d)
    if len(daily_ics) < 10:
        return None
    ics = np.array(daily_ics)
    ic = float(np.mean(ics))
    t_stat, p_val = stats.ttest_1samp(ics, 0)
    p_value = float(p_val) if not np.isnan(p_val) else 1.0
    p_corr = min(p_value * len(SHORT_DIMENSIONS), 1.0)
    is_sig = p_corr < 0.05
    overfit = abs(wr_in - wr_out) > 0.05

    return dict(
        dim=dim["key"],
        ic=ic,
        p_corr=p_corr,
        is_sig=is_sig,
        n_train=len(train_df),
        n_test=len(test_df),
        n_top=n_top,
        wr_in=wr_in,
        wr_out=wr_out,
        wr_mkt=wr_mkt,
        wr_pos=wr_pos,
        avg_top_short=avg_top_short,
        overfit=overfit,
    )


def main() -> int:
    print(f"[research] DATABASE_URL={os.environ.get('DATABASE_URL', '(unset)')}")
    print(f"[research] SHORT DIMENSIONS = {[d['key'] for d in SHORT_DIMENSIONS]}")

    db = SessionLocal()
    try:
        df_base = AlphaMinerService._load_features(db)
        if df_base.empty:
            print("[research] 沒有 features, abort")
            return 1
        max_date = df_base["date"].max()
        test_start = (max_date - pd.DateOffset(months=TEST_MONTHS)).date()
        train_end = (max_date - pd.DateOffset(months=TEST_MONTHS + GAP_MONTHS)).date()
        df_base = AlphaMinerService._compute_quantile_ranks(df_base)
        df_base = AlphaMinerService._add_weights(df_base, train_end)

        print(f"[research] train_end={train_end}  test_start={test_start}  max_date={max_date.date()}")
        print()

        results = []
        for dim in SHORT_DIMENSIONS:
            print(f"[research] training {dim['key']} ...")
            r = _train_short_dim(df_base, dim, train_end, test_start)
            if r is None:
                print(f"  {dim['key']}: 訓練失敗或樣本不足")
                continue
            results.append(r)
    finally:
        db.close()

    print()
    header = (
        f"{'dim':>10} | {'ic_short':>8} | {'p_corr':>7} | {'sig':>3} | "
        f"{'n_train':>7} | {'n_test':>6} | {'n_top':>5} | "
        f"{'wr_in':>6} | {'wr_out':>6} | {'wr_mkt':>6} | "
        f"{'超額':>5} | {'wr_pos':>6} | {'avg_top_s':>9} | {'overfit':>7}"
    )
    print(header)
    print("-" * len(header))
    for r in results:
        excess = (r["wr_out"] - r["wr_mkt"]) * 100
        print(
            f"{r['dim']:>10} | "
            f"{r['ic']:>+8.4f} | {r['p_corr']:>7.4f} | {('Y' if r['is_sig'] else 'N'):>3} | "
            f"{r['n_train']:>7d} | {r['n_test']:>6d} | {r['n_top']:>5d} | "
            f"{r['wr_in']*100:>5.1f}% | {r['wr_out']*100:>5.1f}% | {r['wr_mkt']*100:>5.1f}% | "
            f"{excess:>+4.1f}pp | {r['wr_pos']*100:>5.1f}% | {r['avg_top_short']:>+8.2f}% | "
            f"{('Y' if r['overfit'] else 'N'):>7}"
        )

    print()
    print("解讀 (short-aware, metric 已對 short direction 正確翻轉):")
    print("  - ic_short > 0 且 p_corr < 0.05 = 高分股票確實跌得比低分多 (short alpha)")
    print("  - wr_out = 模型 Top20% (預期會跌) 實際下跌 >3% 的比例")
    print("  - wr_mkt = 測試集全市場下跌 >3% 的比例 (short baseline)")
    print("  - 超額 = wr_out - wr_mkt, > +5pp 且 p_corr<0.05 → short 有重啟價值")
    print("  - avg_top_short = 做空 Top20% 的平均報酬 (%), 正值=平均賺到")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

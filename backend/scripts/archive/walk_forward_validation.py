"""
Walk-Forward 驗證 — 30d LightGBM 模型穩定性檢驗

設計：
- 非重疊測試期（4 個月），擴張訓練窗口（expanding window）
- 最小訓練期 8 個月，1 個月間隔避免標籤洩漏
- 使用生產環境完全相同的 LightGBM 超參數
- 通過標準：每窗口 IC > 0.05 且 t > 2.0
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

# ─── 生產環境參數（與 alpha_miner_service.py 一致）────────────────────────
FORWARD_DAYS = 30
THRESHOLD = 0.05          # label: forward_return > 5%
GAP_MONTHS = 1
TEST_MONTHS = 4           # 每窗口 4 個月測試期
MIN_TRAIN_MONTHS = 8      # 最小訓練期
COST = 0.006              # 來回交易成本

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

# HistGradientBoostingClassifier 參數（對齊生產 LightGBM 設定）
# LightGBM: n_estimators=200, max_depth=4, num_leaves=15, lr=0.01, min_child=100, reg_lambda=1.0
MODEL_PARAMS = dict(
    max_iter=200, max_depth=4, max_leaf_nodes=15,
    learning_rate=0.01, min_samples_leaf=100,
    l2_regularization=1.0, random_state=42, verbose=0,
    class_weight="balanced",
)


# ─── 資料載入 ─────────────────────────────────────────────────────────────
def load_data() -> pd.DataFrame:
    cols = ", ".join(["stock_id", "date", "close", "ma60"] + FACTORS)
    sql = text(f"SELECT {cols} FROM stock_features WHERE close > 0 ORDER BY date, stock_id")
    df = pd.read_sql(sql, engine)
    df["date"] = pd.to_datetime(df["date"])
    print(f"[Data] {len(df):,} 筆，{df['date'].min().date()} ~ {df['date'].max().date()}")
    return df


# ─── 分位數排名 ───────────────────────────────────────────────────────────
def compute_ranks(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    df = df.copy()
    rank_cols = []
    for f in FACTORS:
        if f in df.columns:
            rc = f"{f}_rank"
            df[rc] = df.groupby("date")[f].rank(pct=True, na_option="keep")
            rank_cols.append(rc)
    return df, rank_cols


# ─── 時間衰減權重 ─────────────────────────────────────────────────────────
def time_weights(dates: pd.Series, train_end: pd.Timestamp) -> np.ndarray:
    base_year = train_end.year
    delta = base_year - dates.dt.year
    w = np.clip(1.0 - 0.2 * delta, 0.2, 1.0)
    return w.values


# ─── 單窗口訓練 + 評估 ───────────────────────────────────────────────────
def evaluate_window(
    df: pd.DataFrame,
    rank_cols: list[str],
    train_end: pd.Timestamp,
    test_start: pd.Timestamp,
    test_end: pd.Timestamp,
    window_id: int,
) -> dict:
    # Forward return & label
    df_w = df.sort_values(["stock_id", "date"]).copy()
    df_w["forward_close"] = df_w.groupby("stock_id")["close"].shift(-FORWARD_DAYS)
    df_w["forward_return"] = (df_w["forward_close"] - df_w["close"]) / df_w["close"]
    df_w["label"] = (df_w["forward_return"] > THRESHOLD).astype(float)

    # MA60 過濾（30d 生產設定）
    df_w = df_w[df_w["close"] > df_w["ma60"]].copy()

    # 切割
    train = df_w[df_w["date"] <= train_end].dropna(subset=["label"])
    test = df_w[(df_w["date"] >= test_start) & (df_w["date"] <= test_end)].dropna(
        subset=["label", "forward_return"]
    )

    if len(train) < 1000 or len(test) < 200:
        print(f"  [Window {window_id}] 樣本不足 (train={len(train)}, test={len(test)})，跳過")
        return {"window": window_id, "skip": True}

    # 訓練
    X_train = train[rank_cols].values
    y_train = train["label"].values
    w_train = time_weights(train["date"], train_end)

    model = HistGradientBoostingClassifier(**MODEL_PARAMS)
    model.fit(X_train, y_train, sample_weight=w_train)

    # 預測
    X_test = test[rank_cols].values
    prob = model.predict_proba(X_test)[:, 1]

    # ─── Spearman IC（逐日計算）────────────────────────────────────────
    test = test.copy()
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
    ic_std = np.std(daily_ics) if daily_ics else 1
    ic_t = ic_mean / (ic_std / np.sqrt(len(daily_ics))) if daily_ics and ic_std > 0 else 0

    # ─── Top 20% 勝率與報酬 ───────────────────────────────────────────
    top_pct = 0.20
    cutoff_val = np.percentile(prob, (1 - top_pct) * 100)
    top_mask = prob >= cutoff_val
    fwd = test["forward_return"].values
    top_ret = fwd[top_mask]
    n_top = top_mask.sum()

    wr = float(np.nanmean(top_ret > THRESHOLD))
    mkt_wr = float(np.nanmean(fwd > THRESHOLD))
    avg_ret = float(np.nanmean(top_ret))
    mkt_avg = float(np.nanmean(fwd))
    excess = avg_ret - mkt_avg

    # ─── 月度 Sharpe ─────────────────────────────────────────────────
    test["_top"] = top_mask
    test["_month"] = test["date"].dt.to_period("M")
    monthly_ret = []
    for _, grp in test[test["_top"]].groupby("_month"):
        m = float(np.nanmean(grp["forward_return"].values)) - COST
        monthly_ret.append(m)
    sharpe = (
        (np.mean(monthly_ret) / np.std(monthly_ret) * np.sqrt(12))
        if len(monthly_ret) > 2 and np.std(monthly_ret) > 0
        else 0
    )

    # 通過標準
    passed = ic_mean > 0.05 and ic_t > 2.0

    return {
        "window": window_id,
        "skip": False,
        "train_end": train_end.date(),
        "test_start": test_start.date(),
        "test_end": test_end.date(),
        "n_train": len(train),
        "n_test": len(test),
        "n_days": len(daily_ics),
        "ic": ic_mean,
        "ic_t": ic_t,
        "wr": wr,
        "mkt_wr": mkt_wr,
        "excess_wr": wr - mkt_wr,
        "avg_ret": avg_ret,
        "mkt_avg": mkt_avg,
        "excess_ret": excess,
        "sharpe": sharpe,
        "n_top": n_top,
        "passed": passed,
    }


# ─── Walk-Forward 主流程 ─────────────────────────────────────────────────
def run_walk_forward(df: pd.DataFrame):
    df, rank_cols = compute_ranks(df)

    min_date = df["date"].min()
    max_date = df["date"].max()

    # 計算窗口：從第一個可能的測試起點開始，每 TEST_MONTHS 個月滑動
    first_test_start = min_date + pd.DateOffset(months=MIN_TRAIN_MONTHS + GAP_MONTHS)
    windows = []
    test_start = first_test_start
    wid = 1
    while test_start + pd.DateOffset(months=2) <= max_date:  # 至少 2 個月測試數據
        test_end = min(test_start + pd.DateOffset(months=TEST_MONTHS), max_date)
        train_end = test_start - pd.DateOffset(months=GAP_MONTHS)
        windows.append((wid, train_end, test_start, test_end))
        test_start = test_start + pd.DateOffset(months=TEST_MONTHS)
        wid += 1

    print(f"\n{'=' * 70}")
    print(f"  30d Walk-Forward 驗證（{len(windows)} 個非重疊窗口）")
    print(f"  數據範圍：{min_date.date()} ~ {max_date.date()}")
    print(f"  模型：LightGBM + MA60 過濾 + 分位數排名 + 時間衰減")
    print(f"  通過標準：IC > 0.05 且 t > 2.0")
    print(f"{'=' * 70}\n")

    results = []
    for wid, train_end, test_start, test_end in windows:
        train_end_ts = pd.Timestamp(train_end)
        test_start_ts = pd.Timestamp(test_start)
        test_end_ts = pd.Timestamp(test_end)

        print(f"  Window {wid}: train → {train_end_ts.date()} | test {test_start_ts.date()} ~ {test_end_ts.date()}")
        r = evaluate_window(df, rank_cols, train_end_ts, test_start_ts, test_end_ts, wid)
        results.append(r)

        if not r.get("skip"):
            mark = "PASS" if r["passed"] else "FAIL"
            print(f"    IC={r['ic']:+.4f} (t={r['ic_t']:+.2f})  [{mark}]")
            print(f"    WR={r['wr']:.1%} vs mkt {r['mkt_wr']:.1%} (+{r['excess_wr']:.1%})")
            print(f"    Avg={r['avg_ret']*100:+.2f}% vs mkt {r['mkt_avg']*100:+.2f}% (excess={r['excess_ret']*100:+.2f}%)")
            print(f"    Sharpe={r['sharpe']:.2f}  n_train={r['n_train']:,}  n_test={r['n_test']:,}  n_top={r['n_top']}")
        print()

    # ─── 總結 ─────────────────────────────────────────────────────────
    valid = [r for r in results if not r.get("skip")]
    if not valid:
        print("  ⚠️  所有窗口都因樣本不足被跳過")
        return

    ics = [r["ic"] for r in valid]
    passed_count = sum(1 for r in valid if r["passed"])
    total = len(valid)

    print("=" * 70)
    print("  Walk-Forward 總結")
    print("=" * 70)
    print(f"  窗口數：{total}")
    print(f"  通過：{passed_count}/{total}")
    print(f"  IC 平均：{np.mean(ics):+.4f}")
    print(f"  IC 標準差：{np.std(ics):.4f}")
    print(f"  IC 最小值：{np.min(ics):+.4f}")
    print(f"  IC 最大值：{np.max(ics):+.4f}")
    print()

    if passed_count == total:
        print("  ✅ 全部通過 — Alpha 穩定，可信賴")
    elif passed_count >= total - 1:
        fail_windows = [r for r in valid if not r["passed"]]
        print(f"  ⚠️  {total - passed_count} 個窗口未達標（可接受但需觀察）")
        for r in fail_windows:
            print(f"     Window {r['window']}: IC={r['ic']:+.4f} t={r['ic_t']:+.2f}")
    else:
        print("  ❌ 多個窗口未達標 — Alpha 不穩定，需重新思考策略")

    # 逐窗口表格
    print(f"\n{'─' * 70}")
    print(f"  {'Window':>8} {'Test Period':>24} {'IC':>8} {'t':>7} {'WR':>7} {'Excess':>8} {'Sharpe':>7} {'Pass':>5}")
    print(f"  {'─'*8} {'─'*24} {'─'*8} {'─'*7} {'─'*7} {'─'*8} {'─'*7} {'─'*5}")
    for r in valid:
        mark = "Y" if r["passed"] else "N"
        period = f"{r['test_start']} ~ {r['test_end']}"
        print(
            f"  {r['window']:>8} {period:>24} {r['ic']:>+8.4f} {r['ic_t']:>+7.2f} "
            f"{r['wr']:>6.1%} {r['excess_ret']*100:>+7.2f}% {r['sharpe']:>7.2f} {mark:>5}"
        )
    print(f"{'─' * 70}")


if __name__ == "__main__":
    df = load_data()
    run_walk_forward(df)

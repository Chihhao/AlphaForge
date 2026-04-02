"""
10d Walk-Forward 驗證 — 多因子組合 × gap=1（消除機械性相關）
目標：找出 10d 維度能否用正確的因子集產生真實 alpha
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
COST = 0.006  # 來回手續費+稅

# === 因子組合 ===
# A: 原始 15 因子（20d 用的那套）
FACTORS_A = [
    "roe", "yield_rate", "pb_ratio", "revenue_yoy",
    "foreign_hold_chg_5d", "foreign_net_buy", "foreign_buy_5d",
    "dealer_buy_20d", "vol_ratio", "foreign_buy_10d", "price_vs_high20",
    "neg_trust_net_buy", "neg_trust_buy_5d", "neg_trust_buy_10d", "neg_trust_buy_20d",
]

# B: 基本面為主（gap 測試確認 IC 不受 gap 影響的因子）
FACTORS_B = [
    "roe", "yield_rate", "pb_ratio", "revenue_yoy",
    "neg_trust_net_buy", "neg_trust_buy_5d", "neg_trust_buy_10d", "neg_trust_buy_20d",
]

# C: 基本面 + 精選籌碼（gap 測試後仍有殘餘 IC 的）
FACTORS_C = [
    "roe", "yield_rate", "pb_ratio", "revenue_yoy",
    "foreign_hold_chg_5d", "foreign_buy_5d",
    "dealer_buy_20d", "vol_ratio",
    "neg_trust_net_buy", "neg_trust_buy_5d", "neg_trust_buy_10d", "neg_trust_buy_20d",
]

# D: 基本面 + 均值回歸（短線可能有效的技術指標，用反向 IC）
FACTORS_D = [
    "roe", "yield_rate", "pb_ratio", "revenue_yoy",
    "bias10", "bias20", "bb_pctb", "price_vs_high20",
    "neg_trust_net_buy", "neg_trust_buy_5d", "neg_trust_buy_10d", "neg_trust_buy_20d",
]

STRATEGIES = {
    "A_15因子_gap0": (FACTORS_A, 0, False),
    "A_15因子_gap1": (FACTORS_A, 1, False),
    "B_基本面_gap1": (FACTORS_B, 1, False),
    "C_基本面+籌碼_gap1": (FACTORS_C, 1, False),
    "D_基本面+均值回歸_gap1": (FACTORS_D, 1, False),
    "A_15因子+MA60_gap1": (FACTORS_A, 1, True),
    "C_基本面+籌碼+MA60_gap1": (FACTORS_C, 1, True),
}


def load_data() -> pd.DataFrame:
    all_cols = set(["stock_id", "date", "close", "ma60",
                    "bias10", "bias20", "bb_pctb"])
    for fs in [FACTORS_A, FACTORS_B, FACTORS_C, FACTORS_D]:
        for f in fs:
            if f.startswith("neg_trust"):
                all_cols.add(f.replace("neg_", ""))
            else:
                all_cols.add(f)

    cols = sorted(all_cols)
    sql = text(f"SELECT {', '.join(cols)} FROM stock_features "
               f"WHERE close > 0 AND date >= '2023-03-01' ORDER BY date, stock_id")
    df = pd.read_sql(sql, engine)
    df["date"] = pd.to_datetime(df["date"])

    # 反向投信因子
    for s, d in [("trust_net_buy", "neg_trust_net_buy"),
                 ("trust_buy_5d", "neg_trust_buy_5d"),
                 ("trust_buy_10d", "neg_trust_buy_10d"),
                 ("trust_buy_20d", "neg_trust_buy_20d")]:
        if s in df.columns:
            df[d] = -df[s]  # 不 fillna(0)，讓 LightGBM 處理 NaN

    print(f"[Data] {len(df):,} 筆，{df['date'].min().date()} ~ {df['date'].max().date()}")
    return df


def prepare(df: pd.DataFrame, factors: list, forward_days: int,
            gap: int, threshold: float, ma60_filter: bool) -> pd.DataFrame:
    df = df.sort_values(["stock_id", "date"]).copy()

    # gap=1: return 從 T+1 算到 T+1+fwd，避免因子和 return 共用 close_T
    if gap > 0:
        df["entry_close"] = df.groupby("stock_id")["close"].shift(-gap)
        df["exit_close"] = df.groupby("stock_id")["close"].shift(-(gap + forward_days))
        df["forward_return"] = (df["exit_close"] - df["entry_close"]) / df["entry_close"]
    else:
        df["forward_close"] = df.groupby("stock_id")["close"].shift(-forward_days)
        df["forward_return"] = (df["forward_close"] - df["close"]) / df["close"]

    df["label"] = np.where(df["forward_return"].isna(), np.nan,
                           (df["forward_return"] > threshold).astype(float))

    if ma60_filter:
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


def run_strategy(df_raw: pd.DataFrame, name: str, factors: list,
                 gap: int, ma60_filter: bool) -> dict | None:
    forward_days = 10
    threshold = 0.03
    df = prepare(df_raw, factors, forward_days, gap, threshold, ma60_filter)
    rc = [f"{f}_rank" for f in factors if f"{f}_rank" in df.columns]
    wins = gen_windows(df)
    all_ics, all_excess, monthly_rets = [], [], []

    print(f"\n{'─' * 70}")
    print(f"  {name}  ({len(factors)}因子, gap={gap}, MA60={'Y' if ma60_filter else 'N'})")
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
        ic_t = ic / (np.std(daily_ics) / np.sqrt(len(daily_ics))) if daily_ics and np.std(daily_ics) > 0 else 0
        all_ics.append(ic)

        # Top 10%
        cut = np.percentile(prob, 90)
        top = prob >= cut
        fwd = test["forward_return"].values
        excess = np.nanmean(fwd[top]) - np.nanmean(fwd)
        all_excess.append(excess)
        wr = float(np.nanmean(fwd[top] > 0))  # 真實勝率（報酬>0）

        test["_top"] = top
        test["_m"] = test["date"].dt.to_period("M")
        for _, g in test[test["_top"]].groupby("_m"):
            monthly_rets.append(float(np.nanmean(g["forward_return"].values)) - COST)

        mark = "PASS" if ic > 0.03 and ic_t > 1.5 else "---"
        print(f"  W{wid} {ts.date()}~{te.date()} IC={ic:+.4f}(t={ic_t:+.1f}) "
              f"WR={wr:.0%} ex={excess * 100:+.1f}% [{mark}]")

    if not all_ics:
        print("  [跳過] 窗口不足")
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
        "ic_pos_pct": sum(1 for x in all_ics if x > 0) / len(all_ics),
        "ann": ann, "sharpe": sh, "max_dd": dd,
    }


def main():
    df = load_data()
    results = []

    for name, (factors, gap, ma60) in STRATEGIES.items():
        r = run_strategy(df, name, factors, gap, ma60)
        if r:
            results.append(r)

    # 比較表
    print(f"\n{'=' * 90}")
    print(f"  10d Walk-Forward 全策略比較")
    print(f"{'=' * 90}")
    results.sort(key=lambda x: x["sharpe"], reverse=True)
    print(f"\n  {'策略':>30} {'因子':>4} {'avgIC':>7} {'minIC':>7} {'IC>0':>5} "
          f"{'年化':>7} {'Sharpe':>7} {'MaxDD':>7}")
    print("  " + "─" * 80)
    for r in results:
        print(f"  {r['name']:>30} {r['n_factors']:>4} {r['avg_ic']:>+7.4f} {r['min_ic']:>+7.4f} "
              f"{r['ic_pos']:>5} {r['ann'] * 100:>+6.1f}% {r['sharpe']:>7.2f} {r['max_dd'] * 100:>+6.1f}%")


if __name__ == "__main__":
    main()

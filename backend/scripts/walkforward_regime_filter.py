"""
Walk-Forward 回測：大盤 Regime Filter 驗證
比較有/無 regime filter 對共振策略的影響

Regime 條件：TAIEX 收盤 > MA20 才推薦（否則跳過當天）
"""
from __future__ import annotations
import os, warnings
import numpy as np
import pandas as pd
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


def load_data() -> pd.DataFrame:
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
    print(f"[Data] {len(df):,} 筆，{df['date'].min().date()} ~ {df['date'].max().date()}")
    return df


def load_taiex_regime() -> pd.DataFrame:
    """載入 TAIEX 日線，計算 MA20 regime"""
    # 0050 (元大台灣50) 當大盤 proxy，資料量比 ^TWII 完整
    sql = text("SELECT date, close FROM stock_prices "
               "WHERE stock_id = '0050' AND date >= '2023-01-01' ORDER BY date")
    tw = pd.read_sql(sql, engine)
    tw["date"] = pd.to_datetime(tw["date"])
    tw["close"] = tw["close"].astype(float)
    tw["taiex_ma20"] = tw["close"].rolling(20).mean()
    tw["taiex_ma60"] = tw["close"].rolling(60).mean()
    tw["regime_ma20"] = tw["close"] > tw["taiex_ma20"]
    tw["regime_ma60"] = tw["close"] > tw["taiex_ma60"]
    return tw[["date", "close", "taiex_ma20", "taiex_ma60", "regime_ma20", "regime_ma60"]].rename(
        columns={"close": "taiex_close"})


def compute_ranks(df: pd.DataFrame) -> pd.DataFrame:
    for f in STABLE_15:
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


def train_ensemble(train_df, rc, train_end):
    X_tr = train_df[rc].values
    y_tr = train_df["label"].values
    w = np.clip(1.0 - 0.2 * (train_end.year - train_df["date"].dt.year), 0.2, 1.0).values

    clf = HistGradientBoostingClassifier(
        max_iter=200, max_depth=4, max_leaf_nodes=15,
        learning_rate=0.01, min_samples_leaf=100, l2_regularization=1.0,
        random_state=42, class_weight="balanced")
    clf.fit(X_tr, y_tr, sample_weight=w)

    y_reg = train_df["forward_return"].values.clip(-0.5, 0.5)
    reg = HistGradientBoostingRegressor(
        max_iter=200, max_depth=4, max_leaf_nodes=15,
        learning_rate=0.01, min_samples_leaf=100, l2_regularization=1.0,
        random_state=42)
    reg.fit(X_tr, y_reg, sample_weight=w)

    return clf, reg


def predict_ensemble(clf, reg, X_test, X_train):
    p_clf = clf.predict_proba(X_test)[:, 1]
    p_reg = reg.predict(X_test)
    rmin, rmax = reg.predict(X_train).min(), reg.predict(X_train).max()
    p_reg_n = np.clip((p_reg - rmin) / (rmax - rmin + 1e-9), 0, 1)
    return 0.5 * p_clf + 0.5 * p_reg_n


def eval_with_regime(merged: pd.DataFrame, regime_col: str | None, label: str):
    """評估策略績效，可選 regime filter"""
    if regime_col:
        mask = merged[regime_col].fillna(False)
        active = merged[mask]
        skip = merged[~mask]
    else:
        active = merged
        skip = merged.iloc[0:0]

    fwd = active["forward_return"].values
    if len(fwd) == 0:
        return None

    cut20 = np.percentile(active["_p20"], 90)
    cut10 = np.percentile(active["_p10"], 90)
    top20 = active["_p20"] >= cut20
    top10 = active["_p10"] >= cut10
    resonance = top20 & top10

    n_res = int(resonance.sum())
    if n_res == 0:
        return None

    ret_res = np.nanmean(fwd[resonance.values])
    ret_mkt = np.nanmean(fwd)
    wr_res = np.nanmean(fwd[resonance.values] > 0)

    # 跳過天數的市場報酬（觀察跳過時段的市場表現）
    skip_mkt = np.nanmean(skip["forward_return"].values) if len(skip) > 0 else np.nan

    return {
        "label": label,
        "ret_res": ret_res,
        "ret_mkt": ret_mkt,
        "wr_res": wr_res,
        "n_res": n_res,
        "n_active_days": active["date"].nunique(),
        "n_skip_days": skip["date"].nunique(),
        "skip_mkt": skip_mkt,
    }


def main():
    df_raw = load_data()
    taiex = load_taiex_regime()
    print(f"[TAIEX] {len(taiex)} 筆，regime_ma20 True: {taiex['regime_ma20'].sum()}, "
          f"False: {(~taiex['regime_ma20']).sum()}")

    results_all = {}
    for fwd_days, dim_label in [(20, "20d"), (10, "10d")]:
        df = df_raw.sort_values(["stock_id", "date"]).copy()
        df["entry_close"] = df.groupby("stock_id")["close"].shift(-1)
        df["exit_close"] = df.groupby("stock_id")["close"].shift(-(1 + fwd_days))
        df[f"fwd_{dim_label}"] = (df["exit_close"] - df["entry_close"]) / df["entry_close"]
        df["forward_return"] = df[f"fwd_{dim_label}"]
        df["label"] = np.where(df["forward_return"].isna(), np.nan,
                               (df["forward_return"] > 0.03).astype(float))
        df = df[df["close"] > df["ma60"]].copy()
        df = compute_ranks(df)
        results_all[dim_label] = df

    rc = [f"{f}_rank" for f in STABLE_15 if f"{f}_rank" in results_all["20d"].columns]
    wins = gen_windows(results_all["20d"])

    # 測試多種 regime filter
    regime_configs = [
        (None, "無 filter"),
        ("regime_ma20", "TAIEX > MA20"),
        ("regime_ma60", "TAIEX > MA60"),
    ]

    all_results = {cfg[1]: [] for cfg in regime_configs}

    print(f"\n{'=' * 110}")
    print(f"  大盤 Regime Filter Walk-Forward 驗證（gap=1, MA60 個股過濾）")
    print(f"{'=' * 110}")

    for wid, tr, ts, te in wins:
        df20 = results_all["20d"]
        train20 = df20[df20["date"] <= tr].dropna(subset=["label"])
        test20 = df20[(df20["date"] >= ts) & (df20["date"] <= te)].dropna(subset=["label", "forward_return"])

        df10 = results_all["10d"]
        train10 = df10[df10["date"] <= tr].dropna(subset=["label"])
        test10 = df10[(df10["date"] >= ts) & (df10["date"] <= te)].dropna(subset=["label", "forward_return"])

        if len(train20) < 2000 or len(test20) < 300:
            continue
        if len(train10) < 2000 or len(test10) < 300:
            continue

        clf20, reg20 = train_ensemble(train20, rc, tr)
        clf10, reg10 = train_ensemble(train10, rc, tr)

        prob20 = predict_ensemble(clf20, reg20, test20[rc].values, train20[rc].values)
        prob10 = predict_ensemble(clf10, reg10, test10[rc].values, train10[rc].values)

        test20 = test20.copy()
        test20["_p20"] = prob20
        test20["_key"] = test20["stock_id"] + "_" + test20["date"].astype(str)

        test10 = test10.copy()
        test10["_p10"] = prob10
        test10["_key"] = test10["stock_id"] + "_" + test10["date"].astype(str)

        merged = test20[["_key", "stock_id", "date", "_p20", "forward_return"]].merge(
            test10[["_key", "_p10"]], on="_key", how="inner"
        )
        if len(merged) < 100:
            continue

        # 加入 regime 資訊
        merged = merged.merge(taiex[["date", "regime_ma20", "regime_ma60"]], on="date", how="left")

        print(f"\n  W{wid} {ts.date()} ~ {te.date()}")
        print(f"  {'策略':<16} {'共振報酬':>8} {'市場報酬':>8} {'超額':>8} {'勝率':>6} {'共振N':>6} {'活躍日':>6} {'跳過日':>6} {'跳過期市場':>10}")
        print(f"  {'─' * 96}")

        for regime_col, regime_label in regime_configs:
            result = eval_with_regime(merged, regime_col, regime_label)
            if result is None:
                print(f"  {regime_label:<16} {'N/A':>8}")
                continue

            excess = result["ret_res"] - result["ret_mkt"]
            skip_str = f"{result['skip_mkt']*100:>+8.1f}%" if not np.isnan(result["skip_mkt"]) else "     N/A"
            print(f"  {regime_label:<16} {result['ret_res']*100:>+7.1f}% {result['ret_mkt']*100:>+7.1f}% "
                  f"{excess*100:>+7.1f}% {result['wr_res']:>5.0%} {result['n_res']:>5} "
                  f"{result['n_active_days']:>5} {result['n_skip_days']:>5} {skip_str}")

            all_results[regime_label].append(result)

    # === 總結 ===
    print(f"\n{'=' * 110}")
    print(f"  === 總結：各 Regime Filter 平均績效 ===")
    print(f"{'=' * 110}")
    print(f"  {'策略':<16} {'共振報酬':>8} {'市場報酬':>8} {'超額':>8} {'勝率':>6} {'跳過期市場':>10} {'勝窗口':>8}")
    print(f"  {'─' * 76}")

    for regime_label in ["無 filter", "TAIEX > MA20", "TAIEX > MA60"]:
        results = all_results[regime_label]
        if not results:
            continue
        avg_res = np.mean([r["ret_res"] for r in results])
        avg_mkt = np.mean([r["ret_mkt"] for r in results])
        avg_excess = avg_res - avg_mkt
        avg_wr = np.mean([r["wr_res"] for r in results])
        skip_mkts = [r["skip_mkt"] for r in results if not np.isnan(r["skip_mkt"])]
        avg_skip = np.mean(skip_mkts) if skip_mkts else np.nan
        win_windows = sum(1 for r in results if r["ret_res"] > r["ret_mkt"])
        total_windows = len(results)

        skip_str = f"{avg_skip*100:>+8.1f}%" if not np.isnan(avg_skip) else "     N/A"
        print(f"  {regime_label:<16} {avg_res*100:>+7.1f}% {avg_mkt*100:>+7.1f}% "
              f"{avg_excess*100:>+7.1f}% {avg_wr:>5.0%} {skip_str} "
              f"{win_windows}/{total_windows}")

    # === 逐窗口超額比較 ===
    print(f"\n  === 逐窗口超額報酬比較 ===")
    print(f"  {'窗口':>4}  {'無 filter':>10}  {'MA20 filter':>12}  {'MA60 filter':>12}  {'MA20 改善':>10}")
    print(f"  {'─' * 56}")

    for i in range(len(all_results["無 filter"])):
        no_f = all_results["無 filter"][i]
        ma20 = all_results["TAIEX > MA20"][i] if i < len(all_results["TAIEX > MA20"]) else None
        ma60 = all_results["TAIEX > MA60"][i] if i < len(all_results["TAIEX > MA60"]) else None

        ex_no = (no_f["ret_res"] - no_f["ret_mkt"]) * 100
        ex_ma20 = (ma20["ret_res"] - ma20["ret_mkt"]) * 100 if ma20 else float("nan")
        ex_ma60 = (ma60["ret_res"] - ma60["ret_mkt"]) * 100 if ma60 else float("nan")
        improve = ex_ma20 - ex_no if not np.isnan(ex_ma20) else float("nan")

        wid = no_f.get("wid", i + 1)
        print(f"  W{i+1:>2}   {ex_no:>+9.1f}%  {ex_ma20:>+11.1f}%  {ex_ma60:>+11.1f}%  {improve:>+9.1f}%")


if __name__ == "__main__":
    main()

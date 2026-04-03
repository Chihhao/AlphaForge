"""
Walk-Forward 因子組合對比實驗
A. 現行 15 因子
B. 基本面為主 7 因子（移除不穩定籌碼因子）
C. 純基本面 4 因子
D. 基本面 + 營收驚喜 6 因子（用 rev_surprise/rev_accel 替換籌碼）
E. 穩定籌碼 + 營收驚喜 9 因子（折衷方案）

全部搭配 regime=MA20, gap=1, MA60, 共振(20d+10d)
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

# === 因子組合定義 ===
FACTOR_SETS = {
    "A_現行15": [
        "roe", "yield_rate", "pb_ratio", "revenue_yoy",
        "foreign_hold_chg_5d", "foreign_net_buy", "foreign_buy_5d",
        "dealer_buy_20d", "vol_ratio", "foreign_buy_10d", "price_vs_high20",
        "neg_trust_net_buy", "neg_trust_buy_5d", "neg_trust_buy_10d", "neg_trust_buy_20d",
    ],
    "B_基本面+穩定籌碼7": [
        "roe", "pb_ratio", "revenue_yoy", "yield_rate",
        "foreign_hold_chg_5d", "dealer_buy_20d", "vol_ratio",
    ],
    "C_純基本面4": [
        "roe", "pb_ratio", "revenue_yoy", "yield_rate",
    ],
    "D_基本面+營收6": [
        "roe", "pb_ratio", "revenue_yoy", "yield_rate",
        "rev_surprise", "rev_accel",
    ],
    "E_穩定+營收9": [
        "roe", "pb_ratio", "revenue_yoy", "yield_rate",
        "rev_surprise", "rev_accel",
        "foreign_hold_chg_5d", "dealer_buy_20d", "vol_ratio",
    ],
}

ALL_FACTORS = sorted(set(f for fs in FACTOR_SETS.values() for f in fs))


def load_data() -> pd.DataFrame:
    base_cols = ["stock_id", "date", "close", "ma60"]
    raw_factors = list(set(ALL_FACTORS) - {"neg_trust_net_buy", "neg_trust_buy_5d",
                                            "neg_trust_buy_10d", "neg_trust_buy_20d"})
    # 需要原始 trust 因子來計算 neg 版本
    trust_raw = ["trust_net_buy", "trust_buy_5d", "trust_buy_10d", "trust_buy_20d"]
    cols = base_cols + raw_factors + [t for t in trust_raw if t not in raw_factors]
    cols = sorted(set(cols))

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
    # 因子覆蓋率
    for f in ALL_FACTORS:
        if f in df.columns:
            cov = df[f].notna().mean()
            if cov < 0.8:
                print(f"  ⚠ {f} 覆蓋率 {cov:.1%}")
    return df


def load_regime() -> pd.DataFrame:
    sql = text("SELECT date, close FROM stock_prices "
               "WHERE stock_id = '0050' AND date >= '2023-01-01' ORDER BY date")
    tw = pd.read_sql(sql, engine)
    tw["date"] = pd.to_datetime(tw["date"])
    tw["close"] = tw["close"].astype(float)
    tw["ma20"] = tw["close"].rolling(20).mean()
    tw["regime_ok"] = tw["close"] > tw["ma20"]
    return tw[["date", "regime_ok"]]


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
    X = train_df[rc].values
    y = train_df["label"].values
    w = np.clip(1.0 - 0.2 * (train_end.year - train_df["date"].dt.year), 0.2, 1.0).values

    clf = HistGradientBoostingClassifier(
        max_iter=200, max_depth=4, max_leaf_nodes=15,
        learning_rate=0.01, min_samples_leaf=100, l2_regularization=1.0,
        random_state=42, class_weight="balanced")
    clf.fit(X, y, sample_weight=w)

    y_reg = train_df["forward_return"].values.clip(-0.5, 0.5)
    reg = HistGradientBoostingRegressor(
        max_iter=200, max_depth=4, max_leaf_nodes=15,
        learning_rate=0.01, min_samples_leaf=100, l2_regularization=1.0,
        random_state=42)
    reg.fit(X, y_reg, sample_weight=w)
    return clf, reg


def predict_ensemble(clf, reg, X_test, X_train):
    p_clf = clf.predict_proba(X_test)[:, 1]
    p_reg = reg.predict(X_test)
    rmin, rmax = reg.predict(X_train).min(), reg.predict(X_train).max()
    p_reg_n = np.clip((p_reg - rmin) / (rmax - rmin + 1e-9), 0, 1)
    return 0.5 * p_clf + 0.5 * p_reg_n


def run_experiment(factor_set_name: str, factors: list, df_raw: pd.DataFrame,
                   regime: pd.DataFrame, windows: list):
    """跑單一因子組合的 walk-forward"""

    # 計算 rank 特徵
    rc = []
    for f in factors:
        col = f"{f}_rank"
        rc.append(col)

    results = []

    for wid, tr, ts, te in windows:
        per_dim = {}
        for fwd_days, dim in [(20, "20d"), (10, "10d")]:
            df = df_raw.sort_values(["stock_id", "date"]).copy()
            df["entry_close"] = df.groupby("stock_id")["close"].shift(-1)
            df["exit_close"] = df.groupby("stock_id")["close"].shift(-(1 + fwd_days))
            df["forward_return"] = (df["exit_close"] - df["entry_close"]) / df["entry_close"]
            df["label"] = np.where(df["forward_return"].isna(), np.nan,
                                   (df["forward_return"] > 0.03).astype(float))
            df = df[df["close"] > df["ma60"]].copy()

            # 計算 rank
            for f in factors:
                if f in df.columns:
                    df[f"{f}_rank"] = df.groupby("date")[f].rank(pct=True, na_option="keep")

            # 只 dropna label/forward_return，HistGradientBoosting 原生支援 NaN 特徵
            train = df[df["date"] <= tr].dropna(subset=["label"])
            test = df[(df["date"] >= ts) & (df["date"] <= te)].dropna(
                subset=["label", "forward_return"])

            if len(train) < 2000 or len(test) < 300:
                per_dim[dim] = None
                continue

            clf, reg = train_ensemble(train, rc, tr)
            prob = predict_ensemble(clf, reg, test[rc].values, train[rc].values)

            test = test.copy()
            test[f"_p{dim}"] = prob
            test["_key"] = test["stock_id"] + "_" + test["date"].astype(str)
            per_dim[dim] = test

        if per_dim.get("20d") is None or per_dim.get("10d") is None:
            continue

        t20 = per_dim["20d"]
        t10 = per_dim["10d"]

        merged = t20[["_key", "stock_id", "date", "_p20d", "forward_return"]].merge(
            t10[["_key", "_p10d"]], on="_key", how="inner"
        )
        if len(merged) < 100:
            continue

        # Regime filter
        merged = merged.merge(regime, on="date", how="left")
        merged["regime_ok"] = merged["regime_ok"].fillna(True)
        active = merged[merged["regime_ok"]]
        if len(active) < 50:
            continue

        fwd = active["forward_return"].values

        cut20 = np.percentile(active["_p20d"], 90)
        cut10 = np.percentile(active["_p10d"], 90)
        resonance = (active["_p20d"] >= cut20) & (active["_p10d"] >= cut10)

        n_res = int(resonance.sum())
        if n_res == 0:
            continue

        ret_res = np.nanmean(fwd[resonance.values])
        ret_mkt = np.nanmean(fwd)
        wr = np.nanmean(fwd[resonance.values] > 0)

        results.append({
            "wid": wid, "period": f"{ts.date()}~{te.date()}",
            "ret": ret_res, "mkt": ret_mkt, "excess": ret_res - ret_mkt,
            "wr": wr, "n": n_res,
        })

    return results


def main():
    df_raw = load_data()
    regime = load_regime()

    # 先算一次 windows
    df_tmp = df_raw.copy()
    df_tmp["date"] = pd.to_datetime(df_tmp["date"])
    windows = gen_windows(df_tmp)

    all_results = {}

    for name, factors in FACTOR_SETS.items():
        print(f"\n--- 跑 {name} ({len(factors)} 因子) ---")
        results = run_experiment(name, factors, df_raw, regime, windows)
        all_results[name] = results

    # === 總結表格 ===
    print(f"\n{'=' * 120}")
    print(f"  因子組合 Walk-Forward 對比（regime=MA20, gap=1, MA60, 共振）")
    print(f"{'=' * 120}")

    # 逐窗口比較
    w_ids = sorted(set(r["wid"] for rs in all_results.values() for r in rs))

    header = f"  {'窗口':>4}"
    for name in FACTOR_SETS:
        short = name.split("_")[1] if "_" in name else name
        header += f"  {short:>14}"
    print(header)
    print(f"  {'─' * (6 + 16 * len(FACTOR_SETS))}")

    for wid in w_ids:
        row = f"  W{wid:>2}"
        for name in FACTOR_SETS:
            match = [r for r in all_results[name] if r["wid"] == wid]
            if match:
                row += f"  {match[0]['excess']*100:>+13.1f}%"
            else:
                row += f"  {'N/A':>14}"
        print(row)

    # 平均
    print(f"  {'─' * (6 + 16 * len(FACTOR_SETS))}")
    row_avg = f"  平均"
    row_ret = f"  報酬"
    row_wr = f"  勝率"
    row_win = f"  勝窗"

    for name in FACTOR_SETS:
        rs = all_results[name]
        if rs:
            avg_excess = np.mean([r["excess"] for r in rs])
            avg_ret = np.mean([r["ret"] for r in rs])
            avg_wr = np.mean([r["wr"] for r in rs])
            n_win = sum(1 for r in rs if r["excess"] > 0)
            row_avg += f"  {avg_excess*100:>+13.1f}%"
            row_ret += f"  {avg_ret*100:>+13.1f}%"
            row_wr += f"  {avg_wr*100:>12.0f}%"
            row_win += f"  {n_win}/{len(rs):>11}"
        else:
            row_avg += f"  {'N/A':>14}"
            row_ret += f"  {'N/A':>14}"
            row_wr += f"  {'N/A':>14}"
            row_win += f"  {'N/A':>14}"

    print(row_avg)
    print(row_ret)
    print(row_wr)
    print(row_win)

    # 空頭 vs 多頭分析
    print(f"\n  === 空頭窗口 (W3+W4) vs 多頭窗口 (W1+W2+W5+W6+W7) ===")
    bear_wids = {3, 4}

    for name in FACTOR_SETS:
        rs = all_results[name]
        bear = [r for r in rs if r["wid"] in bear_wids]
        bull = [r for r in rs if r["wid"] not in bear_wids]
        short = name.split("_")[1] if "_" in name else name

        bear_ex = np.mean([r["excess"] for r in bear]) * 100 if bear else 0
        bull_ex = np.mean([r["excess"] for r in bull]) * 100 if bull else 0
        print(f"  {short:<20} 空頭超額: {bear_ex:>+6.1f}%  多頭超額: {bull_ex:>+6.1f}%")


if __name__ == "__main__":
    main()

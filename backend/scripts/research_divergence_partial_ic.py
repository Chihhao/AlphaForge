"""
背離因子 Partial IC + ML Walk-Forward 驗證

1. Partial IC：控制現有 12 因子後，背離因子是否仍有獨立預測力
2. 相關性矩陣：與 price_vs_high20、ivol_20d 等可能重疊因子的相關性
3. ML Walk-Forward：12 因子 baseline vs 12+背離因子的邊際 IC 提升
"""
from __future__ import annotations

import os
import warnings
from typing import Dict, List

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sqlalchemy import create_engine, text

warnings.filterwarnings("ignore")

PG_URL = os.getenv(
    "PG_URL",
    "postgresql://alphaforge:alphaforge_secret@10.0.4.3:5433/alphaforge",
)
engine = create_engine(PG_URL)

HOLD = 20
GAP = 1
TRAIN_MONTHS = 12

# 現有 12 因子
BASE_12 = [
    "roe", "yield_rate", "pb_ratio", "revenue_yoy",
    "rev_surprise", "rev_accel",
    "foreign_hold_chg_5d", "dealer_buy_20d", "vol_ratio",
    "ivol_20d",
    "neg_trust_net_buy", "short_chg_5d",
]

# 候選背離因子
DIV_FACTORS = ["div_score_top", "div_score_bot", "neg_divergence_avg"]


# ═══════════════════════════════════════════════════════════════════
# 資料載入
# ═══════════════════════════════════════════════════════════════════
def load_data() -> pd.DataFrame:
    # 從 stock_features 載入現有因子
    base_cols = ["stock_id", "date", "close", "ma60", "volume",
                 "price_vs_high20", "rsi14", "macd_dif"]
    factor_cols = sorted(set(
        [f.replace("neg_", "") for f in BASE_12] + base_cols
    ))
    sql = text(f"""
        SELECT {', '.join(factor_cols)}
        FROM stock_features
        WHERE close > 0 AND date >= '2022-09-01'
        ORDER BY date, stock_id
    """)
    df = pd.read_sql(sql, engine)
    df["date"] = pd.to_datetime(df["date"])

    # 衍生反向因子
    df["neg_trust_net_buy"] = -df["trust_net_buy"]

    # 流動性過濾
    df = df[df["volume"] >= 500_000].copy()
    df = df[df["stock_id"].str.match(r"^[1-9]\d{3}$")].copy()

    # ─── 從 stock_prices 載入 OHLCV 計算背離因子 ─────────────────
    sql2 = text("""
        SELECT stock_id, date, open, high, low, close
        FROM stock_prices
        WHERE date >= '2022-09-01' AND close > 0
        ORDER BY stock_id, date
    """)
    prices = pd.read_sql(sql2, engine)
    prices["date"] = pd.to_datetime(prices["date"])

    # RSI 14
    grp = prices.groupby("stock_id")
    delta = grp["close"].diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.groupby(prices["stock_id"]).transform(
        lambda x: x.ewm(span=14, adjust=False).mean()
    )
    avg_loss = loss.groupby(prices["stock_id"]).transform(
        lambda x: x.ewm(span=14, adjust=False).mean()
    )
    rs = avg_gain / avg_loss.replace(0, np.nan)
    prices["_rsi"] = 100 - (100 / (1 + rs))

    # MACD DIF
    ema12 = grp["close"].transform(lambda x: x.ewm(span=12, adjust=False).mean())
    ema26 = grp["close"].transform(lambda x: x.ewm(span=26, adjust=False).mean())
    prices["_dif"] = ema12 - ema26

    # 日報酬
    prices["_ret"] = grp["close"].pct_change()

    # 背離因子計算
    grp = prices.groupby("stock_id")

    # div_score_top
    price_high20 = grp["close"].transform(lambda x: x.rolling(20, min_periods=10).max())
    rsi_high20 = grp["_rsi"].transform(lambda x: x.rolling(20, min_periods=10).max())
    price_pct_high = (prices["close"] - price_high20) / price_high20
    rsi_pct_high = (prices["_rsi"] - rsi_high20) / rsi_high20.replace(0, np.nan)
    prices["div_score_top"] = price_pct_high - rsi_pct_high

    # div_score_bot
    price_low20 = grp["close"].transform(lambda x: x.rolling(20, min_periods=10).min())
    rsi_low20 = grp["_rsi"].transform(lambda x: x.rolling(20, min_periods=10).min())
    price_pct_low = (prices["close"] - price_low20) / price_low20.replace(0, np.nan)
    rsi_pct_low = (prices["_rsi"] - rsi_low20) / rsi_low20.replace(0, np.nan)
    prices["div_score_bot"] = price_pct_low - rsi_pct_low

    # neg_divergence_avg
    rsi_chg = grp["_rsi"].diff()
    dif_chg = grp["_dif"].diff()
    rsi_corr = prices.groupby("stock_id").apply(
        lambda g: g["_ret"].rolling(20, min_periods=10).corr(rsi_chg.loc[g.index])
    ).reset_index(level=0, drop=True)
    dif_corr = prices.groupby("stock_id").apply(
        lambda g: g["_ret"].rolling(20, min_periods=10).corr(dif_chg.loc[g.index])
    ).reset_index(level=0, drop=True)
    prices["neg_divergence_avg"] = -(rsi_corr.fillna(0) + dif_corr.fillna(0)) / 2

    # 合併至主 df
    div_cols = ["stock_id", "date", "div_score_top", "div_score_bot", "neg_divergence_avg"]
    df = df.merge(prices[div_cols], on=["stock_id", "date"], how="left")

    # 只保留 2023 以後
    df = df[df["date"] >= "2023-01-01"].copy()

    # Forward return
    df = df.sort_values(["stock_id", "date"])
    grp = df.groupby("stock_id")
    df["entry"] = grp["close"].shift(-GAP)
    df["exit"] = grp["close"].shift(-(GAP + HOLD))
    df["fwd_ret"] = (df["exit"] - df["entry"]) / df["entry"]

    df["ym"] = df["date"].dt.to_period("M")

    print(f"[Data] {len(df):,} 筆，{df['stock_id'].nunique()} 檔，"
          f"{df['date'].min().date()} ~ {df['date'].max().date()}")
    return df


# ═══════════════════════════════════════════════════════════════════
# 1. 相關性矩陣
# ═══════════════════════════════════════════════════════════════════
def test_correlation(df: pd.DataFrame) -> None:
    print(f"\n{'='*90}")
    print(f"  1. 背離因子 vs 現有因子相關性（截面 rank 相關）")
    print(f"{'='*90}")

    # 用最近一個月的截面做 rank 相關
    check_factors = BASE_12 + ["price_vs_high20"]
    recent = df[df["date"] >= df["date"].max() - pd.Timedelta(days=60)].copy()

    for div_f in DIV_FACTORS:
        print(f"\n  {div_f}:")
        corrs = []
        for base_f in check_factors:
            valid = recent[[div_f, base_f]].dropna()
            if len(valid) < 100:
                continue
            r, p = stats.spearmanr(valid[div_f], valid[base_f])
            corrs.append((base_f, r, p))
        corrs.sort(key=lambda x: abs(x[1]), reverse=True)
        for base_f, r, p in corrs[:8]:
            flag = " ← 高相關!" if abs(r) > 0.5 else ""
            print(f"    vs {base_f:25s}: ρ={r:+.3f}  p={p:.4f}{flag}")


# ═══════════════════════════════════════════════════════════════════
# 2. Partial IC（控制 baseline 模型預測後的殘差 IC）
# ═══════════════════════════════════════════════════════════════════
def test_partial_ic(df: pd.DataFrame) -> None:
    print(f"\n{'='*90}")
    print(f"  2. Partial IC：控制 12 因子模型後的殘差預測力")
    print(f"     方法：用 12 因子 rank 做 OLS 殘差 → 殘差 vs 背離因子的 Spearman IC")
    print(f"{'='*90}")

    from sklearn.linear_model import LinearRegression

    dates = sorted(df["date"].unique())

    for div_f in DIV_FACTORS:
        daily_raw_ics = []
        daily_partial_ics = []

        for d in dates:
            day = df[df["date"] == d].copy()
            cols_needed = BASE_12 + [div_f, "fwd_ret"]
            day = day.dropna(subset=cols_needed)
            if len(day) < 50:
                continue

            # Rank 因子
            for f in BASE_12:
                day[f"{f}_r"] = day[f].rank(pct=True)
            day[f"{div_f}_r"] = day[div_f].rank(pct=True)

            # Raw IC
            raw_ic, _ = stats.spearmanr(day[f"{div_f}_r"], day["fwd_ret"])
            if np.isnan(raw_ic):
                continue
            daily_raw_ics.append(raw_ic)

            # Partial IC：殘差化
            X = day[[f"{f}_r" for f in BASE_12]].values
            y = day["fwd_ret"].values

            # 從 fwd_ret 中移除 12 因子可解釋的部分
            lr = LinearRegression()
            lr.fit(X, y)
            residual = y - lr.predict(X)

            # 殘差 vs 背離因子的相關
            partial_ic, _ = stats.spearmanr(day[f"{div_f}_r"].values, residual)
            if not np.isnan(partial_ic):
                daily_partial_ics.append(partial_ic)

        if len(daily_raw_ics) < 20:
            print(f"\n  {div_f}: 樣本不足")
            continue

        raw_arr = np.array(daily_raw_ics)
        partial_arr = np.array(daily_partial_ics)

        raw_mean = np.mean(raw_arr)
        partial_mean = np.mean(partial_arr)
        retention = partial_mean / raw_mean * 100 if raw_mean != 0 else 0

        _, raw_p = stats.ttest_1samp(raw_arr, 0)
        _, partial_p = stats.ttest_1samp(partial_arr, 0)

        print(f"\n  {div_f}:")
        print(f"    Raw IC:     {raw_mean:+.4f}  p={raw_p:.4f}")
        print(f"    Partial IC: {partial_mean:+.4f}  p={partial_p:.4f}")
        print(f"    保留率:     {retention:+.0f}%")
        if retention > 50:
            print(f"    → 高度正交，獨立於現有 12 因子 ✓")
        elif retention > 20:
            print(f"    → 部分正交，有邊際貢獻")
        else:
            print(f"    → 大部分被現有因子覆蓋 ✗")


# ═══════════════════════════════════════════════════════════════════
# 3. ML Walk-Forward：12 因子 vs 12+背離
# ═══════════════════════════════════════════════════════════════════
def train_models(train: pd.DataFrame, factors: List[str]):
    t = train.dropna(subset=factors + ["fwd_ret"]).copy()
    if len(t) < 500:
        return None

    rank_cols = []
    for f in factors:
        rc = f"{f}_r"
        t[rc] = t.groupby("date")[f].rank(pct=True)
        rank_cols.append(rc)

    X = t[rank_cols].values
    y_cls = (t["fwd_ret"] > t["fwd_ret"].median()).astype(int).values

    clf = HistGradientBoostingClassifier(max_iter=150, max_depth=4, random_state=42)
    reg = HistGradientBoostingRegressor(max_iter=150, max_depth=4, random_state=42)
    clf.fit(X, y_cls)
    reg.fit(X, t["fwd_ret"].values)

    return clf, reg, rank_cols


def predict_day(clf, reg, rank_cols, factors, day_data):
    s = day_data.dropna(subset=factors).copy()
    if len(s) < 50:
        return None

    for f, rc in zip(factors, rank_cols):
        s[rc] = s[f].rank(pct=True)

    X = s[rank_cols].values
    score = clf.predict_proba(X)[:, 1] * 0.5 + \
            pd.Series(reg.predict(X)).rank(pct=True).values * 0.5
    return pd.Series(score, index=s.index)


def test_ml_walkforward(df: pd.DataFrame) -> None:
    print(f"\n{'='*90}")
    print(f"  3. ML Walk-Forward：12 因子 baseline vs 12+背離因子")
    print(f"     每月訓練 → 每日 OOS IC/L-S")
    print(f"{'='*90}")

    strategies: Dict[str, List[str]] = {
        "A_base12": BASE_12,
        "B_+div_top": BASE_12 + ["div_score_top"],
        "C_+div_bot": BASE_12 + ["div_score_bot"],
        "D_+neg_div_avg": BASE_12 + ["neg_divergence_avg"],
        "E_+all3": BASE_12 + DIV_FACTORS,
        "F_+top+bot": BASE_12 + ["div_score_top", "div_score_bot"],
    }

    months = sorted(df["ym"].unique())
    results: Dict[str, List[dict]] = {name: [] for name in strategies}

    test_start = TRAIN_MONTHS
    n_test = len(months) - test_start
    print(f"  測試窗口: {n_test} 個月\n")

    for i in range(test_start, len(months)):
        test_month = months[i]
        train_months = months[i - TRAIN_MONTHS:i]

        train = df[df["ym"].isin(train_months)].copy()
        test = df[df["ym"] == test_month].copy()
        test_dates = sorted(test["date"].unique())
        if not test_dates:
            continue

        print(f"  {test_month}: {len(test_dates)} 交易日", end="", flush=True)

        for strat_name, factors in strategies.items():
            models = train_models(train, factors)
            if models is None:
                continue
            clf, reg, rank_cols = models

            daily_ics = []
            daily_tops = []
            daily_bots = []

            for td in test_dates:
                day_data = test[test["date"] == td].copy()
                if len(day_data) < 100:
                    continue

                scores = predict_day(clf, reg, rank_cols, factors, day_data)
                if scores is None:
                    continue

                day_data.loc[scores.index, "score"] = scores
                valid = day_data.dropna(subset=["score", "fwd_ret"])
                if len(valid) < 50:
                    continue

                ic, _ = stats.spearmanr(valid["score"], valid["fwd_ret"])
                if np.isnan(ic):
                    continue
                daily_ics.append(ic)

                # Top/Bottom 10%
                top = valid[valid["score"] >= valid["score"].quantile(0.9)]
                bot = valid[valid["score"] <= valid["score"].quantile(0.1)]
                if len(top) >= 3 and len(bot) >= 3:
                    daily_tops.append(top["fwd_ret"].mean())
                    daily_bots.append(bot["fwd_ret"].mean())

            if daily_ics:
                results[strat_name].append({
                    "month": str(test_month),
                    "ic": np.mean(daily_ics),
                    "top": np.mean(daily_tops) if daily_tops else np.nan,
                    "bot": np.mean(daily_bots) if daily_bots else np.nan,
                    "n_days": len(daily_ics),
                })

        print()

    # 輸出結果
    print(f"\n{'='*90}")
    print(f"  ML Walk-Forward 結果摘要")
    print(f"{'='*90}")
    print(f"\n  {'策略':<20s} {'IC':>8s} {'IC p值':>10s} {'Top10%':>9s} "
          f"{'Bot10%':>9s} {'L-S':>9s} {'L-S+%':>7s}")
    print(f"  {'-'*75}")

    baseline_ic = None
    for strat_name in strategies:
        rows = results[strat_name]
        if not rows:
            continue
        rdf = pd.DataFrame(rows)
        ic_mean = rdf["ic"].mean()
        ics = rdf["ic"].dropna().values
        _, ic_p = stats.ttest_1samp(ics, 0) if len(ics) >= 5 else (np.nan, np.nan)
        top_mean = rdf["top"].mean() * 100
        bot_mean = rdf["bot"].mean() * 100
        ls = top_mean - bot_mean
        ls_pos = np.mean(rdf["top"].values - rdf["bot"].values > 0) * 100

        if strat_name == "A_base12":
            baseline_ic = ic_mean

        delta = ""
        if baseline_ic is not None and strat_name != "A_base12":
            d = (ic_mean - baseline_ic) / baseline_ic * 100
            delta = f" (Δ{d:+.1f}%)"

        print(f"  {strat_name:<20s} {ic_mean:>+8.4f} {ic_p:>10.4f} "
              f"{top_mean:>+8.2f}% {bot_mean:>+8.2f}% {ls:>+8.2f}% {ls_pos:>6.0f}%{delta}")

    # 分年度
    print(f"\n  分年度 IC:")
    for strat_name in ["A_base12", "E_+all3", "F_+top+bot"]:
        rows = results.get(strat_name, [])
        if not rows:
            continue
        rdf = pd.DataFrame(rows)
        rdf["year"] = rdf["month"].str[:4]
        print(f"\n  {strat_name}:")
        for yr in sorted(rdf["year"].unique()):
            yr_data = rdf[rdf["year"] == yr]
            ic_m = yr_data["ic"].mean()
            top_m = yr_data["top"].mean() * 100
            bot_m = yr_data["bot"].mean() * 100
            print(f"    {yr}: IC={ic_m:+.4f}  Top={top_m:+.2f}%  Bot={bot_m:+.2f}%  "
                  f"L-S={top_m-bot_m:+.2f}%")

    # 統計檢驗：baseline vs best
    print(f"\n  Paired t-test (baseline vs best):")
    base_rows = results.get("A_base12", [])
    for strat_name in ["B_+div_top", "C_+div_bot", "D_+neg_div_avg", "E_+all3", "F_+top+bot"]:
        alt_rows = results.get(strat_name, [])
        if not base_rows or not alt_rows:
            continue
        bdf = pd.DataFrame(base_rows).set_index("month")
        adf = pd.DataFrame(alt_rows).set_index("month")
        common = bdf.index.intersection(adf.index)
        if len(common) < 5:
            continue
        diff = adf.loc[common, "ic"].values - bdf.loc[common, "ic"].values
        t, p = stats.ttest_1samp(diff, 0)
        mean_diff = np.mean(diff)
        print(f"    {strat_name:20s} vs baseline: ΔIC={mean_diff:+.4f}  t={t:.2f}  p={p:.4f}")


def main() -> None:
    print("=" * 90)
    print("  背離因子 Partial IC + ML Walk-Forward 驗證")
    print("=" * 90)

    df = load_data()

    test_correlation(df)
    test_partial_ic(df)
    test_ml_walkforward(df)

    print(f"\n{'='*90}")
    print(f"  研究完成")
    print(f"{'='*90}")


if __name__ == "__main__":
    main()

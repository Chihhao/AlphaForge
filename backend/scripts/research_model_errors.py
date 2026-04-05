"""
模型錯誤分析：找出現有 9 因子模型的盲點

方法：
1. 重建 walk-forward 預測（和現有模型相同邏輯）
2. 把每月推薦的 Top10% 分成「選對」（報酬>0）和「選錯」（報酬<0）
3. 比較兩組在「非模型因子」上的差異 → 找出缺失因子
4. 同時分析 Bot10%（預測差但實際漲的）→ 找出遺漏的 alpha

分析維度：
- 產業分佈
- 市值大小
- 融資融券 (margin_chg_5d)
- 技術指標 (RSI, 乖離率)
- 波動率 (ATR)
- 近期動量
- 季節性（月份）
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

TRAINING_FACTORS = [
    "roe", "yield_rate", "pb_ratio", "revenue_yoy",
    "rev_surprise", "rev_accel",
    "foreign_hold_chg_5d", "dealer_buy_20d", "vol_ratio",
]

# 非模型因子（候選診斷用）
DIAGNOSTIC_FACTORS = [
    "margin_chg_5d", "rsi14", "rsi2", "bias5", "bias20",
    "bb_pctb", "atr_pct", "ma_trend", "price_vs_high20",
    "foreign_net_buy", "foreign_buy_5d", "trust_net_buy", "trust_buy_5d",
]

HOLD = 20
GAP = 1


def load_data() -> pd.DataFrame:
    all_cols = (
        ["stock_id", "date", "close", "ma60", "volume"]
        + TRAINING_FACTORS
        + DIAGNOSTIC_FACTORS
    )
    # deduplicate
    all_cols = list(dict.fromkeys(all_cols))

    sql = text(f"""
        SELECT {', '.join(all_cols)}
        FROM stock_features
        WHERE close > 0 AND date >= '2023-06-01'
        ORDER BY date, stock_id
    """)
    df = pd.read_sql(sql, engine)
    df["date"] = pd.to_datetime(df["date"])
    return df


def load_sectors() -> Dict[str, str]:
    """載入股票產業分類"""
    sql = text("SELECT stock_id, industry FROM stocks WHERE industry IS NOT NULL")
    df = pd.read_sql(sql, engine)
    return dict(zip(df["stock_id"], df["industry"]))


def run_walkforward_and_diagnose(df: pd.DataFrame, sectors: Dict[str, str]) -> None:
    dates = sorted(df["date"].unique())

    # 建立月度窗口
    df["ym"] = df["date"].dt.to_period("M")
    months = sorted(df["ym"].unique())

    # 訓練期 12 個月，測試 1 個月
    TRAIN_MONTHS = 12
    results: List[dict] = []

    print(f"\n走 Walk-Forward（{TRAIN_MONTHS}m train → 1m test）...\n")

    for i in range(TRAIN_MONTHS, len(months)):
        test_month = months[i]
        train_months = months[i - TRAIN_MONTHS:i]

        train = df[df["ym"].isin(train_months)].copy()
        test = df[df["ym"] == test_month].copy()

        if len(train) < 1000 or len(test) < 200:
            continue

        # 計算 forward return
        for subset in [train, test]:
            subset["entry"] = subset.groupby("stock_id")["close"].shift(-GAP)
            subset["exit"] = subset.groupby("stock_id")["close"].shift(-(GAP + HOLD))
            subset["fwd_ret"] = (subset["exit"] - subset["entry"]) / subset["entry"]

        train = train.dropna(subset=["fwd_ret"] + TRAINING_FACTORS)
        test = test.dropna(subset=["fwd_ret"] + TRAINING_FACTORS)

        if len(train) < 500 or len(test) < 100:
            continue

        # 訓練 rank
        for f in TRAINING_FACTORS:
            train[f"{f}_r"] = train.groupby("date")[f].rank(pct=True)
            test[f"{f}_r"] = test.groupby("date")[f].rank(pct=True)

        rank_cols = [f"{f}_r" for f in TRAINING_FACTORS]
        X_train = train[rank_cols].values
        X_test = test[rank_cols].values

        # 二分類：報酬>中位數 = 1
        median_ret = train["fwd_ret"].median()
        y_train = (train["fwd_ret"] > median_ret).astype(int).values

        # Ensemble
        clf = HistGradientBoostingClassifier(max_iter=200, max_depth=4, random_state=42)
        reg = HistGradientBoostingRegressor(max_iter=200, max_depth=4, random_state=42)
        clf.fit(X_train, y_train)
        reg.fit(X_train, train["fwd_ret"].values)

        test["score"] = clf.predict_proba(X_test)[:, 1] * 0.5 + \
                        pd.Series(reg.predict(X_test)).rank(pct=True).values * 0.5

        # 取最後一天的截面（每月推薦）
        last_date = test["date"].max()
        snapshot = test[test["date"] == last_date].copy()

        if len(snapshot) < 50:
            continue

        snapshot["rank"] = snapshot["score"].rank(pct=True)
        snapshot["sector"] = snapshot["stock_id"].map(sectors).fillna("unknown")

        # 動量（非模型因子，診斷用）
        snapshot["momentum_20d"] = snapshot.groupby("stock_id").apply(
            lambda x: x["close"].pct_change(20)
        ).values if False else np.nan  # 簡化：用 price_vs_high20 代替

        # 市值 proxy（close * volume 的近似）
        snapshot["size_proxy"] = np.log(snapshot["close"] * snapshot["volume"].clip(lower=1))

        # Top10% / Bot10%
        top10 = snapshot[snapshot["rank"] >= 0.9].copy()
        bot10 = snapshot[snapshot["rank"] <= 0.1].copy()
        mid = snapshot[(snapshot["rank"] > 0.3) & (snapshot["rank"] < 0.7)].copy()

        # Top10% 中區分選對/選錯
        if len(top10) > 0:
            top_right = top10[top10["fwd_ret"] > 0]
            top_wrong = top10[top10["fwd_ret"] <= 0]

            for _, row in top10.iterrows():
                rec = {
                    "ym": str(test_month),
                    "stock_id": row["stock_id"],
                    "score": row["score"],
                    "fwd_ret": row["fwd_ret"],
                    "group": "top10",
                    "correct": row["fwd_ret"] > 0,
                    "sector": row.get("sector", "unknown"),
                    "size_proxy": row.get("size_proxy"),
                }
                for f in DIAGNOSTIC_FACTORS:
                    if f in row.index:
                        rec[f] = row[f]
                results.append(rec)

        # Bot10% 中找「遺珠」
        if len(bot10) > 0:
            for _, row in bot10.iterrows():
                rec = {
                    "ym": str(test_month),
                    "stock_id": row["stock_id"],
                    "score": row["score"],
                    "fwd_ret": row["fwd_ret"],
                    "group": "bot10",
                    "correct": row["fwd_ret"] <= 0,  # bot10 預測差，真的差才對
                    "sector": row.get("sector", "unknown"),
                    "size_proxy": row.get("size_proxy"),
                }
                for f in DIAGNOSTIC_FACTORS:
                    if f in row.index:
                        rec[f] = row[f]
                results.append(rec)

    if not results:
        print("No results!")
        return

    rdf = pd.DataFrame(results)
    print(f"收集 {len(rdf):,} 筆預測記錄")

    # ════════════════════════════════════════════════════════════
    #  分析 1：Top10% 選對 vs 選錯的因子差異
    # ════════════════════════════════════════════════════════════
    top = rdf[rdf["group"] == "top10"]
    right = top[top["correct"] == True]
    wrong = top[top["correct"] == False]

    print(f"\n{'=' * 100}")
    print(f"  分析 1：Top10% 選對 vs 選錯")
    print(f"  選對: {len(right)} ({len(right)/len(top):.0%}) | 選錯: {len(wrong)} ({len(wrong)/len(top):.0%})")
    print(f"{'=' * 100}")

    print(f"\n  {'因子':>20} {'選對均值':>10} {'選錯均值':>10} {'差異':>10} {'t-stat':>8} {'p-val':>8} {'意義':>15}")
    print("  " + "─" * 90)

    significant_factors = []
    for f in DIAGNOSTIC_FACTORS:
        if f not in rdf.columns:
            continue
        r_vals = right[f].dropna()
        w_vals = wrong[f].dropna()
        if len(r_vals) < 20 or len(w_vals) < 20:
            continue

        r_mean = r_vals.mean()
        w_mean = w_vals.mean()
        diff = r_mean - w_mean

        t, p = stats.ttest_ind(r_vals, w_vals, equal_var=False)

        if p < 0.05:
            sig = "★★ 顯著"
            significant_factors.append((f, diff, t, p))
        elif p < 0.1:
            sig = "★ 邊際"
        else:
            sig = ""

        print(f"  {f:>20} {r_mean:>+10.3f} {w_mean:>+10.3f} {diff:>+10.3f}"
              f" {t:>8.2f} {p:>8.4f} {sig:>15}")

    # ════════════════════════════════════════════════════════════
    #  分析 2：Bot10% 遺珠（模型預測差但實際漲很多的）
    # ════════════════════════════════════════════════════════════
    bot = rdf[rdf["group"] == "bot10"]
    missed_gems = bot[bot["fwd_ret"] > bot["fwd_ret"].quantile(0.75)]  # Bot10%中報酬最高的25%

    print(f"\n{'=' * 100}")
    print(f"  分析 2：Bot10% 遺珠（模型認為差但實際報酬高的股票）")
    print(f"  遺珠: {len(missed_gems)} 筆 | 平均報酬: {missed_gems['fwd_ret'].mean()*100:+.2f}%")
    print(f"{'=' * 100}")

    print(f"\n  遺珠 vs Bot10% 其他，各因子差異:")
    bot_rest = bot[~bot.index.isin(missed_gems.index)]

    print(f"  {'因子':>20} {'遺珠均值':>10} {'其他均值':>10} {'差異':>10} {'t-stat':>8} {'p-val':>8}")
    print("  " + "─" * 75)

    for f in DIAGNOSTIC_FACTORS:
        if f not in rdf.columns:
            continue
        g_vals = missed_gems[f].dropna()
        o_vals = bot_rest[f].dropna()
        if len(g_vals) < 10 or len(o_vals) < 10:
            continue

        g_mean = g_vals.mean()
        o_mean = o_vals.mean()
        diff = g_mean - o_mean
        t, p = stats.ttest_ind(g_vals, o_vals, equal_var=False)

        sig = " ★★" if p < 0.05 else " ★" if p < 0.1 else ""
        print(f"  {f:>20} {g_mean:>+10.3f} {o_mean:>+10.3f} {diff:>+10.3f}"
              f" {t:>8.2f} {p:>8.4f}{sig}")

    # ════════════════════════════════════════════════════════════
    #  分析 3：產業分佈
    # ════════════════════════════════════════════════════════════
    print(f"\n{'=' * 100}")
    print(f"  分析 3：錯誤的產業分佈")
    print(f"{'=' * 100}")

    top_sectors = top.groupby(["sector", "correct"]).size().unstack(fill_value=0)
    if True in top_sectors.columns and False in top_sectors.columns:
        top_sectors["total"] = top_sectors[True] + top_sectors[False]
        top_sectors["error_rate"] = top_sectors[False] / top_sectors["total"]
        top_sectors = top_sectors.sort_values("error_rate", ascending=False)

        print(f"\n  {'產業':>15} {'選對':>6} {'選錯':>6} {'錯誤率':>8} {'判定':>10}")
        print("  " + "─" * 50)
        for sector, row in top_sectors.iterrows():
            if row["total"] < 10:
                continue
            err_rate = row["error_rate"]
            verdict = "⚠ 高錯誤" if err_rate > 0.5 else ""
            print(f"  {str(sector)[:15]:>15} {row[True]:>6.0f} {row[False]:>6.0f}"
                  f" {err_rate:>7.0%} {verdict:>10}")

    # ════════════════════════════════════════════════════════════
    #  分析 4：月份分佈
    # ════════════════════════════════════════════════════════════
    print(f"\n{'=' * 100}")
    print(f"  分析 4：錯誤的月份分佈")
    print(f"{'=' * 100}")

    top["month"] = top["ym"].apply(lambda x: int(x.split("-")[1]))
    month_stats = top.groupby("month").agg(
        total=("correct", "count"),
        right=("correct", "sum"),
    )
    month_stats["error_rate"] = 1 - month_stats["right"] / month_stats["total"]

    print(f"\n  {'月':>4} {'選對':>6} {'選錯':>6} {'錯誤率':>8}")
    print("  " + "─" * 30)
    for m, row in month_stats.iterrows():
        print(f"  {m:>4} {row['right']:>6.0f} {row['total']-row['right']:>6.0f}"
              f" {row['error_rate']:>7.0%}")

    # ════════════════════════════════════════════════════════════
    #  結論
    # ════════════════════════════════════════════════════════════
    print(f"\n{'=' * 100}")
    print(f"  結論：模型的盲點在哪裡？")
    print(f"{'=' * 100}")

    if significant_factors:
        print(f"\n  顯著差異因子（p < 0.05）：")
        for f, diff, t, p in significant_factors:
            direction = "選對組較高" if diff > 0 else "選對組較低"
            print(f"    {f}: {direction}（差異={diff:+.3f}, t={t:.2f}, p={p:.4f}）")
            if diff > 0:
                print(f"      → 加入模型可能改善：{f} 高 → 預測更準")
            else:
                print(f"      → 加入模型可能改善：{f} 低（或取反）→ 預測更準")
    else:
        print(f"\n  沒有發現顯著的遺漏因子（可能模型已捕捉大部分可用資訊）")


def main() -> None:
    print("=== 模型錯誤分析 ===\n")

    print("Loading data...")
    df = load_data()
    print(f"  {len(df):,} rows, {df['date'].min().date()} ~ {df['date'].max().date()}")

    print("Loading sectors...")
    sectors = load_sectors()
    print(f"  {len(sectors)} stocks with sector info")

    run_walkforward_and_diagnose(df, sectors)


if __name__ == "__main__":
    main()

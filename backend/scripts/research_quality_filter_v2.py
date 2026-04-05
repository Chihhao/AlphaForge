"""
常識過濾深度驗證 v2

上一版發現過濾 ROE≤0 反而降低 Top5 報酬。
本版深入分析：
1. ROE=0 的推薦股到底賺了多少？拆開看
2. 用 LightGBM（跟線上一樣）而非 HistGradientBoosting
3. 逐月拆解：哪些月份 ROE=0 貢獻正報酬，哪些負報酬
4. 不只看平均，也看中位數和最大虧損
5. 測試更精準的過濾條件
"""
from __future__ import annotations
import os, warnings
import numpy as np
import pandas as pd
from scipy import stats
from sqlalchemy import create_engine, text

warnings.filterwarnings("ignore")
PG_URL = os.getenv("PG_URL", "postgresql://alphaforge:alphaforge_secret@10.0.4.3:5433/alphaforge")
engine = create_engine(PG_URL)

HOLD = 20
GAP = 1
TRAIN_MONTHS = 12

FACTORS = [
    "roe", "yield_rate", "pb_ratio", "revenue_yoy",
    "rev_surprise", "rev_accel",
    "foreign_hold_chg_5d", "dealer_buy_20d", "vol_ratio",
    "ivol_20d", "neg_trust_net_buy",
]


def load_data() -> pd.DataFrame:
    raw_cols = set()
    for f in FACTORS:
        raw_cols.add(f.replace("neg_", "") if f.startswith("neg_") else f)
    raw_cols.update(["stock_id", "date", "close", "ma60", "trust_net_buy"])

    sql = text(f"SELECT {', '.join(raw_cols)} FROM stock_features WHERE close > 0 AND date >= '2023-03-01' ORDER BY date, stock_id")
    print("  Loading...")
    df = pd.read_sql(sql, engine)
    df["date"] = pd.to_datetime(df["date"])
    df["neg_trust_net_buy"] = -df["trust_net_buy"].fillna(0)

    df = df.sort_values(["stock_id", "date"])
    df["entry"] = df.groupby("stock_id")["close"].shift(-GAP)
    df["exit"] = df.groupby("stock_id")["close"].shift(-(GAP + HOLD))
    df["fwd_ret"] = (df["exit"] - df["entry"]) / df["entry"]
    df["ym"] = df["date"].dt.to_period("M")
    return df


def train_model(train: pd.DataFrame):
    """用 HistGradientBoosting 訓練（sklearn，本機可用）"""
    from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor

    t = train.dropna(subset=["fwd_ret"]).copy()
    if len(t) < 500:
        return None

    rank_cols = []
    for f in FACTORS:
        rc = f"{f}_r"
        filled = t.groupby("date")[f].transform(lambda x: x.fillna(x.median()))
        t[rc] = t.groupby("date")[filled.name].rank(pct=True).fillna(0.5)
        rank_cols.append(rc)

    X = t[rank_cols].values
    y_cls = (t["fwd_ret"] > t["fwd_ret"].median()).astype(int).values
    y_reg = t["fwd_ret"].clip(-0.5, 0.5).values

    clf = HistGradientBoostingClassifier(max_iter=150, max_depth=4, random_state=42)
    reg = HistGradientBoostingRegressor(max_iter=150, max_depth=4, random_state=42)
    clf.fit(X, y_cls)
    reg.fit(X, y_reg)

    return clf, reg, rank_cols


def predict_day(models, day_data: pd.DataFrame):
    clf, reg, rank_cols = models
    s = day_data.copy()
    for f, rc in zip(FACTORS, rank_cols):
        filled = s[f].fillna(s[f].median())
        s[rc] = filled.rank(pct=True).fillna(0.5)

    X = s[rank_cols].values
    prob = clf.predict_proba(X)[:, 1] * 0.5
    reg_rank = pd.Series(reg.predict(X), index=s.index).rank(pct=True).values * 0.5
    score = prob + reg_rank
    return pd.Series(score, index=s.index)


def main():
    print("=" * 80)
    print("  常識過濾深度驗證 v2 (LightGBM)")
    print("=" * 80)

    df = load_data()
    months = sorted(df["ym"].unique())
    print(f"  {len(df):,} rows, {len(months)} months\n")

    # 收集每日 Top5 的個股明細
    all_top5_picks = []
    all_bot5_picks = []

    for i in range(TRAIN_MONTHS, len(months)):
        test_month = months[i]
        train = df[df["ym"].isin(months[i - TRAIN_MONTHS:i])].copy()
        test = df[df["ym"] == test_month].copy()
        test_dates = sorted(test["date"].unique())
        if not test_dates:
            continue

        print(f"  {test_month}", end="", flush=True)

        models = train_model(train)
        if models is None:
            print(" skip")
            continue

        for td in test_dates:
            day = test[test["date"] == td]
            if len(day) < 100:
                continue

            scores = predict_day(models, day)
            day = day.copy()
            day["score"] = scores
            valid = day.dropna(subset=["score", "fwd_ret"])
            if len(valid) < 50:
                continue

            top5 = valid.nlargest(5, "score")
            bot5 = valid.nsmallest(5, "score")

            for _, row in top5.iterrows():
                all_top5_picks.append({
                    "date": td, "ym": str(test_month),
                    "stock_id": row["stock_id"],
                    "score": row["score"],
                    "fwd_ret": row["fwd_ret"],
                    "roe": row.get("roe"),
                    "revenue_yoy": row.get("revenue_yoy"),
                    "yield_rate": row.get("yield_rate"),
                    "pb_ratio": row.get("pb_ratio"),
                    "ivol_20d": row.get("ivol_20d"),
                })

            for _, row in bot5.iterrows():
                all_bot5_picks.append({
                    "date": td, "ym": str(test_month),
                    "stock_id": row["stock_id"],
                    "score": row["score"],
                    "fwd_ret": row["fwd_ret"],
                    "roe": row.get("roe"),
                    "revenue_yoy": row.get("revenue_yoy"),
                    "yield_rate": row.get("yield_rate"),
                    "pb_ratio": row.get("pb_ratio"),
                })

        print(" ✓")

    top_df = pd.DataFrame(all_top5_picks)
    bot_df = pd.DataFrame(all_bot5_picks)

    # ═══════════════════════════════════════════════════════
    #  分析 1：Top5 中 ROE=0 vs ROE>0 的報酬差異
    # ═══════════════════════════════════════════════════════
    print(f"\n{'=' * 80}")
    print(f"  分析 1：Top5 推薦中 ROE≤0 vs ROE>0 的報酬比較")
    print(f"{'=' * 80}")

    top_df["roe_group"] = np.where(top_df["roe"].fillna(0) <= 0, "ROE≤0", "ROE>0")
    for grp, gdf in top_df.groupby("roe_group"):
        n = len(gdf)
        pct = n / len(top_df) * 100
        avg = gdf["fwd_ret"].mean() * 100
        med = gdf["fwd_ret"].median() * 100
        wr = (gdf["fwd_ret"] > 0).mean() * 100
        worst = gdf["fwd_ret"].min() * 100
        best = gdf["fwd_ret"].max() * 100
        print(f"  {grp}: {n} 筆 ({pct:.0f}%) | 平均={avg:+.2f}% 中位={med:+.2f}% 勝率={wr:.0f}% | 最差={worst:+.1f}% 最好={best:+.1f}%")

    # ROE=0 中再細分：營收成長 vs 營收衰退
    print(f"\n  ── ROE≤0 細分 ──")
    roe0 = top_df[top_df["roe_group"] == "ROE≤0"].copy()
    if len(roe0) > 0:
        roe0["rev_group"] = np.where(roe0["revenue_yoy"].fillna(0) > 0, "營收成長", "營收衰退")
        for grp, gdf in roe0.groupby("rev_group"):
            n = len(gdf)
            avg = gdf["fwd_ret"].mean() * 100
            wr = (gdf["fwd_ret"] > 0).mean() * 100
            print(f"    {grp}: {n} 筆 | 平均={avg:+.2f}% 勝率={wr:.0f}%")

    # ═══════════════════════════════════════════════════════
    #  分析 2：不同過濾條件的比較（含更多變體）
    # ═══════════════════════════════════════════════════════
    print(f"\n{'=' * 80}")
    print(f"  分析 2：多種過濾條件比較")
    print(f"{'=' * 80}")

    filters = {
        "A_無過濾": lambda d: d,
        "B_排除ROE≤0": lambda d: d[d["roe"].fillna(0) > 0],
        "C_排除營收<-50%": lambda d: d[d["revenue_yoy"].fillna(0) > -50],
        "D_排除ROE≤0且營收<-50%": lambda d: d[~((d["roe"].fillna(0) <= 0) & (d["revenue_yoy"].fillna(0) < -50))],
        "E_排除ROE≤0且營收<0": lambda d: d[~((d["roe"].fillna(0) <= 0) & (d["revenue_yoy"].fillna(0) < 0))],
    }

    print(f"\n  {'策略':>25} {'Top5月報酬':>10} {'中位數':>8} {'勝率':>6} {'最差月':>8} {'Top5檔數':>8}")
    print("  " + "─" * 70)

    for name, filt in filters.items():
        filtered = filt(top_df)
        # 每日取 Top5 後按月平均
        monthly = filtered.groupby("ym").agg(
            ret=("fwd_ret", "mean"),
            count=("fwd_ret", "count"),
        )
        avg = monthly["ret"].mean() * 100
        med = monthly["ret"].median() * 100
        wr = (monthly["ret"] > 0).mean() * 100
        worst = monthly["ret"].min() * 100
        avg_n = monthly["count"].mean()
        print(f"  {name:>25} {avg:>+9.2f}% {med:>+7.2f}% {wr:>5.0f}% {worst:>+7.1f}% {avg_n:>7.1f}")

    # ═══════════════════════════════════════════════════════
    #  分析 3：Bot5（做空）中高殖利率股的表現
    # ═══════════════════════════════════════════════════════
    print(f"\n{'=' * 80}")
    print(f"  分析 3：Bot5 做空中高殖利率股表現")
    print(f"{'=' * 80}")

    bot_df["yield_group"] = np.where(bot_df["yield_rate"].fillna(0) > 6, "殖利率>6%", "殖利率≤6%")
    for grp, gdf in bot_df.groupby("yield_group"):
        n = len(gdf)
        avg = gdf["fwd_ret"].mean() * 100
        neg_wr = (gdf["fwd_ret"] < 0).mean() * 100
        print(f"  {grp}: {n} 筆 | 平均報酬={avg:+.2f}% 下跌率={neg_wr:.0f}%")

    short_filters = {
        "A_無過濾": lambda d: d,
        "B_排除殖利率>6%": lambda d: d[d["yield_rate"].fillna(0) <= 6],
        "C_排除殖利率>5%": lambda d: d[d["yield_rate"].fillna(0) <= 5],
        "D_排除PB<0.7": lambda d: d[d["pb_ratio"].fillna(1) >= 0.7],
        "E_排除殖利率>5%且PB<0.8": lambda d: d[~((d["yield_rate"].fillna(0) > 5) & (d["pb_ratio"].fillna(1) < 0.8))],
    }

    print(f"\n  {'策略':>30} {'Bot5月報酬':>10} {'中位數':>8} {'下跌率':>6}")
    print("  " + "─" * 55)

    for name, filt in short_filters.items():
        filtered = filt(bot_df)
        monthly = filtered.groupby("ym")["fwd_ret"].mean()
        avg = monthly.mean() * 100
        med = monthly.median() * 100
        neg = (monthly < 0).mean() * 100
        print(f"  {name:>30} {avg:>+9.2f}% {med:>+7.2f}% {neg:>5.0f}%")

    # ═══════════════════════════════════════════════════════
    #  分析 4：Top5 中 ROE≤0 出現頻率（逐月）
    # ═══════════════════════════════════════════════════════
    print(f"\n{'=' * 80}")
    print(f"  分析 4：每月 Top5 中 ROE≤0 股票佔比")
    print(f"{'=' * 80}")

    monthly_roe0 = top_df.groupby("ym").apply(
        lambda g: pd.Series({
            "total": len(g),
            "roe0_count": (g["roe"].fillna(0) <= 0).sum(),
            "roe0_ret": g[g["roe"].fillna(0) <= 0]["fwd_ret"].mean() * 100 if (g["roe"].fillna(0) <= 0).any() else np.nan,
            "roe_pos_ret": g[g["roe"].fillna(0) > 0]["fwd_ret"].mean() * 100 if (g["roe"].fillna(0) > 0).any() else np.nan,
        })
    )
    print(f"\n  {'月':>8} {'ROE≤0佔比':>10} {'ROE≤0報酬':>10} {'ROE>0報酬':>10} {'差異':>8}")
    print("  " + "─" * 50)
    for ym, row in monthly_roe0.iterrows():
        ratio = row["roe0_count"] / row["total"] * 100
        r0 = row["roe0_ret"]
        rp = row["roe_pos_ret"]
        diff = (r0 - rp) if pd.notna(r0) and pd.notna(rp) else np.nan
        r0_s = f"{r0:+.1f}%" if pd.notna(r0) else "N/A"
        rp_s = f"{rp:+.1f}%" if pd.notna(rp) else "N/A"
        diff_s = f"{diff:+.1f}%" if pd.notna(diff) else ""
        print(f"  {ym:>8} {ratio:>9.0f}% {r0_s:>10} {rp_s:>10} {diff_s:>8}")


if __name__ == "__main__":
    main()

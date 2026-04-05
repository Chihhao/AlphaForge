"""
跨市場 Timing Overlay 研究
==========================
Part 1 發現美股隔夜→台股次日 r=0.40（極強），但橫截面 IC 歸零。
→ 美股是「市場方向」訊號，不是「選股」訊號。

本腳本測試：能否用美股方向作為 overlay 來增強現有 20d 模型的表現？

策略假說：
  A. Regime-Split: 美股漲→只做多推薦有效 / 美股跌→只做空推薦有效
  B. Timing Overlay: 根據美股強弱調整做多/做空的權重
  C. Conditional IC: 模型在不同 US regime 下的 IC 是否有差異？
  D. 20d 累積美股動量：用來判斷市場趨勢，調整整體曝險

使用: cd backend && ./.venv/bin/python scripts/research_cross_market_timing.py
"""
from __future__ import annotations

import os
import warnings

import numpy as np
import pandas as pd
from scipy import stats
from sqlalchemy import create_engine, text

warnings.filterwarnings("ignore")

PG_URL = os.getenv(
    "PG_URL",
    "postgresql://alphaforge:alphaforge_secret@10.0.4.3:5433/alphaforge",
)
engine = create_engine(PG_URL)
HOLD, GAP = 20, 1


def load_data():
    """載入台股價格 + 全球指數 + features"""
    print("載入資料 ...", flush=True)

    tw = pd.read_sql(text("""
        SELECT stock_id, date, close, volume
        FROM stock_prices WHERE date >= '2023-04-01' AND close > 0 AND volume > 0
        ORDER BY stock_id, date
    """), engine)
    tw["date"] = pd.to_datetime(tw["date"])

    us = pd.read_sql(text("""
        SELECT index_id, date, close, change_pct FROM global_index ORDER BY index_id, date
    """), engine)
    us["date"] = pd.to_datetime(us["date"])

    feat = pd.read_sql(text("""
        SELECT stock_id, date, roe, yield_rate, pb_ratio, revenue_yoy,
               rev_surprise, rev_accel, foreign_hold_chg_5d, dealer_buy_20d,
               vol_ratio, ivol_20d, trust_net_buy
        FROM stock_features WHERE date >= '2023-06-01'
        ORDER BY stock_id, date
    """), engine)
    feat["date"] = pd.to_datetime(feat["date"])

    print(f"  台股: {len(tw):,} 筆, 指數: {len(us):,} 筆, Features: {len(feat):,} 筆")
    return tw, us, feat


def align_us(tw_dates, us_df):
    """台股日期 → 最近美股交易日"""
    pivot = us_df.pivot_table(index="date", columns="index_id", values="change_pct")
    close_pivot = us_df.pivot_table(index="date", columns="index_id", values="close")
    us_dates = sorted(pivot.index)

    mapping = []
    us_idx = 0
    for tw_d in sorted(tw_dates.unique()):
        while us_idx < len(us_dates) - 1 and us_dates[us_idx + 1] < tw_d:
            us_idx += 1
        if us_dates[us_idx] >= tw_d:
            tmp = us_idx
            while tmp > 0 and us_dates[tmp] >= tw_d:
                tmp -= 1
            if us_dates[tmp] >= tw_d:
                continue
            us_idx = tmp

        us_d = us_dates[us_idx]
        row = {"tw_date": tw_d, "us_date": us_d}
        for idx_id in ["sp500", "nasdaq", "sox", "vix"]:
            if idx_id in pivot.columns:
                row[f"{idx_id}_ret"] = pivot.loc[us_d, idx_id] if us_d in pivot.index else np.nan
            if idx_id in close_pivot.columns:
                row[f"{idx_id}_close"] = close_pivot.loc[us_d, idx_id] if us_d in close_pivot.index else np.nan
        mapping.append(row)
    return pd.DataFrame(mapping)


def simulate_model_ic(feat_df, tw_df, us_map_df):
    """
    模擬 LightGBM 20d 模型的 cross-sectional IC，
    按 US regime 分組比較。

    使用 11 因子 rank-weighted score 作為 LightGBM 的近似。
    """
    print("\n" + "=" * 70)
    print("A: Conditional IC — 模型 IC 在不同 US regime 的差異")
    print("=" * 70)

    # 合併
    df = feat_df.merge(tw_df[["stock_id", "date", "close"]], on=["stock_id", "date"], how="inner")
    df = df.sort_values(["stock_id", "date"])

    # Forward return
    df["fwd_ret_20d"] = df.groupby("stock_id")["close"].transform(
        lambda x: x.shift(-HOLD - GAP + 1) / x.shift(-GAP + 1) - 1
    )

    # Composite score (11因子 rank average 作為 proxy)
    factors = ["roe", "yield_rate", "pb_ratio", "revenue_yoy",
               "rev_surprise", "rev_accel", "foreign_hold_chg_5d", "dealer_buy_20d",
               "vol_ratio", "ivol_20d", "trust_net_buy"]

    # neg 因子翻轉 (ivol 低=好, trust 反向)
    df["neg_ivol_20d"] = -df["ivol_20d"]
    df["neg_trust_net_buy"] = -df["trust_net_buy"]
    score_factors = ["roe", "yield_rate", "pb_ratio", "revenue_yoy",
                     "rev_surprise", "rev_accel", "foreign_hold_chg_5d", "dealer_buy_20d",
                     "vol_ratio", "neg_ivol_20d", "neg_trust_net_buy"]

    for f in score_factors:
        if f in df.columns:
            df[f"{f}_rank"] = df.groupby("date")[f].rank(pct=True)

    rank_cols = [f"{f}_rank" for f in score_factors if f"{f}_rank" in df.columns]
    df["composite_score"] = df[rank_cols].mean(axis=1)

    # 合併 US 訊號
    us_daily = us_map_df.rename(columns={"tw_date": "date"})
    df = df.merge(us_daily[["date", "sp500_ret", "vix_close"]], on="date", how="left")

    # US 多日動量
    us_sorted = us_map_df.sort_values("tw_date").copy()
    for w in [5, 10, 20]:
        us_sorted[f"sp500_mom{w}d"] = us_sorted["sp500_ret"].rolling(w, min_periods=w).sum()
    df = df.merge(
        us_sorted[["tw_date", "sp500_mom5d", "sp500_mom10d", "sp500_mom20d"]].rename(columns={"tw_date": "date"}),
        on="date", how="left"
    )

    # 每日 IC
    dates = sorted(df["date"].dropna().unique())
    daily_ic = []
    for d in dates:
        day = df[(df["date"] == d) & df["composite_score"].notna() & df["fwd_ret_20d"].notna()]
        if len(day) < 50:
            continue
        ic, _ = stats.spearmanr(day["composite_score"], day["fwd_ret_20d"])
        if np.isnan(ic):
            continue

        sp_ret = day["sp500_ret"].iloc[0] if "sp500_ret" in day.columns else np.nan
        vix = day["vix_close"].iloc[0] if "vix_close" in day.columns else np.nan
        mom5 = day["sp500_mom5d"].iloc[0] if "sp500_mom5d" in day.columns else np.nan
        mom20 = day["sp500_mom20d"].iloc[0] if "sp500_mom20d" in day.columns else np.nan

        # Top5/Bot5 報酬
        top5 = day.nlargest(5, "composite_score")["fwd_ret_20d"].mean()
        bot5 = day.nsmallest(5, "composite_score")["fwd_ret_20d"].mean()

        daily_ic.append({
            "date": d, "ic": ic,
            "sp500_ret": sp_ret, "vix": vix,
            "sp500_mom5d": mom5, "sp500_mom20d": mom20,
            "top5_ret": top5, "bot5_ret": bot5,
        })

    ic_df = pd.DataFrame(daily_ic)
    print(f"\n有效日數: {len(ic_df)}, 整體 IC: {ic_df['ic'].mean():+.4f}")

    # --- A1: SP500 前日漲跌 vs IC ---
    print(f"\n--- A1: SP500 前日漲跌 → 模型 IC ---")
    for label, mask in [
        ("美股漲", ic_df["sp500_ret"] > 0),
        ("美股跌", ic_df["sp500_ret"] < 0),
        ("美股大漲(>1%)", ic_df["sp500_ret"] > 1),
        ("美股大跌(<-1%)", ic_df["sp500_ret"] < -1),
    ]:
        sub = ic_df[mask]
        if len(sub) < 20:
            continue
        ic_mean = sub["ic"].mean()
        top5_mean = sub["top5_ret"].mean() * 100
        bot5_mean = sub["bot5_ret"].mean() * 100
        ls = top5_mean - bot5_mean
        print(f"  {label:<20s}  n={len(sub):>4d}  IC={ic_mean:>+.4f}  "
              f"Top5={top5_mean:>+.2f}%  Bot5={bot5_mean:>+.2f}%  L-S={ls:>+.2f}%")

    # --- A2: SP500 20d 動量 vs IC ---
    print(f"\n--- A2: SP500 20d 動量 → 模型 IC ---")
    valid = ic_df.dropna(subset=["sp500_mom20d"])
    if len(valid) > 50:
        q33 = valid["sp500_mom20d"].quantile(0.33)
        q67 = valid["sp500_mom20d"].quantile(0.67)
        for label, lo, hi in [
            ("美股下跌趨勢", -999, q33),
            ("美股盤整", q33, q67),
            ("美股上漲趨勢", q67, 999),
        ]:
            sub = valid[(valid["sp500_mom20d"] >= lo) & (valid["sp500_mom20d"] < hi)]
            if len(sub) < 20:
                continue
            ic_mean = sub["ic"].mean()
            top5_mean = sub["top5_ret"].mean() * 100
            bot5_mean = sub["bot5_ret"].mean() * 100
            print(f"  {label:<20s}  n={len(sub):>4d}  IC={ic_mean:>+.4f}  "
                  f"Top5={top5_mean:>+.2f}%  Bot5={bot5_mean:>+.2f}%")

    # --- A3: VIX 水位 vs IC ---
    print(f"\n--- A3: VIX 水位 → 模型 IC ---")
    valid = ic_df.dropna(subset=["vix"])
    if len(valid) > 50:
        q33 = valid["vix"].quantile(0.33)
        q67 = valid["vix"].quantile(0.67)
        for label, lo, hi in [
            (f"低VIX (<{q33:.1f})", 0, q33),
            (f"中VIX ({q33:.1f}~{q67:.1f})", q33, q67),
            (f"高VIX (>{q67:.1f})", q67, 999),
        ]:
            sub = valid[(valid["vix"] >= lo) & (valid["vix"] < hi)]
            if len(sub) < 20:
                continue
            ic_mean = sub["ic"].mean()
            top5_mean = sub["top5_ret"].mean() * 100
            bot5_mean = sub["bot5_ret"].mean() * 100
            print(f"  {label:<20s}  n={len(sub):>4d}  IC={ic_mean:>+.4f}  "
                  f"Top5={top5_mean:>+.2f}%  Bot5={bot5_mean:>+.2f}%")

    return ic_df


def timing_overlay_backtest(ic_df: pd.DataFrame):
    """
    B: Timing Overlay 回測
    策略：
      - Baseline: 固定做多 Top5 + 做空 Bot5
      - Overlay: 根據美股訊號調整權重
        - 美股漲 → 做多權重 100%, 做空權重 50%
        - 美股跌 → 做多權重 50%, 做空權重 100%
    """
    print("\n" + "=" * 70)
    print("B: Timing Overlay 回測")
    print("=" * 70)

    valid = ic_df.dropna(subset=["sp500_ret", "top5_ret", "bot5_ret"]).copy()
    if len(valid) < 50:
        print("資料不足")
        return

    # Baseline: 等權 long-short
    valid["baseline_ls"] = valid["top5_ret"] - valid["bot5_ret"]
    valid["baseline_long"] = valid["top5_ret"]
    valid["baseline_short"] = -valid["bot5_ret"]  # 做空的利潤 = -bot5_ret

    # Overlay 策略
    us_up = valid["sp500_ret"] > 0
    for name, long_w_up, short_w_up, long_w_dn, short_w_dn in [
        ("Overlay-1: 美漲偏多",  1.0, 0.5, 0.5, 1.0),
        ("Overlay-2: 美漲全多",  1.0, 0.0, 0.0, 1.0),
        ("Overlay-3: 溫和調整",  0.7, 0.3, 0.3, 0.7),
    ]:
        long_w = np.where(us_up, long_w_up, long_w_dn)
        short_w = np.where(us_up, short_w_up, short_w_dn)
        valid[name] = long_w * valid["top5_ret"] - short_w * valid["bot5_ret"]

    # 用 SP500 5d 動量
    sp5_valid = valid.dropna(subset=["sp500_mom5d"])
    sp5_up = sp5_valid["sp500_mom5d"] > 0
    sp5_valid["Overlay-4: 5d動量偏多"] = np.where(
        sp5_up,
        1.0 * sp5_valid["top5_ret"] - 0.5 * sp5_valid["bot5_ret"],
        0.5 * sp5_valid["top5_ret"] - 1.0 * sp5_valid["bot5_ret"],
    )

    # 比較結果
    strategies = ["baseline_ls", "Overlay-1: 美漲偏多", "Overlay-2: 美漲全多",
                  "Overlay-3: 溫和調整"]

    print(f"\n{'策略':<30s} {'月均報酬':>10s} {'Sharpe':>8s} {'WR':>8s} {'MDD':>8s}")
    print("-" * 70)

    for strat in strategies:
        rets = valid[strat].dropna()
        monthly = rets.mean() * 21  # ~21 trading days per month
        annual = rets.mean() * 252
        sharpe = rets.mean() / rets.std() * np.sqrt(252) if rets.std() > 0 else 0
        wr = (rets > 0).mean() * 100
        cum = (1 + rets).cumprod()
        mdd = ((cum / cum.cummax()) - 1).min() * 100

        label = strat if "Overlay" in strat else "Baseline (等權L-S)"
        print(f"  {label:<28s} {monthly*100:>+9.2f}% {sharpe:>8.2f} {wr:>7.1f}% {mdd:>+7.1f}%")

    # Overlay-4 (5d 動量)
    if len(sp5_valid) > 50:
        rets = sp5_valid["Overlay-4: 5d動量偏多"].dropna()
        monthly = rets.mean() * 21
        sharpe = rets.mean() / rets.std() * np.sqrt(252) if rets.std() > 0 else 0
        wr = (rets > 0).mean() * 100
        cum = (1 + rets).cumprod()
        mdd = ((cum / cum.cummax()) - 1).min() * 100
        print(f"  {'Overlay-4: 5d動量偏多':<28s} {monthly*100:>+9.2f}% {sharpe:>8.2f} {wr:>7.1f}% {mdd:>+7.1f}%")

    # 統計檢定: Overlay-1 vs Baseline
    from scipy.stats import ttest_rel
    base = valid["baseline_ls"].dropna()
    ov1 = valid["Overlay-1: 美漲偏多"].dropna()
    common = base.index.intersection(ov1.index)
    if len(common) > 50:
        t, p = ttest_rel(ov1.loc[common], base.loc[common])
        print(f"\n  Overlay-1 vs Baseline: t={t:+.3f}, p={p:.4f}"
              f"{'  ✓ 顯著' if p < 0.05 else '  ✗ 不顯著'}")


def directional_analysis(ic_df: pd.DataFrame):
    """
    C: 分別看做多和做空在不同 regime 的表現
    """
    print("\n" + "=" * 70)
    print("C: 做多/做空分別在 US regime 的表現")
    print("=" * 70)

    valid = ic_df.dropna(subset=["sp500_ret", "top5_ret", "bot5_ret"]).copy()

    print(f"\n{'Regime':<25s} {'做多Top5':>10s} {'做空Bot5':>10s} {'建議':>15s}")
    print("-" * 65)

    for label, mask in [
        ("美股大漲(>1%)", valid["sp500_ret"] > 1),
        ("美股小漲(0~1%)", (valid["sp500_ret"] > 0) & (valid["sp500_ret"] <= 1)),
        ("美股小跌(-1~0%)", (valid["sp500_ret"] >= -1) & (valid["sp500_ret"] < 0)),
        ("美股大跌(<-1%)", valid["sp500_ret"] < -1),
    ]:
        sub = valid[mask]
        if len(sub) < 15:
            continue
        top5 = sub["top5_ret"].mean() * 100
        bot5 = sub["bot5_ret"].mean() * 100
        short_profit = -bot5  # 做空利潤

        if top5 > 0.5 and short_profit < 0:
            advice = "純做多"
        elif top5 < 0 and short_profit > 0.5:
            advice = "純做空"
        elif top5 > 0 and short_profit > 0:
            advice = "做多+做空"
        else:
            advice = "觀望"

        print(f"  {label:<23s} {top5:>+9.2f}% {-bot5:>+9.2f}%   → {advice}")


def main():
    tw, us, feat = load_data()
    tw = tw.sort_values(["stock_id", "date"])
    tw["ret"] = tw.groupby("stock_id")["close"].pct_change()

    us_map = align_us(tw["date"], us)
    # 加 5d 動量
    us_map = us_map.sort_values("tw_date")
    us_map["sp500_mom5d"] = us_map["sp500_ret"].rolling(5, min_periods=5).sum()

    print(f"\n美股日期對齊: {len(us_map)} 個台股交易日")

    ic_df = simulate_model_ic(feat, tw, us_map)
    timing_overlay_backtest(ic_df)
    directional_analysis(ic_df)

    print("\n" + "=" * 70)
    print("研究完成！")
    print("=" * 70)


if __name__ == "__main__":
    main()

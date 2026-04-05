"""
產業集中度 & Alpha 分解
======================
模型反覆推薦同一批半導體股（奇鋐、欣興、川湖、晶豪科）。
本腳本驗證：alpha 來自「產業配置」還是「選股能力」？

Alpha 分解：
  Total Alpha = 做多Top5 - 大盤
  = (做多Top5 - 同產業均值) + (同產業均值 - 大盤)
  = 選股 Alpha + 產業配置 Alpha

使用: cd backend && ./.venv/bin/python scripts/research_sector_alpha.py
"""
from __future__ import annotations

import os
import warnings
from collections import Counter

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


def main():
    print("載入資料 ...", flush=True)

    signals = pd.read_sql(text(
        "SELECT signal_date, stock_id, stock_name, time_dimension, direction, weighted_win_rate"
        " FROM alpha_signal_history"
        " WHERE time_dimension IN (:d1, :d2) AND direction = :dir"
        " ORDER BY signal_date, weighted_win_rate DESC"
    ), engine, params={"d1": "30d", "d2": "20d", "dir": "long"})
    signals["signal_date"] = pd.to_datetime(signals["signal_date"])

    prices = pd.read_sql(text(
        "SELECT stock_id, date, close FROM stock_prices"
        " WHERE date >= :start AND close > 0 ORDER BY stock_id, date"
    ), engine, params={"start": "2025-08-01"})
    prices["date"] = pd.to_datetime(prices["date"])

    stocks_df = pd.read_sql(text(
        "SELECT stock_id, stock_name, industry FROM stocks WHERE industry IS NOT NULL"
    ), engine)
    industry_map = dict(zip(stocks_df["stock_id"], stocks_df["industry"]))

    print(f"  訊號: {len(signals)}, 價格: {len(prices):,}, 產業: {len(industry_map)}")

    # 交易日序列
    trading_days = sorted(prices["date"].unique())
    td_map = {d: i for i, d in enumerate(trading_days)}

    # 每個產業每天的股票集合（用於計算產業 benchmark）
    # 預先計算每個 (stock_id, date) 的 20d forward return
    print("計算 20d forward return ...", flush=True)
    prices = prices.sort_values(["stock_id", "date"])
    prices["fwd20"] = prices.groupby("stock_id")["close"].transform(
        lambda x: x.shift(-20) / x - 1
    )

    # 每日每產業的平均 20d return
    prices["industry"] = prices["stock_id"].map(industry_map)
    sector_daily = prices.dropna(subset=["fwd20", "industry"]).groupby(
        ["date", "industry"]
    )["fwd20"].mean().reset_index()
    sector_daily.columns = ["date", "industry", "sector_fwd20"]

    # 大盤每日平均 20d return
    mkt_daily = prices.dropna(subset=["fwd20"]).groupby("date")["fwd20"].mean()

    # ═══ 逐日分析 Top5 ═══
    daily = []
    all_industries = []

    for d in sorted(signals["signal_date"].unique()):
        if d not in td_map:
            continue
        idx = td_map[d]
        if idx + 20 >= len(trading_days):
            continue

        day_sigs = signals[signals["signal_date"] == d].nlargest(5, "weighted_win_rate")
        entry_date = trading_days[idx + 1]

        rets = []
        sector_rets = []
        industries = []

        for _, sig in day_sigs.iterrows():
            # 個股 20d return
            sp = prices[(prices["stock_id"] == sig["stock_id"]) & (prices["date"] == entry_date)]
            if sp.empty or pd.isna(sp["fwd20"].iloc[0]):
                continue

            stock_ret = sp["fwd20"].iloc[0]
            ind = industry_map.get(sig["stock_id"], "未知")

            # 同產業 benchmark
            sec_row = sector_daily[
                (sector_daily["date"] == entry_date) & (sector_daily["industry"] == ind)
            ]
            sec_ret = sec_row["sector_fwd20"].iloc[0] if not sec_row.empty else np.nan

            rets.append(stock_ret)
            sector_rets.append(sec_ret)
            industries.append(ind)

        if not rets:
            continue

        mkt_ret = mkt_daily.get(entry_date, 0)
        avg_ret = np.mean(rets)
        avg_sector = np.nanmean(sector_rets)

        all_industries.extend(industries)

        # 電子系佔比
        elec_keywords = ["半導體", "電子", "光電", "電腦", "通信", "電機", "資訊"]
        elec_count = sum(1 for i in industries if any(k in i for k in elec_keywords))

        daily.append({
            "date": d,
            "month": pd.Timestamp(d).to_period("M"),
            "top5_ret": avg_ret,
            "mkt_ret": mkt_ret,
            "sector_ret": avg_sector,
            "excess_vs_mkt": avg_ret - mkt_ret,
            "excess_vs_sector": avg_ret - avg_sector,
            "elec_pct": elec_count / len(rets) * 100,
            "industries": industries,
        })

    dr = pd.DataFrame(daily)

    # ═══════════════════════════════════════════════════════════════════
    # 結果
    # ═══════════════════════════════════════════════════════════════════
    print("\n" + "=" * 80)
    print("產業集中度分析")
    print("=" * 80)

    ind_counts = Counter(all_industries)
    total_picks = len(all_industries)
    print(f"\nTop5 推薦的產業分布（{total_picks} 檔次）:")
    for ind, cnt in ind_counts.most_common(15):
        bar = "█" * int(cnt / total_picks * 50)
        print(f"  {ind:<20s} {cnt:>4d} ({cnt/total_picks*100:>5.1f}%) {bar}")

    print(f"\n電子科技佔比: {dr['elec_pct'].mean():.1f}%")

    # Alpha 分解
    print("\n" + "=" * 80)
    print("Alpha 分解: 產業配置 vs 選股")
    print("=" * 80)

    total_alpha = dr["excess_vs_mkt"].mean()
    sector_contrib = dr["sector_ret"].mean() - dr["mkt_ret"].mean()
    stock_contrib = dr["top5_ret"].mean() - dr["sector_ret"].mean()

    t_vs_mkt = dr["excess_vs_mkt"].mean() / (dr["excess_vs_mkt"].std() / np.sqrt(len(dr)))
    t_vs_sec = dr["excess_vs_sector"].mean() / (dr["excess_vs_sector"].std() / np.sqrt(len(dr)))

    print(f"\n整體 ({len(dr)} 天):")
    print(f"  做多 Top5 報酬:     {dr['top5_ret'].mean()*100:>+.2f}%")
    print(f"  大盤報酬:           {dr['mkt_ret'].mean()*100:>+.2f}%")
    print(f"  同產業報酬:         {dr['sector_ret'].mean()*100:>+.2f}%")
    print(f"")
    print(f"  超額 vs 大盤:       {total_alpha*100:>+.2f}%  t={t_vs_mkt:.2f}")
    print(f"  超額 vs 同產業:     {dr['excess_vs_sector'].mean()*100:>+.2f}%  t={t_vs_sec:.2f}")
    print(f"")
    pct_sector = sector_contrib / total_alpha * 100 if total_alpha != 0 else 0
    pct_stock = stock_contrib / total_alpha * 100 if total_alpha != 0 else 0
    print(f"  ┌─ 產業配置 alpha:  {sector_contrib*100:>+.2f}%  ({pct_sector:.0f}%)")
    print(f"  └─ 選股 alpha:      {stock_contrib*100:>+.2f}%  ({pct_stock:.0f}%)")
    print(f"     總 alpha:        {total_alpha*100:>+.2f}%  (100%)")

    # 月度分解
    print(f"\n--- 月度 Alpha 分解 ---")
    print(f"  {'月份':>8s}  {'做多':>8s}  {'大盤':>8s}  {'產業':>8s}  {'vs大盤':>8s}  {'vs產業':>8s}  {'電子%':>6s}")
    print("  " + "-" * 65)
    for m, g in dr.groupby("month"):
        print(
            f"  {str(m):>8s}  {g['top5_ret'].mean()*100:>+7.2f}%  {g['mkt_ret'].mean()*100:>+7.2f}%  "
            f"{g['sector_ret'].mean()*100:>+7.2f}%  {g['excess_vs_mkt'].mean()*100:>+7.2f}%  "
            f"{g['excess_vs_sector'].mean()*100:>+7.2f}%  {g['elec_pct'].mean():>5.0f}%"
        )

    # 勝率
    print(f"\n--- 勝率 ---")
    exc_mkt = dr["excess_vs_mkt"]
    exc_sec = dr["excess_vs_sector"]
    print(f"  超越大盤勝率:   {(exc_mkt > 0).mean()*100:.1f}%")
    print(f"  超越同產業勝率: {(exc_sec > 0).mean()*100:.1f}%")

    print("\n" + "=" * 80)
    print("分析完成！")
    print("=" * 80)


if __name__ == "__main__":
    main()

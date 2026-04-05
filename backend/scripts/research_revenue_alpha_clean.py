"""
營收 Alpha 嚴格研究（無前視偏差版）

方法論：
- 進場日固定為每月 11 日（最近交易日）：確保所有公司 10 日前已公布
- 用當月剛公布的 rev_surprise 排名（M 月營收 → M+1 月 11 日進場）
- 也測試用「上個月」的 rev_surprise（更保守，M-1 月營收 → M+1 月 11 日）
- 持有期：5d, 10d, 20d
- 必含 long-short 測試
- 按年度分組看穩定性

因子候選：
- rev_surprise: 實際營收 vs 3 月均值（%偏差）
- rev_accel: 營收加速度（本月 YoY - 上月 YoY）
- rev_combo: rev_surprise 和 rev_accel 的等權排名和
"""
from __future__ import annotations

import os
import warnings
from typing import Dict, List

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
COST = 0.006


def load_revenue() -> pd.DataFrame:
    sql = text("""
        SELECT stock_id, year, month, revenue, revenue_yoy
        FROM stock_revenue_history WHERE revenue > 0
        ORDER BY stock_id, year, month
    """)
    df = pd.read_sql(sql, engine)
    df = df.sort_values(["stock_id", "year", "month"]).reset_index(drop=True)
    g = df.groupby("stock_id")
    df["rev_ma3"] = g["revenue"].transform(
        lambda x: x.rolling(3, min_periods=2).mean().shift(1)
    )
    df["rev_surprise"] = (df["revenue"] - df["rev_ma3"]) / df["rev_ma3"] * 100
    df["rev_accel"] = g["revenue_yoy"].diff()

    # 公布月：M 月營收 → M+1 月公布
    next_m = df["month"] + 1
    df["ann_year"] = df["year"] + (next_m > 12).astype(int)
    df["ann_month"] = next_m.where(next_m <= 12, next_m - 12)
    df["ann_ym"] = df["ann_year"].astype(int) * 100 + df["ann_month"].astype(int)
    return df


def load_prices() -> pd.DataFrame:
    sql = text("""
        SELECT stock_id, date, close
        FROM stock_prices WHERE close > 0 AND date >= '2023-01-01'
        ORDER BY stock_id, date
    """)
    df = pd.read_sql(sql, engine)
    df["date"] = pd.to_datetime(df["date"])
    return df


def get_pos(px: pd.Series, dt: pd.Timestamp) -> int | None:
    if dt not in px.index:
        return None
    loc = px.index.get_loc(dt)
    if isinstance(loc, int):
        return loc
    if isinstance(loc, slice):
        return loc.start
    return int(np.flatnonzero(loc)[0])


def run_analysis(rev: pd.DataFrame, prices: pd.DataFrame) -> None:
    trade_dates = np.sort(prices["date"].unique())

    price_map: Dict[str, pd.Series] = {}
    for sid, grp in prices.groupby("stock_id"):
        price_map[sid] = grp.set_index("date")["close"].sort_index()

    # 營收因子按公布月分組
    rev_clean = rev.dropna(subset=["rev_surprise"]).copy()

    # 測試月份：2023-08 起（至少 6 個月歷史）
    test_yms = sorted(ym for ym in rev_clean["ann_ym"].unique() if ym >= 202308)

    HOLD_DAYS = [5, 10, 20]
    ENTRY_DAY = 11  # 確保全部公司已公布

    # ════════════════════════════════════════════════════════════
    #  策略 A: 用當月 rev_surprise（剛公布的）
    #  策略 B: 用上個月 rev_surprise（延遲 1 個月，更保守）
    #  策略 C: rev_combo（rev_surprise + rev_accel 等權排名和）
    # ════════════════════════════════════════════════════════════

    strategies = {
        "A_當月rev_surprise": {"lag": 0, "factor": "rev_surprise"},
        "B_上月rev_surprise": {"lag": 1, "factor": "rev_surprise"},
        "C_當月rev_combo":    {"lag": 0, "factor": "rev_combo"},
    }

    for strat_name, strat_cfg in strategies.items():
        lag = strat_cfg["lag"]
        factor = strat_cfg["factor"]

        print(f"\n{'=' * 120}")
        print(f"  策略: {strat_name} | 進場: 每月{ENTRY_DAY}日 | lag={lag}")
        print(f"{'=' * 120}")

        all_months: Dict[int, List[dict]] = {h: [] for h in HOLD_DAYS}

        for ym in test_yms:
            y, m = ym // 100, ym % 100

            # 決定使用哪個月的營收
            if lag == 0:
                use_ym = ym
            else:
                # 上個月
                pm = m - 1
                py = y
                if pm < 1:
                    pm = 12
                    py -= 1
                use_ym = py * 100 + pm

            avail = rev_clean[rev_clean["ann_ym"] == use_ym].copy()
            if len(avail) < 100:
                continue

            # 計算 combo factor
            if factor == "rev_combo":
                avail["rs_rank"] = avail["rev_surprise"].rank(pct=True)
                avail["ra_rank"] = avail["rev_accel"].rank(pct=True, na_option="keep")
                avail["rev_combo"] = avail["rs_rank"] + avail["ra_rank"].fillna(0.5)
                avail = avail.dropna(subset=["rev_combo"])
            else:
                avail = avail.dropna(subset=[factor])

            # 排名
            avail["rank"] = avail[factor].rank(pct=True)
            top10 = set(avail[avail["rank"] >= 0.9]["stock_id"].values)
            bot10 = set(avail[avail["rank"] <= 0.1]["stock_id"].values)

            # 進場日
            try:
                target = pd.Timestamp(y, m, ENTRY_DAY)
            except ValueError:
                continue
            idx = np.searchsorted(trade_dates, np.datetime64(target))
            if idx >= len(trade_dates):
                continue
            t0 = pd.Timestamp(trade_dates[idx])

            for hold in HOLD_DAYS:
                top_rets, bot_rets, mkt_rets = [], [], []
                factor_vals, ret_vals = [], []

                for _, row in avail.iterrows():
                    sid = row["stock_id"]
                    if sid not in price_map:
                        continue
                    px = price_map[sid]
                    pos = get_pos(px, t0)
                    if pos is None:
                        continue
                    exit_pos = pos + hold
                    if exit_pos >= len(px.values):
                        continue

                    ret = (px.values[exit_pos] - px.values[pos]) / px.values[pos]
                    mkt_rets.append(ret)
                    factor_vals.append(row[factor])
                    ret_vals.append(ret)

                    if sid in top10:
                        top_rets.append(ret)
                    if sid in bot10:
                        bot_rets.append(ret)

                if len(top_rets) < 10 or len(mkt_rets) < 50:
                    continue

                top_avg = np.mean(top_rets)
                bot_avg = np.mean(bot_rets) if bot_rets else np.nan
                mkt_avg = np.mean(mkt_rets)

                ic, _ = stats.spearmanr(factor_vals, ret_vals)

                all_months[hold].append({
                    "ym": ym,
                    "top10": top_avg,
                    "bot10": bot_avg,
                    "mkt": mkt_avg,
                    "excess": top_avg - mkt_avg,
                    "ls": top_avg - bot_avg if not np.isnan(bot_avg) else np.nan,
                    "ic": ic if not np.isnan(ic) else np.nan,
                    "n_top": len(top_rets),
                    "n_all": len(mkt_rets),
                })

        # ── 結果 ──
        for hold in HOLD_DAYS:
            months = all_months[hold]
            if not months:
                continue
            mdf = pd.DataFrame(months)

            print(f"\n  ── 持有 {hold}d ──")
            print(f"  {'月份':>8} {'Top10%':>8} {'Bot10%':>8} {'市場':>8}"
                  f" {'超額':>8} {'L-S':>8} {'IC':>8} {'N_top':>6}")
            print("  " + "─" * 74)

            for _, r in mdf.iterrows():
                ym_str = f"{int(r['ym'])//100}-{int(r['ym'])%100:02d}"
                bot_str = f"{r['bot10']*100:>+8.2f}" if not np.isnan(r['bot10']) else f"{'N/A':>8}"
                ls_str = f"{r['ls']*100:>+8.2f}" if not np.isnan(r['ls']) else f"{'N/A':>8}"
                ic_str = f"{r['ic']:>+8.4f}" if not np.isnan(r['ic']) else f"{'N/A':>8}"
                print(f"  {ym_str:>8} {r['top10']*100:>+8.2f} {bot_str}"
                      f" {r['mkt']*100:>+8.2f} {r['excess']*100:>+8.2f}"
                      f" {ls_str} {ic_str} {r['n_top']:>6.0f}")

            # 彙總
            n = len(mdf)
            avg_top = mdf["top10"].mean() * 100
            avg_bot = mdf["bot10"].dropna().mean() * 100
            avg_mkt = mdf["mkt"].mean() * 100
            avg_excess = mdf["excess"].mean() * 100
            avg_ls = mdf["ls"].dropna().mean() * 100
            avg_ic = mdf["ic"].dropna().mean()
            ic_pos = (mdf["ic"].dropna() > 0).mean()
            excess_pos = (mdf["excess"] > 0).mean()
            ls_pos = (mdf["ls"].dropna() > 0).mean()

            # bot10 下跌率（真空端分辨力）
            bot_neg = (mdf["bot10"].dropna() < 0).mean()

            # Sharpe
            me = mdf["excess"].values
            sharpe = np.mean(me) / np.std(me, ddof=1) * np.sqrt(12) if np.std(me) > 0 else 0

            # MaxDD
            cum = (1 + mdf["top10"] - COST).cumprod()
            dd = ((cum - cum.cummax()) / cum.cummax()).min() * 100

            # 累積報酬
            cum_top = (cum.iloc[-1] - 1) * 100
            cum_mkt = ((1 + mdf["mkt"]).cumprod().iloc[-1] - 1) * 100

            print("  " + "─" * 74)
            print(f"  {'平均':>8} {avg_top:>+8.2f} {avg_bot:>+8.2f}"
                  f" {avg_mkt:>+8.2f} {avg_excess:>+8.2f}"
                  f" {avg_ls:>+8.2f} {avg_ic:>+8.4f}")
            print(f"  月數: {n} | IC正比: {ic_pos:.0%} | 超額正比: {excess_pos:.0%}"
                  f" | L-S正比: {ls_pos:.0%} | Bot10%下跌率: {bot_neg:.0%}")
            print(f"  Sharpe: {sharpe:.2f} | MaxDD: {dd:.1f}%"
                  f" | 累積(扣成本): {cum_top:+.1f}% vs 市場 {cum_mkt:+.1f}%")

            # 按年分組
            mdf["year"] = mdf["ym"] // 100
            print(f"\n  按年度:")
            for yr, ygrp in mdf.groupby("year"):
                y_excess = ygrp["excess"].mean() * 100
                y_ls = ygrp["ls"].dropna().mean() * 100
                y_ic = ygrp["ic"].dropna().mean()
                y_ic_pos = (ygrp["ic"].dropna() > 0).mean()
                y_n = len(ygrp)
                print(f"    {yr}: 超額{y_excess:>+.2f}% | L-S{y_ls:>+.2f}%"
                      f" | IC{y_ic:>+.4f} ({y_ic_pos:.0%}正) | {y_n}月")

    # ════════════════════════════════════════════════════════════
    #  最終對比
    # ════════════════════════════════════════════════════════════
    print(f"\n{'=' * 120}")
    print(f"  最終對比（所有策略 × 持有期）")
    print(f"{'=' * 120}")
    print(f"\n  已消除前視偏差：進場日={ENTRY_DAY}日（所有公司已公布）")
    print(f"  可信度指標：IC正比 ≥ 70% 且 L-S > 0 且 Bot10%下跌率 > 50%\n")


def main() -> None:
    print("=== 營收 Alpha 嚴格研究（無前視偏差）===\n")
    rev = load_revenue()
    prices = load_prices()
    print(f"Revenue: {len(rev):,} | Prices: {len(prices):,}")
    run_analysis(rev, prices)


if __name__ == "__main__":
    main()

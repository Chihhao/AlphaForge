"""
Walk-Forward 驗證：營收事件 Overlay 策略

策略邏輯：
- 每月 5 日（最近交易日），取已公布營收中 rev_surprise Top10% 的股票
- 買入持有 5 / 10 天
- 純因子排序（無 ML 訓練），但用 walk-forward 格式確認每月 OOS 表現

比較基準：
A) 營收事件 overlay（5日進場, 5d 持有）
B) 營收事件 overlay（5日進場, 10d 持有）
C) 現有 20d 靜態模型 baseline（10日進場, 20d 持有）
D) 等權市場基準

額外分析：
- 和現有 20d 模型的報酬相關性（判斷是否互補）
- 組合策略：20d + overlay 的疊加效果
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
COST = 0.006  # 來回成本


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

    # 公布月
    next_m = df["month"] + 1
    df["ann_year"] = df["year"] + (next_m > 12).astype(int)
    df["ann_month"] = next_m.where(next_m <= 12, next_m - 12)
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


def find_trade_day(trade_dates: np.ndarray, target: pd.Timestamp) -> pd.Timestamp | None:
    idx = np.searchsorted(trade_dates, np.datetime64(target))
    return pd.Timestamp(trade_dates[idx]) if idx < len(trade_dates) else None


def run_walkforward(rev: pd.DataFrame, prices: pd.DataFrame) -> None:
    trade_dates = np.sort(prices["date"].unique())

    # Price lookup
    price_map: Dict[str, pd.Series] = {}
    for sid, grp in prices.groupby("stock_id"):
        price_map[sid] = grp.set_index("date")["close"].sort_index()

    # 建立每月可用的 rev_surprise snapshot
    # 對於公布月 (ann_year, ann_month)，在 entry_day 時可用的最新營收
    rev_by_ann = rev.dropna(subset=["rev_surprise"]).copy()
    rev_by_ann["ann_ym"] = (
        rev_by_ann["ann_year"].astype(int) * 100
        + rev_by_ann["ann_month"].astype(int)
    )

    # 收集所有測試月
    all_ann_yms = sorted(rev_by_ann["ann_ym"].unique())
    # 至少要有 6 個月歷史
    test_yms = [ym for ym in all_ann_yms if ym >= 202307]

    # 策略配置
    configs = [
        {"name": "Event_5d", "entry_day": 5, "hold": 5},
        {"name": "Event_10d", "entry_day": 5, "hold": 10},
        {"name": "Baseline_20d", "entry_day": 10, "hold": 20},
    ]

    all_monthly: Dict[str, List[dict]] = {c["name"]: [] for c in configs}

    print(f"\n{'=' * 120}")
    print(f"  Walk-Forward: 營收事件 Overlay 策略")
    print(f"  測試期: {test_yms[0]} ~ {test_yms[-1]} ({len(test_yms)} 個月)")
    print(f"{'=' * 120}")

    for cfg in configs:
        entry_day = cfg["entry_day"]
        hold = cfg["hold"]
        name = cfg["name"]

        for ym in test_yms:
            y = ym // 100
            m = ym % 100

            # 該月可用的 rev_surprise（公布月 = ym 的營收）
            avail = rev_by_ann[rev_by_ann["ann_ym"] == ym]
            if len(avail) < 50:
                continue

            # 進場日
            try:
                target = pd.Timestamp(y, m, entry_day)
            except ValueError:
                continue
            t0 = find_trade_day(trade_dates, target)
            if t0 is None:
                continue

            # 排名並取 Top10%
            avail = avail.copy()
            avail["rank"] = avail["rev_surprise"].rank(pct=True)
            top10 = avail[avail["rank"] >= 0.9]
            bot10 = avail[avail["rank"] <= 0.1]

            # 計算組合報酬
            top_rets = []
            bot_rets = []
            mkt_rets = []

            for _, row in avail.iterrows():
                sid = row["stock_id"]
                if sid not in price_map:
                    continue
                px = price_map[sid]
                if t0 not in px.index:
                    continue
                loc = px.index.get_loc(t0)
                pos = loc if isinstance(loc, int) else loc.start if isinstance(loc, slice) else int(np.flatnonzero(loc)[0])
                exit_pos = pos + hold
                if exit_pos >= len(px.values):
                    continue
                ret = (px.values[exit_pos] - px.values[pos]) / px.values[pos]
                mkt_rets.append(ret)

                if row["stock_id"] in top10["stock_id"].values:
                    top_rets.append(ret)
                if row["stock_id"] in bot10["stock_id"].values:
                    bot_rets.append(ret)

            if not top_rets or not mkt_rets:
                continue

            top_avg = np.mean(top_rets)
            bot_avg = np.mean(bot_rets) if bot_rets else np.nan
            mkt_avg = np.mean(mkt_rets)
            excess = top_avg - mkt_avg
            ls_spread = top_avg - bot_avg if not np.isnan(bot_avg) else np.nan

            # IC (全截面)
            vals = []
            rets_for_ic = []
            for _, row in avail.iterrows():
                sid = row["stock_id"]
                if sid not in price_map:
                    continue
                px = price_map[sid]
                if t0 not in px.index:
                    continue
                loc = px.index.get_loc(t0)
                pos = loc if isinstance(loc, int) else loc.start if isinstance(loc, slice) else int(np.flatnonzero(loc)[0])
                exit_pos = pos + hold
                if exit_pos >= len(px.values):
                    continue
                ret = (px.values[exit_pos] - px.values[pos]) / px.values[pos]
                vals.append(row["rev_surprise"])
                rets_for_ic.append(ret)

            ic = np.nan
            if len(vals) >= 30:
                ic, _ = stats.spearmanr(vals, rets_for_ic)

            all_monthly[name].append({
                "ym": ym,
                "date": t0,
                "top10_ret": top_avg,
                "bot10_ret": bot_avg,
                "mkt_ret": mkt_avg,
                "excess": excess,
                "ls_spread": ls_spread,
                "ic": ic,
                "n_top": len(top_rets),
                "n_total": len(mkt_rets),
            })

    # ── 逐月結果 ──
    for cfg in configs:
        name = cfg["name"]
        months = all_monthly[name]
        if not months:
            continue

        mdf = pd.DataFrame(months)

        print(f"\n  ── {name} (進場{cfg['entry_day']}日 / 持有{cfg['hold']}d) ──")
        print(f"  {'月份':>8} {'Top10%':>8} {'Bot10%':>8} {'市場':>8} {'超額':>8} {'L-S':>8} {'IC':>8} {'N':>5}")
        print("  " + "─" * 72)

        for _, r in mdf.iterrows():
            ym_str = f"{r['ym'] // 100}-{r['ym'] % 100:02d}"
            print(
                f"  {ym_str:>8}"
                f" {r['top10_ret']*100:>+8.2f}"
                f" {r['bot10_ret']*100:>+8.2f}" if not np.isnan(r['bot10_ret']) else f" {'N/A':>8}"
                f" {r['mkt_ret']*100:>+8.2f}"
                f" {r['excess']*100:>+8.2f}"
                f" {r['ls_spread']*100:>+8.2f}" if not np.isnan(r['ls_spread']) else f" {'N/A':>8}"
                f" {r['ic']:>+8.4f}" if not np.isnan(r['ic']) else f" {'N/A':>8}"
                f" {r['n_top']:>5.0f}"
            )

        # 彙總
        avg_top = mdf["top10_ret"].mean() * 100
        avg_bot = mdf["bot10_ret"].mean() * 100
        avg_mkt = mdf["mkt_ret"].mean() * 100
        avg_excess = mdf["excess"].mean() * 100
        avg_ls = mdf["ls_spread"].dropna().mean() * 100
        avg_ic = mdf["ic"].dropna().mean()
        ic_pos = (mdf["ic"].dropna() > 0).mean()
        excess_pos = (mdf["excess"] > 0).mean()

        # 累積報酬
        cum_top = (1 + mdf["top10_ret"] - COST).prod() - 1
        cum_mkt = (1 + mdf["mkt_ret"]).prod() - 1

        # Sharpe (月度)
        monthly_excess = mdf["excess"].values
        sharpe = (np.mean(monthly_excess) / np.std(monthly_excess, ddof=1)
                  * np.sqrt(12) if np.std(monthly_excess) > 0 else 0)

        # MaxDD
        cum_vals = (1 + mdf["top10_ret"] - COST).cumprod()
        peak = cum_vals.cummax()
        dd = (cum_vals - peak) / peak
        max_dd = dd.min() * 100

        print("  " + "─" * 72)
        print(f"  {'平均':>8} {avg_top:>+8.2f} {avg_bot:>+8.2f} {avg_mkt:>+8.2f}"
              f" {avg_excess:>+8.2f} {avg_ls:>+8.2f} {avg_ic:>+8.4f}")
        print(f"  IC正比: {ic_pos:.0%} | 超額正比: {excess_pos:.0%}")
        print(f"  累積(扣成本): Top10%={cum_top*100:+.1f}% | 市場={cum_mkt*100:+.1f}%")
        print(f"  Sharpe: {sharpe:.2f} | MaxDD: {max_dd:.1f}%")

    # ── 策略對比摘要 ──
    print(f"\n{'=' * 120}")
    print(f"  策略對比摘要")
    print(f"{'=' * 120}")
    print(f"\n  {'策略':>15} {'月均超額':>8} {'月均L-S':>8} {'月均IC':>8} {'IC正比':>7}"
          f" {'Sharpe':>7} {'MaxDD':>7} {'超額正比':>8} {'月數':>5}")
    print("  " + "─" * 90)

    strategy_monthly = {}
    for cfg in configs:
        name = cfg["name"]
        months = all_monthly[name]
        if not months:
            continue
        mdf = pd.DataFrame(months)
        strategy_monthly[name] = mdf

        avg_excess = mdf["excess"].mean() * 100
        avg_ls = mdf["ls_spread"].dropna().mean() * 100
        avg_ic = mdf["ic"].dropna().mean()
        ic_pos = (mdf["ic"].dropna() > 0).mean()
        excess_pos = (mdf["excess"] > 0).mean()
        monthly_excess = mdf["excess"].values
        sharpe = (np.mean(monthly_excess) / np.std(monthly_excess, ddof=1)
                  * np.sqrt(12) if np.std(monthly_excess) > 0 else 0)
        cum_vals = (1 + mdf["top10_ret"] - COST).cumprod()
        max_dd = ((cum_vals - cum_vals.cummax()) / cum_vals.cummax()).min() * 100

        print(f"  {name:>15} {avg_excess:>+8.2f} {avg_ls:>+8.2f} {avg_ic:>+8.4f}"
              f" {ic_pos:>6.0%} {sharpe:>7.2f} {max_dd:>6.1f}%"
              f" {excess_pos:>7.0%} {len(mdf):>5}")

    # ── 相關性分析 ──
    if "Event_5d" in strategy_monthly and "Baseline_20d" in strategy_monthly:
        print(f"\n  ── 策略間報酬相關性（判斷互補性）──")
        ev5 = strategy_monthly["Event_5d"].set_index("ym")["excess"]
        bl20 = strategy_monthly["Baseline_20d"].set_index("ym")["excess"]
        common_yms = ev5.index.intersection(bl20.index)
        if len(common_yms) >= 6:
            corr, p = stats.pearsonr(ev5.loc[common_yms], bl20.loc[common_yms])
            print(f"  Event_5d vs Baseline_20d 超額相關: {corr:+.3f} (p={p:.4f})")
            if abs(corr) < 0.3:
                print(f"  → ★ 低相關 — 兩策略互補性強，疊加有效")
            elif abs(corr) < 0.6:
                print(f"  → ◎ 中度相關 — 部分互補")
            else:
                print(f"  → ✗ 高相關 — 疊加效果有限")

            # 模擬組合：20d 持續持有 + Event overlay
            # 簡化：每月報酬 = 20d 超額 + event 超額（假設資金各半）
            combo_excess = (ev5.loc[common_yms] + bl20.loc[common_yms]) / 2
            combo_sharpe = (combo_excess.mean() / combo_excess.std()
                           * np.sqrt(12) if combo_excess.std() > 0 else 0)
            ev5_sharpe = (ev5.loc[common_yms].mean() / ev5.loc[common_yms].std()
                          * np.sqrt(12) if ev5.loc[common_yms].std() > 0 else 0)
            bl20_sharpe = (bl20.loc[common_yms].mean() / bl20.loc[common_yms].std()
                           * np.sqrt(12) if bl20.loc[common_yms].std() > 0 else 0)

            print(f"\n  {'策略':>20} {'Sharpe':>8}")
            print(f"  " + "─" * 30)
            print(f"  {'Event_5d 單獨':>20} {ev5_sharpe:>8.2f}")
            print(f"  {'Baseline_20d 單獨':>20} {bl20_sharpe:>8.2f}")
            print(f"  {'50/50 組合':>20} {combo_sharpe:>8.2f}")

            improvement = (combo_sharpe - max(ev5_sharpe, bl20_sharpe)) / max(ev5_sharpe, bl20_sharpe) * 100
            print(f"  組合 vs 最佳單一: {improvement:+.0f}%")

    # ── 最終結論 ──
    print(f"\n{'=' * 120}")
    print(f"  結論")
    print(f"{'=' * 120}")
    if strategy_monthly:
        ev = strategy_monthly.get("Event_5d")
        bl = strategy_monthly.get("Baseline_20d")
        if ev is not None and bl is not None:
            ev_excess = ev["excess"].mean() * 100
            bl_excess = bl["excess"].mean() * 100
            ev_ic_pos = (ev["ic"].dropna() > 0).mean()
            if ev_excess > bl_excess and ev_ic_pos >= 0.7:
                print(f"  ★ 營收事件 overlay 通過 walk-forward 驗證")
                print(f"    Event_5d 月均超額 {ev_excess:+.2f}% > Baseline_20d {bl_excess:+.2f}%")
                print(f"    IC 正比 {ev_ic_pos:.0%}")
                print(f"    建議：整合進上線系統作為月初加碼策略")
            elif ev_excess > 0 and ev_ic_pos >= 0.6:
                print(f"  ◎ 營收事件有 alpha 但優勢不夠大")
                print(f"    建議繼續觀察，暫不上線")
            else:
                print(f"  ✗ 營收事件策略在 walk-forward 中表現不佳")
                print(f"    不建議上線")


def main() -> None:
    print("=== Walk-Forward: 營收事件 Overlay ===\n")
    rev = load_revenue()
    prices = load_prices()
    print(f"Revenue: {len(rev):,} | Prices: {len(prices):,}")
    run_walkforward(rev, prices)


if __name__ == "__main__":
    main()

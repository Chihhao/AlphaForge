"""
diagnose_5d.py — 5日短線策略深度診斷
"""
from __future__ import annotations
import sys, os, warnings
import numpy as np
import pandas as pd
from datetime import date, timedelta
from scipy import stats

warnings.filterwarnings('ignore')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
logging.basicConfig(level=logging.WARNING)


def main():
    from app.db.database import engine, SessionLocal
    from sqlalchemy import text

    print("=" * 70)
    print("  5 日短線策略深度診斷")
    print("=" * 70)

    # ── 載入資料 ──────────────────────────────────────────────────────
    cutoff = (date.today() - timedelta(days=365 * 2)).isoformat()
    factor_cols = [
        'rsi14', 'k', 'd', 'macd_dif', 'macd_osc',
        'bias5', 'bias10', 'bias20', 'bb_pctb', 'vol_ratio',
        'yield_rate', 'roe', 'pb_ratio', 'revenue_yoy',
        'foreign_net_buy', 'foreign_buy_5d', 'trust_net_buy', 'trust_buy_5d',
        'margin_chg_5d', 'dealer_net_buy', 'dealer_buy_5d',
        'price_vs_high20', 'ma_trend', 'sector_rs',
        'foreign_hold_pct', 'foreign_hold_chg_5d',
    ]
    cols = ['stock_id', 'date', 'close'] + factor_cols
    sql = text(f"SELECT {', '.join(cols)} FROM stock_features WHERE date >= :cutoff")
    df = pd.read_sql(sql, engine, params={"cutoff": cutoff})
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values(['stock_id', 'date'])

    # Forward returns
    df['fwd_close'] = df.groupby('stock_id')['close'].shift(-5)
    close = df['close'].replace(0, np.nan)
    df['ret_5d'] = (df['fwd_close'] - close) / close

    # 測試期
    max_date = df['date'].max()
    test_start = max_date - pd.DateOffset(months=6)
    test_df = df[df['date'] >= test_start].dropna(subset=['ret_5d']).copy()
    print(f"\n測試期: {test_start.date()} ~ {max_date.date()}")
    print(f"測試筆數: {len(test_df):,}")

    # ══════════════════════════════════════════════════════════════════
    # 1. 交易成本影響
    # ══════════════════════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("  1. 交易成本對 5 日報酬的影響")
    print("=" * 70)
    ret = test_df['ret_5d']
    cost = 0.006  # 0.6%

    for label, r in [("扣成本前", ret), ("扣成本後", ret - cost)]:
        print(f"\n  {label}:")
        print(f"    平均: {r.mean()*100:+.3f}%  中位數: {r.median()*100:+.3f}%")
        print(f"    勝率(>0%): {(r > 0).mean()*100:.1f}%")
        print(f"    勝率(>1%): {(r > 0.01).mean()*100:.1f}%")
        print(f"    勝率(>3%): {(r > 0.03).mean()*100:.1f}%")

    print(f"\n  → 0.6% 成本佔 5 日平均報酬({ret.mean()*100:.3f}%)的"
          f" {cost / max(abs(ret.mean()), 0.0001) * 100:.0f}%")

    # ══════════════════════════════════════════════════════════════════
    # 2. 因子分位數 → 實際 5d 報酬（quintile analysis）
    # ══════════════════════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("  2. 因子分位數分析 — Top/Bottom Quintile 的 5 日報酬")
    print("=" * 70)

    top_factors = ['bias10', 'bias20', 'bb_pctb', 'rsi14', 'k',
                   'macd_osc', 'sector_rs', 'vol_ratio',
                   'trust_buy_5d', 'foreign_buy_5d']

    print(f"\n  {'因子':<20s} {'Q1(低)':>8s} {'Q2':>8s} {'Q3':>8s} {'Q4':>8s} {'Q5(高)':>8s} {'Q1-Q5':>8s} {'方向':>6s}")
    print(f"  {'-'*78}")

    for factor in top_factors:
        valid = test_df[[factor, 'ret_5d', 'date']].dropna()
        if len(valid) < 1000:
            continue
        try:
            valid['quintile'] = valid.groupby('date')[factor].transform(
                lambda x: pd.qcut(x.rank(method='first'), 5, labels=[1,2,3,4,5])
            )
        except Exception:
            continue
        valid = valid.dropna(subset=['quintile'])
        q_means = valid.groupby('quintile')['ret_5d'].mean() * 100
        if len(q_means) < 5:
            continue
        spread = q_means.iloc[0] - q_means.iloc[4]
        direction = "買低" if spread > 0 else "買高"
        print(f"  {factor:<20s}", end="")
        for q in range(1, 6):
            if q in q_means.index:
                print(f" {q_means[q]:>+7.3f}%", end="")
            else:
                print(f" {'N/A':>8s}", end="")
        print(f" {spread:>+7.3f}% {direction:>6s}")

    # ══════════════════════════════════════════════════════════════════
    # 3. 均值回歸策略模擬（不用模型，純因子排名）
    # ══════════════════════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("  3. 純因子排名策略（不透過 Logistic Regression）")
    print("=" * 70)

    strategies = [
        ("bias10 最低 20%（超賣反彈）", 'bias10', 'bottom'),
        ("rsi14 最低 20%（超賣反彈）", 'rsi14', 'bottom'),
        ("bb_pctb 最低 20%（布林下緣反彈）", 'bb_pctb', 'bottom'),
        ("vol_ratio 最高 20%（放量突破）", 'vol_ratio', 'top'),
        ("bias10 最低 + vol_ratio 最高（超賣放量）", 'combo_oversold_vol', 'combo'),
    ]

    # 預計算排名
    test_df['bias10_rank'] = test_df.groupby('date')['bias10'].rank(pct=True)
    test_df['rsi14_rank'] = test_df.groupby('date')['rsi14'].rank(pct=True)
    test_df['bb_pctb_rank'] = test_df.groupby('date')['bb_pctb'].rank(pct=True)
    test_df['vol_ratio_rank'] = test_df.groupby('date')['vol_ratio'].rank(pct=True)

    random_wr = (test_df['ret_5d'] > 0).mean() * 100
    random_wr_cost = ((test_df['ret_5d'] - cost) > 0).mean() * 100

    print(f"\n  隨機基準 — 勝率(>0%): {random_wr:.1f}%, 扣成本: {random_wr_cost:.1f}%")
    print(f"  隨機基準 — 平均報酬: {test_df['ret_5d'].mean()*100:+.3f}%\n")

    for name, factor, side in strategies:
        if side == 'combo':
            mask = (test_df['bias10_rank'] <= 0.20) & (test_df['vol_ratio_rank'] >= 0.80)
        elif side == 'bottom':
            mask = test_df[f'{factor}_rank'] <= 0.20
        else:
            mask = test_df[f'{factor}_rank'] >= 0.80

        selected = test_df[mask]
        if len(selected) < 50:
            print(f"  {name}: 樣本不足 ({len(selected)} 筆)")
            continue

        ret_raw = selected['ret_5d']
        ret_net = ret_raw - cost
        wr_raw = (ret_raw > 0).mean() * 100
        wr_net = (ret_net > 0).mean() * 100
        avg_raw = ret_raw.mean() * 100
        avg_net = ret_net.mean() * 100
        n = len(selected)
        t_stat, p_val = stats.ttest_1samp(ret_net.values, 0)

        print(f"  {name}")
        print(f"    N={n:,} | 勝率: {wr_raw:.1f}%(原) {wr_net:.1f}%(扣成本)")
        print(f"    平均報酬: {avg_raw:+.3f}%(原) {avg_net:+.3f}%(扣成本)")
        print(f"    超額勝率: {wr_net - random_wr_cost:+.1f}pp | t={t_stat:.2f} p={p_val:.4f}")
        print()

    # ══════════════════════════════════════════════════════════════════
    # 4. 最佳持有天數掃描（1~10 天）
    # ══════════════════════════════════════════════════════════════════
    print("=" * 70)
    print("  4. 最佳持有天數（bias10 最低 20%，掃描 1~10 天）")
    print("=" * 70)

    df_scan = df.sort_values(['stock_id', 'date']).copy()
    for d in range(1, 11):
        df_scan[f'fwd_{d}'] = df_scan.groupby('stock_id')['close'].shift(-d)
        df_scan[f'ret_{d}'] = (df_scan[f'fwd_{d}'] - df_scan['close'].replace(0, np.nan)) / df_scan['close'].replace(0, np.nan)

    scan_df = df_scan[df_scan['date'] >= test_start].copy()
    scan_df['bias10_rank'] = scan_df.groupby('date')['bias10'].rank(pct=True)
    oversold = scan_df[scan_df['bias10_rank'] <= 0.20]

    print(f"\n  {'天數':>4s} {'平均報酬(原)':>12s} {'平均報酬(扣成本)':>16s} {'勝率(扣成本)':>12s} {'N':>8s}")
    print(f"  {'-'*56}")
    for d in range(1, 11):
        ret_col = f'ret_{d}'
        valid = oversold[ret_col].dropna()
        if len(valid) < 50:
            continue
        avg_raw = valid.mean() * 100
        avg_net = (valid - cost).mean() * 100
        wr_net = ((valid - cost) > 0).mean() * 100
        print(f"  {d:>4d} {avg_raw:>+11.3f}% {avg_net:>+15.3f}% {wr_net:>11.1f}% {len(valid):>8,}")

    # ══════════════════════════════════════════════════════════════════
    # 5. 門檻分析：不同進場嚴格度的影響
    # ══════════════════════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("  5. 進場門檻分析（bias10 排名百分位 vs 報酬）")
    print("=" * 70)

    print(f"\n  {'門檻':>8s} {'平均報酬(扣成本)':>16s} {'勝率(扣成本)':>12s} {'N':>8s} {'t-test p':>10s}")
    print(f"  {'-'*58}")
    for pct in [0.30, 0.20, 0.15, 0.10, 0.05]:
        mask = scan_df['bias10_rank'] <= pct
        selected = scan_df[mask]['ret_5d'].dropna()
        if len(selected) < 30:
            continue
        ret_net = selected - cost
        avg = ret_net.mean() * 100
        wr = (ret_net > 0).mean() * 100
        t, p = stats.ttest_1samp(ret_net.values, 0)
        print(f"  ≤{pct*100:4.0f}% {avg:>+15.3f}% {wr:>11.1f}% {len(selected):>8,} {p:>10.4f}")

    # ══════════════════════════════════════════════════════════════════
    # 6. Strategy Miner 5d 出場原因分析
    # ══════════════════════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("  6. Strategy Miner 5d 交易出場原因分布")
    print("=" * 70)

    from app.models.strategy_miner_trade import StrategyMinerTrade
    db = SessionLocal()
    try:
        trades = db.query(StrategyMinerTrade).filter(
            StrategyMinerTrade.strategy_id == '5d'
        ).all()
        if trades:
            reasons = {}
            returns_by_reason = {}
            for t in trades:
                r = t.exit_reason or 'unknown'
                reasons[r] = reasons.get(r, 0) + 1
                if r not in returns_by_reason:
                    returns_by_reason[r] = []
                returns_by_reason[r].append(t.return_pct)

            total = len(trades)
            print(f"\n  總交易筆數: {total}")
            for reason, count in sorted(reasons.items(), key=lambda x: -x[1]):
                pct = count / total * 100
                rets = returns_by_reason[reason]
                avg = np.mean(rets)
                wr = sum(1 for r in rets if r > 0) / len(rets) * 100
                print(f"    {reason:<15s}: {count:>5d} ({pct:>5.1f}%) | 平均報酬: {avg:>+6.2f}% | 勝率: {wr:.1f}%")
    finally:
        db.close()

    # ══════════════════════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("  結論")
    print("=" * 70)
    print("""
    以上數據回答：
    - 交易成本對 5 日報酬的殺傷力有多大？
    - 不用模型，純因子排名能不能打敗隨機？
    - 最佳持有天數是幾天？
    - 進場門檻要多嚴格才能扣成本後仍獲利？
    - ATR 停損是不是讓太多交易提前出場？
    """)


if __name__ == "__main__":
    main()

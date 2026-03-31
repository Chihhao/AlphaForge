"""
diagnose_alpha_quality.py
─────────────────────────
診斷 Alpha Miner 訊號品質：
  1. 標籤分布 — 各持有期有多少 % 的股票真正上漲超過門檻？
  2. 隨機基準線 — 隨機選股的勝率 vs Strategy Miner 的勝率
  3. 特徵預測力 — 各因子與 forward return 的 Spearman IC
  4. 模型顯著性 — 有多少策略通過 Bonferroni 校正？IC 分布如何？
  5. 過擬合檢測 — in-sample vs out-of-sample 勝率差異
"""
from __future__ import annotations

import logging
import sys
import os
import numpy as np
import pandas as pd
from datetime import date, timedelta
from scipy import stats

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)


def main():
    from app.db.database import engine
    from sqlalchemy import text

    print("=" * 70)
    print("  Alpha Miner 訊號品質診斷")
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
        'foreign_hold_pct', 'foreign_hold_chg_5d', 'etf_net_flow_5d',
        'foreign_buy_10d', 'foreign_buy_20d',
        'trust_buy_10d', 'trust_buy_20d',
        'dealer_buy_10d', 'dealer_buy_20d',
    ]
    cols = ['stock_id', 'date', 'close'] + factor_cols
    sql = text(f"SELECT {', '.join(cols)} FROM stock_features WHERE date >= :cutoff")
    df = pd.read_sql(sql, engine, params={"cutoff": cutoff})
    df['date'] = pd.to_datetime(df['date'])
    print(f"\n載入資料：{len(df):,} 筆，{df['stock_id'].nunique()} 檔股票")
    print(f"日期範圍：{df['date'].min().date()} ~ {df['date'].max().date()}")

    # ── 計算 forward returns ─────────────────────────────────────────
    df = df.sort_values(['stock_id', 'date'])
    for days in [5, 10, 30]:
        df[f'fwd_{days}d'] = df.groupby('stock_id')['close'].shift(-days)
        close = df['close'].replace(0, np.nan)
        df[f'ret_{days}d'] = (df[f'fwd_{days}d'] - close) / close

    # ══════════════════════════════════════════════════════════════════
    # 1. 標籤分布（隨機基準線）
    # ══════════════════════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("  1. 標籤分布 — 全市場有多少比例的股票漲/跌超過門檻？")
    print("=" * 70)

    dims = [
        ("5d",  5,  0.03, 0.05),
        ("10d", 10, 0.03, 0.05),
        ("30d", 30, 0.05, 0.10),
    ]
    for name, days, thr_lo, thr_hi in dims:
        ret_col = f'ret_{days}d'
        valid = df[ret_col].dropna()
        n = len(valid)
        up_lo = (valid > thr_lo).mean() * 100
        up_hi = (valid > thr_hi).mean() * 100
        dn_lo = (valid < -thr_lo).mean() * 100
        dn_hi = (valid < -thr_hi).mean() * 100
        avg_ret = valid.mean() * 100
        med_ret = valid.median() * 100
        print(f"\n  {name} ({days}日報酬，N={n:,}):")
        print(f"    平均報酬: {avg_ret:+.2f}%  中位數: {med_ret:+.2f}%")
        print(f"    ▲ 上漲 > {thr_lo*100:.0f}%: {up_lo:.1f}%   > {thr_hi*100:.0f}%: {up_hi:.1f}%")
        print(f"    ▼ 下跌 > {thr_lo*100:.0f}%: {dn_lo:.1f}%   > {thr_hi*100:.0f}%: {dn_hi:.1f}%")
        print(f"    → 隨機選股做多勝率（>{thr_lo*100:.0f}%）: {up_lo:.1f}%")
        print(f"    → 隨機選股做空勝率（<-{thr_lo*100:.0f}%）: {dn_lo:.1f}%")

    # ══════════════════════════════════════════════════════════════════
    # 2. 特徵預測力 — 各因子與 forward return 的截面 Spearman IC
    # ══════════════════════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("  2. 特徵預測力 — 日均截面 Spearman IC（|IC| > 0.02 才有意義）")
    print("=" * 70)

    # 用測試期（最後 6 個月）的資料
    max_date = df['date'].max()
    test_start = max_date - pd.DateOffset(months=6)

    for name, days, _, _ in dims:
        ret_col = f'ret_{days}d'
        test_df = df[df['date'] >= test_start].copy()
        print(f"\n  {name} 維度（測試期 {test_start.date()} ~ {max_date.date()}）:")
        print(f"  {'因子':<25s} {'平均IC':>8s} {'IC t值':>8s} {'p值':>10s} {'顯著':>4s}")
        print(f"  {'-'*60}")

        ic_results = []
        for factor in factor_cols:
            daily_ics = []
            for _, grp in test_df.groupby('date'):
                valid = grp[[factor, ret_col]].dropna()
                if len(valid) < 30:
                    continue
                if valid[factor].nunique() < 3:
                    continue
                ic_val, _ = stats.spearmanr(valid[factor], valid[ret_col])
                if not np.isnan(ic_val):
                    daily_ics.append(ic_val)

            if len(daily_ics) < 10:
                continue
            mean_ic = np.mean(daily_ics)
            t_stat, p_val = stats.ttest_1samp(daily_ics, 0)
            ic_results.append((factor, mean_ic, t_stat, p_val))

        # 按 |IC| 排序
        ic_results.sort(key=lambda x: abs(x[1]), reverse=True)
        for factor, mean_ic, t_stat, p_val in ic_results[:15]:
            sig = "***" if p_val < 0.001 else "**" if p_val < 0.01 else "*" if p_val < 0.05 else ""
            print(f"  {factor:<25s} {mean_ic:>+8.4f} {t_stat:>8.2f} {p_val:>10.4f} {sig:>4s}")

    # ══════════════════════════════════════════════════════════════════
    # 3. Strategy Miner 實際結果 vs 隨機基準
    # ══════════════════════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("  3. Strategy Miner 回測勝率 vs 隨機基準")
    print("=" * 70)

    from app.models.strategy_backtest_param import StrategyBacktestParam
    from app.models.strategy_miner_trade import StrategyMinerTrade
    from app.db.database import SessionLocal

    db = SessionLocal()
    try:
        for dim_key in ['5d', '10d', '30d']:
            opt = (
                db.query(StrategyBacktestParam)
                .filter(
                    StrategyBacktestParam.strategy_id == dim_key,
                    StrategyBacktestParam.is_optimal == True,
                )
                .first()
            )
            trades = (
                db.query(StrategyMinerTrade)
                .filter(StrategyMinerTrade.strategy_id == dim_key)
                .all()
            )
            if not opt or not trades:
                print(f"\n  {dim_key}: 無資料")
                continue

            returns = [t.return_pct for t in trades]
            win_count = sum(1 for r in returns if r > 0)
            n_trades = len(returns)
            win_rate = win_count / n_trades * 100
            avg_ret = np.mean(returns)
            med_ret = np.median(returns)

            # 對應的隨機基準
            days = int(dim_key.replace('d', ''))
            thr_lo = 0.05 if days == 30 else 0.03
            ret_col = f'ret_{days}d'
            random_valid = df[ret_col].dropna()
            random_win = (random_valid > 0).mean() * 100  # 任何正報酬
            random_win_thr = (random_valid > thr_lo).mean() * 100  # 超過門檻

            print(f"\n  {dim_key} (ATR: TP={opt.take_profit_pct:.1f}× SL={opt.stop_loss_pct:.1f}×):")
            print(f"    策略交易筆數: {n_trades}")
            print(f"    策略勝率（>0%）: {win_rate:.1f}%")
            print(f"    策略平均報酬: {avg_ret:.2f}%  中位數: {med_ret:.2f}%")
            print(f"    隨機基準勝率（>0%）: {random_win:.1f}%")
            print(f"    差距: {win_rate - random_win:+.1f}pp")

            # 統計檢定：策略報酬 vs 0
            t_stat, p_val = stats.ttest_1samp(returns, 0)
            print(f"    報酬 t-test vs 0: t={t_stat:.2f}, p={p_val:.4f}")
    finally:
        db.close()

    # ══════════════════════════════════════════════════════════════════
    # 4. Alpha Miner 模型顯著性統計
    # ══════════════════════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("  4. Alpha Miner 模型品質（從 DB snapshot）")
    print("=" * 70)

    from app.models.alpha_miner_snapshot import AlphaMinerSnapshot
    from app.schemas.alpha_miner import AlphaMinerResult

    db = SessionLocal()
    try:
        snap = db.query(AlphaMinerSnapshot).order_by(
            AlphaMinerSnapshot.train_date.desc()
        ).first()
        if snap:
            result = AlphaMinerResult.model_validate_json(snap.result_json)
            print(f"\n  訓練日期: {snap.train_date}")
            print(f"  訓練期: {result.train_period}")
            print(f"  測試期: {result.test_period}")
            print(f"  Bonferroni 門檻: {result.bonferroni_threshold:.6f}")

            for dim_key in ['5d', '10d', '30d', '5d_short', '10d_short', '30d_short']:
                dim_strategies = [s for s in result.strategies if s.time_dimension == dim_key]
                sig_strategies = [s for s in dim_strategies if s.is_significant]
                overfit = [s for s in dim_strategies if s.overfit_warning]

                if not dim_strategies:
                    continue

                ics = [s.ic for s in dim_strategies]
                sig_ics = [s.ic for s in sig_strategies]

                print(f"\n  {dim_key}:")
                print(f"    策略總數: {len(dim_strategies)}, 顯著: {len(sig_strategies)}, 過擬合警告: {len(overfit)}")
                print(f"    IC 分布: mean={np.mean(ics):.4f}, std={np.std(ics):.4f}, "
                      f"min={np.min(ics):.4f}, max={np.max(ics):.4f}")
                if sig_strategies:
                    print(f"    顯著策略 IC: mean={np.mean(sig_ics):.4f}, "
                          f"range=[{np.min(sig_ics):.4f}, {np.max(sig_ics):.4f}]")
                    # 顯著策略的 win rate
                    win_rates = [s.win_rate_outsample for s in sig_strategies]
                    mkt_rates = [s.market_win_rate for s in sig_strategies]
                    print(f"    顯著策略勝率: mean={np.mean(win_rates):.1%}, "
                          f"市場基準: {np.mean(mkt_rates):.1%}, "
                          f"超額: {np.mean(win_rates) - np.mean(mkt_rates):+.1%}")
        else:
            print("  無 snapshot 資料")
    finally:
        db.close()

    # ══════════════════════════════════════════════════════════════════
    # 5. 結論
    # ══════════════════════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("  5. 診斷結論")
    print("=" * 70)
    print("""
    上述數據回答以下關鍵問題：

    Q1: 策略勝率 vs 隨機選股差多少？
        → 如果差距 < 3pp，Alpha 訊號幾乎沒有預測力

    Q2: 哪些因子有真正的預測力？
        → |IC| > 0.02 且 p < 0.05 的因子才值得保留

    Q3: 換 LightGBM 有意義嗎？
        → 如果個別因子有 IC 但組合模型沒改善 → 非線性交互可能有用
        → 如果個別因子 IC 都接近 0 → 換模型也沒用，需要更好的特徵
    """)
    print("=" * 70)


if __name__ == "__main__":
    main()

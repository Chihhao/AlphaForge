"""Diagnostic: 若繞過 quality gate, 2026-01-30 ~ 04-17 的 20d long 實際勝率多少?

邏輯:
  1. 按 14 天 checkpoint 重跑 _optimize_dimension 拿 walk-forward 對齊的 tp/sl/hd
  2. 跳過 win_rate_test < baseline+5pp 的整 dim 阻擋
  3. 每個 signal_date 依當前流程選 Top5 (trigger_count >= P70, score 排序)
  4. 以當日收盤為 entry_price, 用 hd 個交易日的 forward prices 模擬 tp/sl/time_limit
  5. 統計真實勝率 vs 每個 checkpoint 的 wr_test 預測

輸出: 每 checkpoint 的 n/wr/avg_return, 以及整體彙總
不寫入 strategy_miner_picks (read-only simulation)
"""
from __future__ import annotations
import os
import sys
from collections import Counter
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.database import SessionLocal
from app.services.strategy_miner_service import StrategyMinerService
from app.models.alpha_signal_history import AlphaSignalHistory
from app.models.strategy_backtest_param import StrategyBacktestParam
from app.models.stock_price import StockPrice
from app.models.stock_feature import StockFeature


CHECKPOINTS = [
    date(2026, 1, 30),
    date(2026, 2, 13),
    date(2026, 2, 27),
    date(2026, 3, 13),
    date(2026, 3, 27),
    date(2026, 4, 10),
]
RANGE_END = date(2026, 4, 18)
MAX_PICKS = 5
TRIGGER_PCT = 0.70


def simulate_pick(db, stock_id: str, signal_date: date, tp_mult: float,
                  sl_mult: float, hd: int):
    entry_row = (
        db.query(StockPrice.close)
        .filter(StockPrice.stock_id == stock_id, StockPrice.date == signal_date)
        .first()
    )
    if not entry_row or not entry_row.close:
        return None
    entry = float(entry_row.close)
    atr_row = (
        db.query(StockFeature.atr20)
        .filter(StockFeature.stock_id == stock_id, StockFeature.date == signal_date)
        .first()
    )
    if atr_row and atr_row.atr20:
        tp_pct = tp_mult * atr_row.atr20 / entry
        sl_pct = sl_mult * atr_row.atr20 / entry
    else:
        tp_pct = tp_mult * 0.03
        sl_pct = sl_mult * 0.03
    tp_level = entry * (1 + tp_pct)
    sl_level = entry * (1 - sl_pct)
    forward = (
        db.query(StockPrice)
        .filter(StockPrice.stock_id == stock_id, StockPrice.date > signal_date)
        .order_by(StockPrice.date)
        .limit(hd)
        .all()
    )
    if not forward:
        return None
    for j, fp in enumerate(forward, 1):
        if fp.high >= tp_level:
            return {'outcome': 'tp', 'ret': (tp_level - entry) / entry * 100, 'exit_day': j}
        if fp.low <= sl_level:
            return {'outcome': 'sl', 'ret': (sl_level - entry) / entry * 100, 'exit_day': j}
    last = forward[-1]
    return {'outcome': 'time_limit', 'ret': (last.close - entry) / entry * 100, 'exit_day': len(forward)}


def main():
    db = SessionLocal()
    all_results = []
    cp_summary = []
    try:
        for i, cp in enumerate(CHECKPOINTS):
            StrategyMinerService._optimize_dimension(db, '20d', 'long', as_of_date=cp)
            opt = (
                db.query(StrategyBacktestParam)
                .filter_by(strategy_id='20d', is_optimal=True)
                .first()
            )
            if not opt:
                print(f'cp={cp} no optimal')
                continue
            tp_mult = opt.take_profit_pct
            sl_mult = opt.stop_loss_pct
            hd = opt.hold_days_max
            wr_test_pred = opt.win_rate_test
            range_end = CHECKPOINTS[i + 1] if i + 1 < len(CHECKPOINTS) else RANGE_END

            signal_dates = (
                db.query(AlphaSignalHistory.signal_date)
                .filter(
                    AlphaSignalHistory.signal_date >= cp,
                    AlphaSignalHistory.signal_date < range_end,
                    AlphaSignalHistory.time_dimension == '20d',
                    AlphaSignalHistory.direction == 'long',
                )
                .distinct()
                .order_by(AlphaSignalHistory.signal_date)
                .all()
            )
            cp_results = []
            for (d,) in signal_dates:
                rows = (
                    db.query(AlphaSignalHistory)
                    .filter(
                        AlphaSignalHistory.signal_date == d,
                        AlphaSignalHistory.time_dimension == '20d',
                        AlphaSignalHistory.direction == 'long',
                    )
                    .all()
                )
                if not rows:
                    continue
                # dedup by stock_id keep max trigger_count
                by_stock = {}
                for r in rows:
                    e = by_stock.get(r.stock_id)
                    if e is None or r.trigger_count > e.trigger_count:
                        by_stock[r.stock_id] = r
                rows = list(by_stock.values())
                counts = sorted(r.trigger_count for r in rows)
                if not counts:
                    continue
                p70 = counts[min(int(len(counts) * TRIGGER_PCT), len(counts) - 1)]
                rows = [r for r in rows if r.trigger_count >= p70]
                rows.sort(key=lambda r: r.trigger_count * (r.weighted_odds_ratio or 1.0),
                          reverse=True)
                picks = rows[:MAX_PICKS]
                for r in picks:
                    res = simulate_pick(db, r.stock_id, d, tp_mult, sl_mult, hd)
                    if res is None:
                        continue
                    res['cp'] = cp
                    res['d'] = d
                    res['stock_id'] = r.stock_id
                    cp_results.append(res)

            if cp_results:
                n = len(cp_results)
                wins = sum(1 for r in cp_results if r['ret'] > 0)
                avg = sum(r['ret'] for r in cp_results) / n
                cp_summary.append({
                    'cp': cp,
                    'wr_test_pred': wr_test_pred,
                    'n': n,
                    'wr_actual': wins / n,
                    'avg_ret': avg,
                    'outcomes': Counter(r['outcome'] for r in cp_results),
                })
                all_results.extend(cp_results)

        print('\n=== Per-checkpoint ===')
        print(f"{'cp':12} {'wr_test_pred':>13} {'n':>4} {'wr_actual':>10} {'avg_ret%':>10}  outcomes")
        for s in cp_summary:
            print(
                f"{str(s['cp']):12} {s['wr_test_pred']:>13.4f} {s['n']:>4} "
                f"{s['wr_actual']:>10.3f} {s['avg_ret']:>10.2f}  {dict(s['outcomes'])}"
            )

        if all_results:
            n = len(all_results)
            wins = sum(1 for r in all_results if r['ret'] > 0)
            avg = sum(r['ret'] for r in all_results) / n
            oc = Counter(r['outcome'] for r in all_results)
            print('\n=== Overall (bypass gate, 2026-01-30 ~ 2026-04-17) ===')
            print(f'n={n} wr_actual={wins/n:.3f} avg_ret={avg:.2f}%')
            print(f'outcomes={dict(oc)}')
    finally:
        db.rollback()
        db.close()


if __name__ == '__main__':
    main()

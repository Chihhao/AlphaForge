"""
驗證：訊號推薦 vs 主流標的（0050、2330 台積電），各維度勝率差異

用「同一天買 0050 / 台積電，持有同樣天數」當基準，
看訊號推薦到底有沒有比直接買大盤 ETF / 權值股好。
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.database import SessionLocal
from app.models.alpha_signal_history import AlphaSignalHistory
from app.models.stock_price import StockPrice
from collections import defaultdict
import logging

logging.disable(logging.CRITICAL)

HOLD_MAP = {'5d': 5, '10d': 10, '30d': 30}
BENCHMARKS = ['0050', '2330']


def run():
    db = SessionLocal()

    signals = db.query(AlphaSignalHistory).filter(
        AlphaSignalHistory.is_resolved == True
    ).all()

    # 載入所有股價
    print("載入股價資料...")
    price_map = {}
    stock_dates_map = defaultdict(list)
    rows = db.query(StockPrice.stock_id, StockPrice.date, StockPrice.open, StockPrice.close).all()
    for r in rows:
        price_map[(r.stock_id, r.date)] = {'open': r.open, 'close': r.close}
        stock_dates_map[r.stock_id].append(r.date)
    for sid in stock_dates_map:
        stock_dates_map[sid].sort()
    db.close()

    def get_trading_day(sid, base_date, offset):
        dates = stock_dates_map.get(sid, [])
        try:
            idx = dates.index(base_date)
            target = idx + offset
            if 0 <= target < len(dates):
                return dates[target]
        except ValueError:
            pass
        return None

    for dim in ['5d', '10d', '30d']:
        hold = HOLD_MAP[dim]
        dim_signals = [s for s in signals if s.time_dimension == dim]

        # 訊號組
        sig_wins = 0
        sig_total = 0
        sig_returns = []

        # 基準組（每個 benchmark 各自統計）
        bench_stats = {b: {'wins': 0, 'total': 0, 'returns': []} for b in BENCHMARKS}

        for s in dim_signals:
            sid = s.stock_id
            sig_date = s.signal_date

            # 訊號：隔日開盤進場
            next_day = get_trading_day(sid, sig_date, 1)
            if not next_day:
                continue
            entry_open = price_map.get((sid, next_day), {}).get('open')
            if not entry_open:
                continue
            exit_day = get_trading_day(sid, sig_date, hold)
            if not exit_day:
                continue
            exit_close = price_map.get((sid, exit_day), {}).get('close')
            if not exit_close:
                continue

            ret = (exit_close - entry_open) / entry_open * 100
            sig_returns.append(ret)
            sig_total += 1
            if ret > 0:
                sig_wins += 1

            # 基準：同一天買 benchmark，同樣持有天數，隔日開盤進場
            for b in BENCHMARKS:
                b_next = get_trading_day(b, sig_date, 1)
                if not b_next:
                    continue
                b_entry = price_map.get((b, b_next), {}).get('open')
                if not b_entry:
                    continue
                b_exit_day = get_trading_day(b, sig_date, hold)
                if not b_exit_day:
                    continue
                b_exit = price_map.get((b, b_exit_day), {}).get('close')
                if not b_exit:
                    continue

                b_ret = (b_exit - b_entry) / b_entry * 100
                bench_stats[b]['returns'].append(b_ret)
                bench_stats[b]['total'] += 1
                if b_ret > 0:
                    bench_stats[b]['wins'] += 1

        sig_wr = sig_wins / sig_total * 100 if sig_total else 0
        sig_avg = sum(sig_returns) / len(sig_returns) if sig_returns else 0

        print(f"\n{'='*64}")
        print(f"  {dim} 維度（持有 {hold} 天，隔日開盤價進場）")
        print(f"{'='*64}")
        print(f"  {'':>14} {'勝率':>8} {'平均報酬':>10} {'筆數':>8}")
        print(f"  {'訊號推薦':>12} {sig_wr:>7.1f}% {sig_avg:>+9.2f}% {sig_total:>7}")

        for b in BENCHMARKS:
            bs = bench_stats[b]
            b_wr = bs['wins'] / bs['total'] * 100 if bs['total'] else 0
            b_avg = sum(bs['returns']) / len(bs['returns']) if bs['returns'] else 0
            alpha_wr = sig_wr - b_wr
            alpha_ret = sig_avg - b_avg
            label = f"買 {b}"
            print(f"  {label:>12} {b_wr:>7.1f}% {b_avg:>+9.2f}% {bs['total']:>7}")
            print(f"  {'Alpha vs '+b:>14} {alpha_wr:>+7.1f}% {alpha_ret:>+9.2f}%")

        print(f"  {'-'*50}")


if __name__ == "__main__":
    run()

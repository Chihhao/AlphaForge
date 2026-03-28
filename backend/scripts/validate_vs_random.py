"""
驗證：訊號推薦 vs 隨機買入，各維度的勝率差異

對每筆訊號的同一天，隨機抽 5 檔其他股票，用同樣持有天數算勝率，
作為「大盤基準」。如果訊號勝率跟隨機差不多，代表預測沒有 alpha。
"""

import sys, os, random
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.database import SessionLocal
from app.models.alpha_signal_history import AlphaSignalHistory
from app.models.stock_price import StockPrice
from collections import defaultdict
import logging

logging.disable(logging.CRITICAL)

HOLD_MAP = {'5d': 5, '10d': 10, '30d': 30}
RANDOM_SAMPLES = 5  # 每筆訊號抽幾檔對照

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

    # 建立「每個交易日有哪些股票有資料」的反向索引
    date_stocks = defaultdict(list)
    for (sid, d) in price_map:
        date_stocks[d].append(sid)

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

    random.seed(42)

    for dim in ['5d', '10d', '30d']:
        hold = HOLD_MAP[dim]
        dim_signals = [s for s in signals if s.time_dimension == dim]

        # 訊號組（用隔日開盤進場）
        sig_wins = 0
        sig_total = 0
        sig_returns = []

        # 隨機組（同日期、同持有天數、用隔日開盤進場）
        rnd_wins = 0
        rnd_total = 0
        rnd_returns = []

        for s in dim_signals:
            sid = s.stock_id
            sig_date = s.signal_date

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

            # 隨機對照：從同一天有資料的股票中抽樣
            available = [x for x in date_stocks.get(sig_date, []) if x != sid]
            samples = random.sample(available, min(RANDOM_SAMPLES, len(available)))
            for rsid in samples:
                r_next = get_trading_day(rsid, sig_date, 1)
                if not r_next:
                    continue
                r_entry = price_map.get((rsid, r_next), {}).get('open')
                if not r_entry:
                    continue
                r_exit_day = get_trading_day(rsid, sig_date, hold)
                if not r_exit_day:
                    continue
                r_exit = price_map.get((rsid, r_exit_day), {}).get('close')
                if not r_exit:
                    continue

                r_ret = (r_exit - r_entry) / r_entry * 100
                rnd_returns.append(r_ret)
                rnd_total += 1
                if r_ret > 0:
                    rnd_wins += 1

        sig_wr = sig_wins / sig_total * 100 if sig_total else 0
        sig_avg = sum(sig_returns) / len(sig_returns) if sig_returns else 0
        rnd_wr = rnd_wins / rnd_total * 100 if rnd_total else 0
        rnd_avg = sum(rnd_returns) / len(rnd_returns) if rnd_returns else 0

        alpha_wr = sig_wr - rnd_wr
        alpha_ret = sig_avg - rnd_avg

        print(f"\n{'='*60}")
        print(f"  {dim} 維度（持有 {hold} 天，隔日開盤價進場）")
        print(f"{'='*60}")
        print(f"  {'':>12} {'勝率':>8} {'平均報酬':>10} {'筆數':>8}")
        print(f"  {'訊號推薦':>10} {sig_wr:>7.1f}% {sig_avg:>+9.2f}% {sig_total:>7}")
        print(f"  {'隨機買入':>10} {rnd_wr:>7.1f}% {rnd_avg:>+9.2f}% {rnd_total:>7}")
        print(f"  {'-'*46}")
        print(f"  {'Alpha':>10} {alpha_wr:>+7.1f}% {alpha_ret:>+9.2f}%")
        if alpha_wr > 0:
            print(f"  → 訊號比亂買好 {alpha_wr:.1f}%，有預測力")
        else:
            print(f"  → 訊號沒比亂買好，預測力不足")


if __name__ == "__main__":
    run()

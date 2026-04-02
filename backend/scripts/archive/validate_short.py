"""
驗證：放空潛力 — 系統推薦的 vs 沒推薦的，誰比較容易跌？

邏輯：
  每個訊號日，把股票分兩組：
    A) 系統推薦的（有出現在 alpha_signal_history）
    B) 沒推薦的（同一天有交易但未被推薦）
  比較兩組的下跌率（放空勝率 = 股價下跌的比例）

  如果 B 組下跌率明顯高於 A 組，代表系統能區分漲跌，
  沒推薦的可以當放空名單。
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
# 每個訊號日從未推薦股票中抽樣（控制計算量）
SAMPLE_PER_DAY = 30


def run():
    db = SessionLocal()

    signals = db.query(AlphaSignalHistory).filter(
        AlphaSignalHistory.is_resolved == True
    ).all()

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

    # 每個交易日有哪些股票
    date_stocks = defaultdict(set)
    for (sid, d) in price_map:
        date_stocks[d].add(sid)

    # 每個 (維度, 日期) 推薦了哪些股票
    signal_map = defaultdict(set)  # (dim, date) -> set of stock_ids
    for s in signals:
        signal_map[(s.time_dimension, s.signal_date)].add(s.stock_id)

    # 收集所有訊號日期（per dim）
    dim_dates = defaultdict(set)
    for s in signals:
        dim_dates[s.time_dimension].add(s.signal_date)

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

    def calc_return(sid, sig_date, hold):
        """隔日開盤買，持有 hold 天後收盤賣"""
        next_day = get_trading_day(sid, sig_date, 1)
        if not next_day:
            return None
        entry = price_map.get((sid, next_day), {}).get('open')
        if not entry or entry <= 0:
            return None
        exit_day = get_trading_day(sid, sig_date, hold)
        if not exit_day:
            return None
        exit_p = price_map.get((sid, exit_day), {}).get('close')
        if not exit_p:
            return None
        return (exit_p - entry) / entry * 100

    random.seed(42)

    for dim in ['5d', '10d', '30d']:
        hold = HOLD_MAP[dim]
        dates = sorted(dim_dates[dim])

        rec_returns = []     # 推薦組
        not_rec_returns = [] # 未推薦組

        for d in dates:
            rec_ids = signal_map[(dim, d)]
            all_ids = date_stocks.get(d, set())
            not_rec_ids = all_ids - rec_ids

            # 推薦組
            for sid in rec_ids:
                ret = calc_return(sid, d, hold)
                if ret is not None:
                    rec_returns.append(ret)

            # 未推薦組（抽樣）
            sample = random.sample(list(not_rec_ids), min(SAMPLE_PER_DAY, len(not_rec_ids)))
            for sid in sample:
                ret = calc_return(sid, d, hold)
                if ret is not None:
                    not_rec_returns.append(ret)

        # 統計
        rec_up = sum(1 for r in rec_returns if r > 0)
        rec_down = sum(1 for r in rec_returns if r <= 0)
        rec_wr = rec_up / len(rec_returns) * 100 if rec_returns else 0
        rec_avg = sum(rec_returns) / len(rec_returns) if rec_returns else 0

        nr_up = sum(1 for r in not_rec_returns if r > 0)
        nr_down = sum(1 for r in not_rec_returns if r <= 0)
        nr_wr = nr_up / len(not_rec_returns) * 100 if not_rec_returns else 0
        nr_avg = sum(not_rec_returns) / len(not_rec_returns) if not_rec_returns else 0

        # 放空勝率 = 股價下跌的比例
        short_rec = rec_down / len(rec_returns) * 100 if rec_returns else 0
        short_nr = nr_down / len(not_rec_returns) * 100 if not_rec_returns else 0

        print(f"\n{'='*64}")
        print(f"  {dim} 維度（持有 {hold} 天，隔日開盤價進場）")
        print(f"{'='*64}")
        print(f"  {'':>14} {'做多勝率':>8} {'放空勝率':>8} {'平均報酬':>10} {'筆數':>8}")
        print(f"  {'有推薦':>12} {rec_wr:>7.1f}% {short_rec:>7.1f}% {rec_avg:>+9.2f}% {len(rec_returns):>7}")
        print(f"  {'沒推薦':>12} {nr_wr:>7.1f}% {short_nr:>7.1f}% {nr_avg:>+9.2f}% {len(not_rec_returns):>7}")
        print(f"  {'-'*50}")

        sep = short_nr - short_rec
        if sep > 5:
            print(f"  → 沒推薦的放空勝率高出 {sep:.1f}%，有區分能力，值得發展放空訊號")
        elif sep > 0:
            print(f"  → 沒推薦的放空勝率只高 {sep:.1f}%，區分能力偏弱")
        else:
            print(f"  → 沒推薦的甚至不太跌，沒有放空價值")


if __name__ == "__main__":
    run()

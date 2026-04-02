"""
驗證：用隔日開盤價 vs 當日收盤價當進場價，各維度勝率差異

邏輯：
  - 取所有已結算訊號
  - 對每筆訊號找出：
      A) 當日收盤價（目前回測用的進場價）
      B) 隔日開盤價（用戶實際能買到的價格）
  - 用各維度的持有天數，取出場價（持有期最後一天收盤價）
  - 比較兩種進場價的勝率
  - 額外模擬 1d 維度（隔日開盤買、隔日收盤賣）
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.database import SessionLocal
from app.models.alpha_signal_history import AlphaSignalHistory
from app.models.stock_price import StockPrice
from sqlalchemy import and_
from collections import defaultdict
import logging

logging.disable(logging.CRITICAL)  # 關閉 SQLAlchemy 日誌

HOLD_MAP = {'5d': 5, '10d': 10, '30d': 30}

def run():
    db = SessionLocal()

    # 1) 載入所有已結算訊號
    signals = db.query(AlphaSignalHistory).filter(
        AlphaSignalHistory.is_resolved == True
    ).all()
    print(f"已結算訊號總數: {len(signals)}")

    # 2) 收集所有需要的 (stock_id, date) 組合
    stock_ids = set()
    for s in signals:
        stock_ids.add(s.stock_id)

    # 3) 批次載入所有相關股價（按 stock_id 分組）
    print("載入股價資料...")
    price_map = {}  # (stock_id, date) -> {open, close}
    for sid in stock_ids:
        rows = db.query(StockPrice.date, StockPrice.open, StockPrice.close).filter(
            StockPrice.stock_id == sid
        ).order_by(StockPrice.date).all()
        for r in rows:
            price_map[(sid, r.date)] = {'open': r.open, 'close': r.close}

    # 建立每檔股票的交易日清單（排序）
    stock_dates = defaultdict(list)
    for (sid, d) in price_map:
        stock_dates[sid].append(d)
    for sid in stock_dates:
        stock_dates[sid].sort()

    def get_trading_day(sid, base_date, offset):
        """取得 base_date 之後第 offset 個交易日"""
        dates = stock_dates[sid]
        try:
            idx = dates.index(base_date)
            target_idx = idx + offset
            if 0 <= target_idx < len(dates):
                return dates[target_idx]
        except ValueError:
            pass
        return None

    # 4) 各維度 + 1d 模擬
    dims_to_test = ['5d', '10d', '30d', '1d']
    results = {}

    for dim in dims_to_test:
        hold = HOLD_MAP.get(dim, 1)
        close_wins = 0
        close_total = 0
        close_returns = []
        open_wins = 0
        open_total = 0
        open_returns = []

        source_dim = dim if dim != '1d' else '5d'  # 1d 用 5d 的訊號來模擬

        dim_signals = [s for s in signals if s.time_dimension == source_dim]

        for s in dim_signals:
            sid = s.stock_id
            sig_date = s.signal_date

            # 當日收盤價
            entry_close = price_map.get((sid, sig_date), {}).get('close')
            if not entry_close:
                continue

            # 隔日
            next_day = get_trading_day(sid, sig_date, 1)
            if not next_day:
                continue
            next_data = price_map.get((sid, next_day))
            if not next_data:
                continue
            entry_open = next_data['open']

            # 出場日
            exit_day = get_trading_day(sid, sig_date, hold)
            if not exit_day:
                continue
            exit_close = price_map.get((sid, exit_day), {}).get('close')
            if not exit_close:
                continue

            if dim == '1d':
                # 1d: 隔日開盤買 → 隔日收盤賣
                exit_price_for_1d = next_data['close']
                ret_open = (exit_price_for_1d - entry_open) / entry_open * 100
                open_returns.append(ret_open)
                open_total += 1
                if ret_open > 0:
                    open_wins += 1

                ret_close = (exit_price_for_1d - entry_close) / entry_close * 100
                close_returns.append(ret_close)
                close_total += 1
                if ret_close > 0:
                    close_wins += 1
            else:
                # A) 收盤價進場
                ret_close = (exit_close - entry_close) / entry_close * 100
                close_returns.append(ret_close)
                close_total += 1
                if ret_close > 0:
                    close_wins += 1

                # B) 隔日開盤價進場
                ret_open = (exit_close - entry_open) / entry_open * 100
                open_returns.append(ret_open)
                open_total += 1
                if ret_open > 0:
                    open_wins += 1

        avg_close = sum(close_returns) / len(close_returns) if close_returns else 0
        avg_open = sum(open_returns) / len(open_returns) if open_returns else 0

        results[dim] = {
            'close_win_rate': close_wins / close_total * 100 if close_total else 0,
            'close_avg_return': avg_close,
            'close_total': close_total,
            'open_win_rate': open_wins / open_total * 100 if open_total else 0,
            'open_avg_return': avg_open,
            'open_total': open_total,
        }

    db.close()

    # 5) 輸出結果
    print("\n" + "=" * 72)
    print("     用收盤價進場 (回測假設)    vs    用隔日開盤價進場 (實際情況)")
    print("=" * 72)
    print(f"{'維度':>4}  {'勝率':>7} {'平均報酬':>8} {'筆數':>6}  │  {'勝率':>7} {'平均報酬':>8} {'筆數':>6}  │ {'勝率差':>6}")
    print("-" * 72)
    for dim in dims_to_test:
        r = results[dim]
        diff = r['open_win_rate'] - r['close_win_rate']
        print(f"{dim:>4}  {r['close_win_rate']:>6.1f}% {r['close_avg_return']:>+7.2f}% {r['close_total']:>5}  │  "
              f"{r['open_win_rate']:>6.1f}% {r['open_avg_return']:>+7.2f}% {r['open_total']:>5}  │ {diff:>+5.1f}%")
    print("=" * 72)
    print("\n說明:")
    print("  收盤價進場 = 訊號當天收盤買入（回測假設，實際買不到）")
    print("  隔日開盤進場 = 隔天開盤買入（用戶實際能買到的價格）")
    print("  1d = 用 5d 訊號，但隔天開盤買、隔天收盤賣（模擬當沖）")


if __name__ == "__main__":
    run()

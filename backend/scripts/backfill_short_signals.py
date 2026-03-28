"""
回補歷史放空訊號至 alpha_signal_history

對每個有 long 訊號的日期，從 stock_features 找當天滿足看空條件的股票，
寫入 direction='short' 的訊號。完成後即可 run_all 對 short 維度尋優。
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
logging.getLogger('sqlalchemy').setLevel(logging.WARNING)

from app.db.database import SessionLocal
from app.models.alpha_signal_history import AlphaSignalHistory
from app.models.stock_feature import StockFeature
from sqlalchemy import func, distinct

# 看空條件（與 alpha_miner_service._get_short_signals 一致）
MIN_BEARISH_CONDITIONS = 3


def score_features(f) -> tuple:
    """回傳 (score, reasons)"""
    score = 0
    reasons = []
    if f.rsi14 is not None and f.rsi14 > 70:
        score += 1; reasons.append('RSI超買')
    if f.k is not None and f.d is not None and f.k > 80 and f.k < f.d:
        score += 1; reasons.append('KD高檔死叉')
    if f.macd_osc is not None and f.macd_osc < 0:
        score += 1; reasons.append('MACD空頭')
    if f.bias20 is not None and f.bias20 > 5:
        score += 1; reasons.append('乖離率偏高')
    if hasattr(f, 'foreign_buy_5d') and f.foreign_buy_5d is not None and f.foreign_buy_5d < 0:
        score += 1; reasons.append('外資賣超')
    if hasattr(f, 'trust_buy_5d') and f.trust_buy_5d is not None and f.trust_buy_5d < 0:
        score += 1; reasons.append('投信賣超')
    return score, reasons


def run():
    db = SessionLocal()

    # 找出所有有 long 訊號的日期
    signal_dates = [
        row[0] for row in
        db.query(distinct(AlphaSignalHistory.signal_date))
        .filter(AlphaSignalHistory.direction == 'long')
        .order_by(AlphaSignalHistory.signal_date)
        .all()
    ]
    print(f"共 {len(signal_dates)} 個訊號日期需要回補放空訊號")

    # 已有 short 訊號的日期（跳過）
    existing_short_dates = set(
        row[0] for row in
        db.query(distinct(AlphaSignalHistory.signal_date))
        .filter(AlphaSignalHistory.direction == 'short')
        .all()
    )

    # 查股票名稱快取
    from app.models.user import Stock as StockModel
    name_map = {
        r.stock_id: r.stock_name
        for r in db.query(StockModel.stock_id, StockModel.stock_name).all()
    }

    total_written = 0
    for i, sig_date in enumerate(signal_dates):
        if sig_date in existing_short_dates:
            continue

        # 找該日期最近的 stock_features 日期（features 可能比訊號日早 1 天）
        feat_date = (
            db.query(func.max(StockFeature.date))
            .filter(StockFeature.date <= sig_date)
            .scalar()
        )
        if not feat_date:
            continue

        features = db.query(StockFeature).filter(StockFeature.date == feat_date).all()

        candidates = []
        for f in features:
            score, reasons = score_features(f)
            if score >= MIN_BEARISH_CONDITIONS:
                candidates.append((f.stock_id, score, reasons))

        # 取前 20 個
        candidates.sort(key=lambda x: x[1], reverse=True)
        candidates = candidates[:20]

        rows = []
        for stock_id, score, reasons in candidates:
            # 各維度都寫一筆
            for dim in ['5d', '10d', '30d']:
                rows.append(AlphaSignalHistory(
                    signal_date=sig_date,
                    stock_id=stock_id,
                    stock_name=name_map.get(stock_id, stock_id),
                    time_dimension=dim,
                    direction='short',
                    trigger_count=score,
                    weighted_win_rate=0.5,
                    weighted_odds_ratio=float(score),
                ))

        if rows:
            db.add_all(rows)
            db.commit()
            total_written += len(rows)

        if (i + 1) % 20 == 0 or i == len(signal_dates) - 1:
            print(f"  進度 {i+1}/{len(signal_dates)} — 累計寫入 {total_written} 筆")

    print(f"\n回補完成：共寫入 {total_written} 筆放空訊號")

    # 統計
    for dim in ['5d', '10d', '30d']:
        cnt = db.query(func.count(AlphaSignalHistory.id)).filter(
            AlphaSignalHistory.direction == 'short',
            AlphaSignalHistory.time_dimension == dim,
        ).scalar()
        print(f"  {dim}_short: {cnt} 筆")

    db.close()


if __name__ == "__main__":
    run()

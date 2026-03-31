"""
backfill_rsi2.py — 輕量回補 RSI(2) 至 stock_features 表
用 pandas.to_sql 寫入 temp table + 單次 JOIN UPDATE 加速。
"""
from __future__ import annotations
import logging, sys, os
import numpy as np, pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)


def main():
    from app.db.database import engine
    from sqlalchemy import text

    logger.info("=== RSI(2) 回補開始 ===")

    # 1. 找出需要回補的日期範圍
    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT MIN(date), MAX(date), COUNT(*) FROM stock_features WHERE rsi2 IS NULL"
        )).fetchone()
        null_min, null_max, null_count = row
        logger.info(f"待回補: {null_count:,} 筆 ({null_min} ~ {null_max})")

        if null_count == 0:
            logger.info("無需回補")
            return

    # 2. 讀取 stock_prices（含暖機期）
    warmup_start = (pd.Timestamp(null_min) - pd.DateOffset(days=30)).strftime('%Y-%m-%d')
    df = pd.read_sql(text(
        "SELECT stock_id, date, close FROM stock_prices WHERE date >= :start ORDER BY stock_id, date"
    ), engine, params={"start": warmup_start})

    logger.info(f"讀取 stock_prices: {len(df):,} 筆")
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values(['stock_id', 'date'])

    # 3. 向量化計算 RSI(2)
    def rsi_logic(s):
        delta = s.diff()
        up = delta.clip(lower=0)
        down = -1 * delta.clip(upper=0)
        ema_up = up.ewm(com=1, adjust=False).mean()
        ema_down = down.ewm(com=1, adjust=False).mean()
        rs = ema_up / ema_down
        return 100 - (100 / (1 + rs))

    df['rsi2'] = df.groupby('stock_id')['close'].transform(rsi_logic)

    # 4. 過濾到需要更新的範圍
    df = df[(df['date'] >= pd.Timestamp(null_min)) & (df['date'] <= pd.Timestamp(null_max))]
    df = df.dropna(subset=['rsi2'])
    update_df = df[['stock_id', 'date', 'rsi2']].copy()
    update_df['date'] = update_df['date'].dt.date
    logger.info(f"計算完成: {len(update_df):,} 筆待寫入")

    # 5. 用 pandas.to_sql 寫入 temp table（比逐行 INSERT 快 100 倍）
    logger.info("寫入 temp table...")
    with engine.connect() as conn:
        conn.execute(text("DROP TABLE IF EXISTS _tmp_rsi2"))
        conn.commit()

    update_df.to_sql('_tmp_rsi2', engine, if_exists='replace', index=False, method='multi', chunksize=10000)
    logger.info("Temp table 寫入完成")

    # 6. 建索引加速 JOIN
    with engine.connect() as conn:
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_tmp_rsi2 ON _tmp_rsi2 (stock_id, date)"))
        conn.commit()
    logger.info("索引建立完成")

    # 7. 單次 JOIN UPDATE
    logger.info("執行 UPDATE...")
    with engine.connect() as conn:
        result = conn.execute(text("""
            UPDATE stock_features sf
            SET rsi2 = t.rsi2
            FROM _tmp_rsi2 t
            WHERE sf.stock_id = t.stock_id
              AND sf.date = t.date
              AND sf.rsi2 IS NULL
        """))
        updated = result.rowcount
        conn.execute(text("DROP TABLE IF EXISTS _tmp_rsi2"))
        conn.commit()

    logger.info(f"=== RSI(2) 回補完成: {updated:,} 筆已更新 ===")


if __name__ == "__main__":
    main()

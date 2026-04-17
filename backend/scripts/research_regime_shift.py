"""驗證 train period 與 test period 的 market_wr 差異（research only）。

目的：檢查 overfit_warning flag 判定（wr_in vs wr_out 差異 > 5pp）是否被
market regime shift 污染。若 train/test period 的全市場 P(ret>3%) 差距
> 5pp，則絕對勝率差不是乾淨的模型穩定性信號。

- 不跑訓練、不寫 DB、不改 production
- 用跟 AlphaMinerService._train_all 同樣的 split 邏輯
- 同樣的股票 regex 過濾（上市 4 碼）
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

try:
    from dotenv import load_dotenv
    load_dotenv(BACKEND / ".env")
except Exception:
    pass

import pandas as pd
import numpy as np
from sqlalchemy import text
from app.db.database import SessionLocal


HORIZONS = [5, 10, 20, 30]
TEST_MONTHS = 6
GAP_MONTHS = 1


def main() -> int:
    db = SessionLocal()
    try:
        max_date_row = db.execute(text(
            "SELECT MAX(date) FROM stock_features WHERE stock_id ~ '^[1-9][0-9]{3}$'"
        )).fetchone()
        max_date = pd.Timestamp(max_date_row[0])
        test_start = (max_date - pd.DateOffset(months=TEST_MONTHS)).date()
        train_end = (max_date - pd.DateOffset(months=TEST_MONTHS + GAP_MONTHS)).date()

        print(f"[regime] max_date={max_date.date()}")
        print(f"[regime] train ≤ {train_end}  (gap)  test ≥ {test_start}")

        df = pd.read_sql(
            text("""
                SELECT stock_id, date, close
                FROM stock_features
                WHERE stock_id ~ '^[1-9][0-9]{3}$'
                ORDER BY stock_id, date
            """),
            db.bind,
        )
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values(['stock_id', 'date']).reset_index(drop=True)
        print(f"[regime] total rows={len(df)}  stocks={df['stock_id'].nunique()}")

        for N in HORIZONS:
            df[f'fret_{N}'] = df.groupby('stock_id')['close'].shift(-N) / df['close'] - 1

        train_mask = df['date'] <= pd.Timestamp(train_end)
        test_mask = df['date'] >= pd.Timestamp(test_start)

        print()
        header = (
            f"{'H':>4} | {'tr_n':>8} | {'te_n':>7} | "
            f"{'tr_mkt_wr':>9} | {'te_mkt_wr':>9} | {'Δwr':>7} | "
            f"{'tr_mean':>8} | {'te_mean':>8} | {'tr_med':>8} | {'te_med':>8}"
        )
        print(header)
        print("-" * len(header))

        for N in HORIZONS:
            col = f'fret_{N}'
            tr = df.loc[train_mask, col].dropna()
            te = df.loc[test_mask, col].dropna()
            tr_wr = float((tr > 0.03).mean())
            te_wr = float((te > 0.03).mean())
            print(
                f"{N:>3}d | {len(tr):>8d} | {len(te):>7d} | "
                f"{tr_wr:>9.3f} | {te_wr:>9.3f} | {te_wr - tr_wr:+7.3f} | "
                f"{tr.mean():+8.4f} | {te.mean():+8.4f} | "
                f"{tr.median():+8.4f} | {te.median():+8.4f}"
            )

        print()
        print("欄位說明：")
        print("  tr_mkt_wr / te_mkt_wr = 全市場 P(forward_return > 3%) in train / test")
        print("  Δwr   = te_mkt_wr - tr_mkt_wr (正值代表 test 市場較強)")
        print("  tr_mean / te_mean = forward_return 平均")
        print("  tr_med  / te_med  = forward_return 中位數")
        print()
        print("判讀：若 Δwr 絕對值 > 5pp，overfit_warning 的 5pp 閾值會被 regime shift")
        print("      系統性觸發，這個 flag 在量 regime 差異而不是模型穩定性。")

    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

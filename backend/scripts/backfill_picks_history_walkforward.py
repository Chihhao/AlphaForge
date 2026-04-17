"""
backfill_picks_history_walkforward.py
─────────────────────────────────────
Walk-forward backfill 真實推薦歷史 (strategy_miner_picks)。

流程：
  1. 每 REOPT_INTERVAL_DAYS 天設一個 re-optimization checkpoint。
  2. 在每個 checkpoint D：用 signal_date <= D 的訊號跑 _optimize_dimension(as_of_date=D)，
     更新 strategy_backtest_params.is_optimal = True 的組合。
  3. 遍歷 [last_checkpoint, next_checkpoint) 區間內的每個 signal_date，
     呼叫 _generate_direction_picks 生成當日 picks，寫入 strategy_miner_picks。
     (此時 optimal 參數已是該區間對應的 walk-forward 結果)
  4. Checkpoint 往前推一階，重複。

關鍵無偏保證：
  - as_of_date 切片確保 optimizer 只看該時點前的資料
  - _generate_direction_picks 讀取當時 is_optimal 的參數
  - strategy_miner_picks 已有 tp/sl/hd 欄位，每筆 pick 保存自己當時用的參數
  - 後續 _evaluate_pick_concluded 用 pick 自己的參數判定結案，不受未來 is_optimal 變化影響

使用：
  cd backend
  ./.venv/bin/python scripts/backfill_picks_history_walkforward.py \\
      --start 2025-09-01 [--interval 14] [--dry-run]
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_START = date(2025, 9, 1)
DEFAULT_INTERVAL = 14
DIMENSIONS = ['5d', '10d', '20d']


def _reoptimize(db, checkpoint: date) -> None:
    """在 checkpoint 日期重跑 3 維度 × 2 方向 = 6 次尋優。"""
    from app.services.strategy_miner_service import StrategyMinerService
    for dim in DIMENSIONS:
        for direction in ('long', 'short'):
            try:
                StrategyMinerService._optimize_dimension(
                    db, dim, direction, as_of_date=checkpoint,
                )
            except Exception as e:
                logger.error(f"  {dim}/{direction} as_of={checkpoint} 失敗: {e}", exc_info=True)
    db.commit()


def _generate_picks_for_range(
    db, start: date, end_exclusive: date,
) -> int:
    """對 [start, end_exclusive) 區間內每一天訊號生成 picks。"""
    from app.models.alpha_signal_history import AlphaSignalHistory
    from app.services.strategy_miner_service import StrategyMinerService

    signal_dates = (
        db.query(AlphaSignalHistory.signal_date)
        .filter(
            AlphaSignalHistory.signal_date >= start,
            AlphaSignalHistory.signal_date < end_exclusive,
        )
        .distinct()
        .order_by(AlphaSignalHistory.signal_date)
        .all()
    )
    signal_dates = [r.signal_date for r in signal_dates]

    total = 0
    for d in signal_dates:
        count = 0
        for direction in ('long', 'short'):
            c = StrategyMinerService._generate_direction_picks(db, d, d, direction)
            count += c
        db.commit()
        if count > 0:
            logger.info(f"  {d}: 寫入 {count} 檔推薦")
            total += count
    return total


def main():
    parser = argparse.ArgumentParser(description="Walk-forward backfill 真實推薦歷史")
    parser.add_argument("--start", type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
                        default=DEFAULT_START, help="backfill 起始日期 (YYYY-MM-DD)")
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL,
                        help="每 N 天重新尋優一次 (預設 14)")
    parser.add_argument("--dry-run", action="store_true", help="印出 checkpoints 但不寫入")
    args = parser.parse_args()

    from app.db.database import SessionLocal
    from app.models.strategy_miner_pick import StrategyMinerPick

    db = SessionLocal()
    try:
        today = date.today()
        checkpoints = []
        d = args.start
        while d < today:
            checkpoints.append(d)
            d = d + timedelta(days=args.interval)
        if checkpoints[-1] < today:
            checkpoints.append(today)

        logger.info(f"規劃 {len(checkpoints)} 個 checkpoints，間隔 {args.interval} 天")
        for cp in checkpoints:
            logger.info(f"  - {cp}")

        if args.dry_run:
            logger.info("dry-run: 不執行")
            return

        total_picks = 0
        for i, cp in enumerate(checkpoints):
            logger.info(f"=== Checkpoint {i+1}/{len(checkpoints)}: {cp} ===")
            logger.info("Step 1: 重跑參數尋優")
            _reoptimize(db, cp)

            range_start = cp
            range_end = checkpoints[i + 1] if i + 1 < len(checkpoints) else today + timedelta(days=1)
            logger.info(f"Step 2: 生成 picks for [{range_start}, {range_end})")
            added = _generate_picks_for_range(db, range_start, range_end)
            total_picks += added

        total = db.query(StrategyMinerPick).count()
        logger.info("=" * 50)
        logger.info(f"完成：本次新增 {total_picks} 筆；picks 表總計 {total} 筆")

    except Exception as e:
        logger.error(f"失敗: {e}", exc_info=True)
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()

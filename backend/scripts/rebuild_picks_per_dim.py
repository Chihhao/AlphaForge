"""Rebuild strategy_miner_picks under per-dim architecture.

清空 strategy_miner_picks 後, 用新的 _generate_direction_picks (per-dim 架構)
走 walk-forward 重建 9/1 ~ 今日的推薦歷史。

前置條件:
  - unique constraint 已切為 uq_strategy_miner_pick_v3 (見 migrate_picks_v3_unique_key.py)
  - 舊資料已備份 (strategy_miner_picks_backup_20260418_pre_v3)
"""
from __future__ import annotations
import argparse
import logging
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Rebuild picks under per-dim architecture")
    parser.add_argument("--start", type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
                        default=date(2025, 9, 1))
    parser.add_argument("--interval", type=int, default=14)
    parser.add_argument("--no-truncate", action="store_true",
                        help="Skip TRUNCATE (補洞模式, 新舊架構混存後果自負)")
    args = parser.parse_args()

    from app.db.database import SessionLocal
    from app.models.strategy_miner_pick import StrategyMinerPick
    from scripts.backfill_picks_history_walkforward import (
        _reoptimize, _generate_picks_for_range,
    )

    db = SessionLocal()
    try:
        if not args.no_truncate:
            cnt = db.query(StrategyMinerPick).count()
            logger.info(f"TRUNCATE strategy_miner_picks ({cnt} rows will be removed)")
            db.execute(text("TRUNCATE TABLE strategy_miner_picks RESTART IDENTITY"))
            db.commit()

        today = date.today()
        checkpoints = []
        d = args.start
        while d < today:
            checkpoints.append(d)
            d = d + timedelta(days=args.interval)
        if checkpoints[-1] < today:
            checkpoints.append(today)

        logger.info(f"規劃 {len(checkpoints)} 個 checkpoints")

        total_picks = 0
        for i, cp in enumerate(checkpoints):
            logger.info(f"=== Checkpoint {i+1}/{len(checkpoints)}: {cp} ===")
            _reoptimize(db, cp)
            range_start = cp
            range_end = checkpoints[i + 1] if i + 1 < len(checkpoints) else today + timedelta(days=1)
            added = _generate_picks_for_range(db, range_start, range_end)
            total_picks += added

        total = db.query(StrategyMinerPick).count()
        logger.info(f"完成: 新增 {total_picks}, 表總計 {total}")
    except Exception as e:
        logger.error(f"失敗: {e}", exc_info=True)
        sys.exit(1)
    finally:
        db.close()


if __name__ == '__main__':
    main()

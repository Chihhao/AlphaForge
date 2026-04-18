"""Migration: strategy_miner_picks unique constraint v2 -> v3

v2: (pick_date, stock_id, direction)                      -- 融合架構
v3: (pick_date, stock_id, direction, time_dimension)      -- per-dim 架構
"""
from __future__ import annotations
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text

from app.db.database import SessionLocal

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

OLD_NAME = 'uq_strategy_miner_pick_v2'
NEW_NAME = 'uq_strategy_miner_pick_v3'


def main():
    db = SessionLocal()
    try:
        exists_old = db.execute(text(
            "SELECT 1 FROM pg_constraint WHERE conname = :n"
        ), {'n': OLD_NAME}).scalar()
        exists_new = db.execute(text(
            "SELECT 1 FROM pg_constraint WHERE conname = :n"
        ), {'n': NEW_NAME}).scalar()
        logger.info(f"old constraint {OLD_NAME}: {'exists' if exists_old else 'absent'}")
        logger.info(f"new constraint {NEW_NAME}: {'exists' if exists_new else 'absent'}")

        if exists_new:
            logger.info("v3 constraint already present, skipping")
            return

        if exists_old:
            logger.info(f"DROP CONSTRAINT {OLD_NAME}")
            db.execute(text(f'ALTER TABLE strategy_miner_picks DROP CONSTRAINT {OLD_NAME}'))

        # 即使 constraint 不存在, PostgreSQL 有時仍會殘留同名 unique index,
        # 會繼續擋住跨維度寫入; 明確 drop index 以求穩定。
        logger.info(f"DROP INDEX IF EXISTS {OLD_NAME}")
        db.execute(text(f'DROP INDEX IF EXISTS {OLD_NAME}'))

        logger.info(f"ADD CONSTRAINT {NEW_NAME}")
        db.execute(text(
            f'ALTER TABLE strategy_miner_picks ADD CONSTRAINT {NEW_NAME} '
            'UNIQUE (pick_date, stock_id, direction, time_dimension)'
        ))
        db.commit()
        logger.info("migration complete")
    except Exception as e:
        logger.error(f"failed: {e}", exc_info=True)
        db.rollback()
        sys.exit(1)
    finally:
        db.close()


if __name__ == '__main__':
    main()

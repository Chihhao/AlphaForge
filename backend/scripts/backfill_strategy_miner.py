"""
backfill_strategy_miner.py
──────────────────────────
Strategy Miner 一次性回補腳本：執行 18 組參數尋優並產生今日推薦清單。

用途：
  - 首次部署後手動執行，讓 strategy_miner_picks 有真實停利停損值
  - 每週日 06:00 排程也會自動執行，此腳本供臨時手動補跑

使用方法：
  cd backend
  ./.venv/bin/python scripts/backfill_strategy_miner.py

執行時間：約 10-60 秒（視 alpha_signal_history 資料量而定）
"""
from __future__ import annotations

import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)


def main():
    from app.db.database import SessionLocal
    from app.services.strategy_miner_service import StrategyMinerService, DIMENSIONS
    from app.models.strategy_backtest_param import StrategyBacktestParam
    from app.models.strategy_miner_trade import StrategyMinerTrade
    from app.models.strategy_miner_pick import StrategyMinerPick

    db = SessionLocal()
    try:
        logger.info("=" * 60)
        logger.info("Strategy Miner 參數尋優開始")
        logger.info("=" * 60)

        # ── Step 1: 執行 18 組參數尋優（所有維度）────────────────────
        logger.info("[1/2] 執行 run_all（18 組參數 × 3 維度）…")
        StrategyMinerService.run_all(db)

        # ── Step 2: 生成今日推薦清單 ──────────────────────────────────
        logger.info("[2/2] 生成今日推薦清單…")
        count = StrategyMinerService.run_daily(db)

        # ── 結果統計 ──────────────────────────────────────────────────
        logger.info("=" * 60)
        logger.info("執行完成，結果統計：")
        logger.info("")

        for dim in DIMENSIONS:
            opt = (
                db.query(StrategyBacktestParam)
                .filter(
                    StrategyBacktestParam.strategy_id == dim,
                    StrategyBacktestParam.is_optimal == True,  # noqa: E712
                )
                .first()
            )
            trade_count = (
                db.query(StrategyMinerTrade)
                .filter(StrategyMinerTrade.strategy_id == dim)
                .count()
            )
            if opt:
                logger.info(
                    f"  {dim:4s} 最優: "
                    f"TP={opt.take_profit_pct*100:.0f}% "
                    f"SL={opt.stop_loss_pct*100:.0f}% "
                    f"HD={opt.hold_days_max}天 "
                    f"| Sharpe訓練={opt.sharpe_train:.3f} 測試={opt.sharpe_test:.3f}"
                    f"| 勝率={opt.win_rate_test*100:.1f}%"
                    f"| 交易筆數={trade_count}"
                )
            else:
                logger.info(f"  {dim:4s} 無最優參數（訊號不足）")

        logger.info("")
        logger.info(f"今日推薦清單：{count} 檔股票")

        picks = (
            db.query(StrategyMinerPick)
            .order_by(StrategyMinerPick.weighted_score.desc())
            .limit(10)
            .all()
        )
        for i, p in enumerate(picks, 1):
            logger.info(
                f"  #{i} {p.stock_name}({p.stock_id}) "
                f"買入={p.entry_price:.0f} "
                f"停利=+{p.take_profit_pct*100:.0f}% "
                f"停損=-{p.stop_loss_pct*100:.0f}% "
                f"持有{p.hold_days_max}天"
            )

        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"執行失敗: {e}", exc_info=True)
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()

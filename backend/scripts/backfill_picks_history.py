"""
backfill_picks_history.py
─────────────────────────
回補 strategy_miner_picks 歷史推薦資料。

原有的 run_daily() 只生成「今日」推薦，本腳本利用 alpha_signal_history 的歷史
訊號，補生成過去 N 天的推薦清單，讓「近期精選歷史」與「持倉追蹤」顯示真實紀錄。

策略：
  - 每個歷史訊號日期，使用該日期的收盤價作為 entry_price（代表次日開盤參考價）
  - 最優停利/停損/持有天數使用當前已優化的 strategy_backtest_params
  - 若該日已有 picks 則跳過（idempotent）

使用方法：
  cd backend
  ./.venv/bin/python scripts/backfill_picks_history.py [--days 30]

  --days: 回補天數（預設 30）
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections import defaultdict
from datetime import date, timedelta
from typing import Dict, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _get_prices_on_date(db, stock_ids: list, target_date: date) -> Dict[str, float]:
    """取得各股在 target_date 當天（或最近前一個交易日）的收盤價。"""
    from sqlalchemy import func, and_
    from app.models.stock_price import StockPrice

    if not stock_ids:
        return {}

    # 取 <= target_date 的最新收盤價
    sub = (
        db.query(
            StockPrice.stock_id,
            func.max(StockPrice.date).label("max_date"),
        )
        .filter(
            StockPrice.stock_id.in_(stock_ids),
            StockPrice.close > 0,
            StockPrice.date <= target_date,
        )
        .group_by(StockPrice.stock_id)
        .subquery()
    )
    rows = (
        db.query(StockPrice.stock_id, StockPrice.close)
        .join(
            sub,
            and_(
                StockPrice.stock_id == sub.c.stock_id,
                StockPrice.date == sub.c.max_date,
            ),
        )
        .all()
    )
    return {r.stock_id: float(r.close) for r in rows if r.close}


def generate_picks_for_date(db, target_date: date, optimal: dict, reasons_map: dict) -> int:
    """為指定日期生成推薦清單，回傳寫入筆數。"""
    from app.models.alpha_signal_history import AlphaSignalHistory
    from app.models.strategy_miner_pick import StrategyMinerPick
    from app.services.strategy_miner_service import StrategyMinerService
    from sqlalchemy import delete

    # 查該日訊號（所有維度）
    rows = (
        db.query(AlphaSignalHistory)
        .filter(AlphaSignalHistory.signal_date == target_date)
        .all()
    )
    if not rows:
        return 0

    # 同股票同維度保留 trigger_count 最高者
    by_dim: Dict[str, Dict[str, AlphaSignalHistory]] = {}
    for r in rows:
        dim_map = by_dim.setdefault(r.time_dimension, {})
        existing = dim_map.get(r.stock_id)
        if existing is None or r.trigger_count > existing.trigger_count:
            dim_map[r.stock_id] = r

    # 合併多維共鳴
    combined: dict = {}
    for dim, dim_map in by_dim.items():
        for stock_id, r in dim_map.items():
            base_score = r.trigger_count * (r.weighted_odds_ratio or 1.0)
            if stock_id not in combined:
                combined[stock_id] = {
                    "primary": r,
                    "dims": [dim],
                    "score": base_score,
                }
            else:
                combined[stock_id]["dims"].append(dim)
                if base_score > combined[stock_id]["score"]:
                    combined[stock_id]["primary"] = r
                    combined[stock_id]["score"] = base_score
                combined[stock_id]["score"] *= 1.10

    sorted_combined = sorted(combined.values(), key=lambda x: x["score"], reverse=True)[:10]

    stock_ids = [item["primary"].stock_id for item in sorted_combined]
    price_map = _get_prices_on_date(db, stock_ids, target_date)

    # 刪除該日已有的 picks（idempotent）
    db.execute(delete(StrategyMinerPick).where(StrategyMinerPick.pick_date == target_date))

    count = 0
    for item in sorted_combined:
        r = item["primary"]
        dims = sorted(set(item["dims"]))
        opt_params = optimal.get(r.time_dimension)
        entry_price = price_map.get(r.stock_id, 0.0)

        if opt_params:
            tp = opt_params.take_profit_pct
            sl = opt_params.stop_loss_pct
            hd = opt_params.hold_days_max
        else:
            tp, sl, hd = StrategyMinerService._default_params(r.time_dimension)

        reasons = reasons_map.get(r.stock_id, [])

        db.add(StrategyMinerPick(
            pick_date=target_date,
            stock_id=r.stock_id,
            stock_name=r.stock_name,
            strategy_ids=json.dumps(dims),
            weighted_score=round(item["score"], 4),
            entry_price=entry_price,
            take_profit_pct=tp,
            stop_loss_pct=sl,
            hold_days_max=hd,
            time_dimension=r.time_dimension,
            buy_reasons=json.dumps(reasons, ensure_ascii=False) if reasons else None,
        ))
        count += 1

    db.commit()
    return count


def main():
    parser = argparse.ArgumentParser(description="回補 strategy_miner_picks 歷史推薦")
    parser.add_argument("--days", type=int, default=30, help="回補天數（預設 30）")
    parser.add_argument("--skip-existing", action="store_true", default=True,
                        help="跳過已有 picks 的日期（預設啟用）")
    args = parser.parse_args()

    from app.db.database import SessionLocal
    from app.models.alpha_signal_history import AlphaSignalHistory
    from app.models.strategy_backtest_param import StrategyBacktestParam
    from app.models.strategy_miner_pick import StrategyMinerPick
    from app.models.alpha_miner_snapshot import AlphaMinerSnapshot

    db = SessionLocal()
    try:
        # 查最優參數（各維度）
        optimal = {}
        for dim in ["5d", "10d", "30d"]:
            opt = (
                db.query(StrategyBacktestParam)
                .filter(
                    StrategyBacktestParam.strategy_id == dim,
                    StrategyBacktestParam.is_optimal == True,  # noqa: E712
                )
                .first()
            )
            optimal[dim] = opt
            if opt:
                logger.info(
                    f"  {dim} 最優: TP={opt.take_profit_pct*100:.0f}% "
                    f"SL={opt.stop_loss_pct*100:.0f}% HD={opt.hold_days_max}天"
                )
            else:
                logger.warning(f"  {dim} 無最優參數，將使用預設值")

        # 建立買入理由 map（基於最新 AlphaMinerSnapshot）
        reasons_map: dict = {}
        try:
            snap = (
                db.query(AlphaMinerSnapshot)
                .order_by(AlphaMinerSnapshot.train_date.desc())
                .first()
            )
            if snap:
                result_data = json.loads(snap.result_json)
                details_data = json.loads(snap.details_json)
                sig_name_map: dict = {}
                for s in result_data.get("strategies", []):
                    if s.get("is_significant") and s.get("ic", 0) > 0:
                        sig_name_map[s["strategy_id"]] = s["strategy_name"]
                stock_strategy_names: dict = {}
                for strat_id, name in sig_name_map.items():
                    detail = details_data.get(strat_id, {})
                    for sig in detail.get("recent_signals", []):
                        sid = sig.get("stock_id")
                        if sid:
                            lst = stock_strategy_names.setdefault(sid, [])
                            if name not in lst:
                                lst.append(name)
                reasons_map = {k: v[:3] for k, v in stock_strategy_names.items()}
                logger.info(f"買入理由 map 建立完成：{len(reasons_map)} 檔有理由")
        except Exception as e:
            logger.warning(f"買入理由建立失敗（略過）: {e}")

        # 查 alpha_signal_history 中有訊號的歷史日期（排除今日）
        today = date.today()
        cutoff = today - timedelta(days=args.days)

        signal_dates = (
            db.query(AlphaSignalHistory.signal_date)
            .filter(
                AlphaSignalHistory.signal_date >= cutoff,
                AlphaSignalHistory.signal_date < today,
            )
            .distinct()
            .order_by(AlphaSignalHistory.signal_date)
            .all()
        )
        signal_dates = [r.signal_date for r in signal_dates]
        logger.info(f"找到 {len(signal_dates)} 個歷史訊號日期 (近 {args.days} 天)")

        if not signal_dates:
            logger.warning("無歷史訊號，請先執行 backfill_signal_history.py")
            return

        # 查已有 picks 的日期
        existing_dates = set()
        if args.skip_existing:
            rows = (
                db.query(StrategyMinerPick.pick_date)
                .filter(StrategyMinerPick.pick_date.in_(signal_dates))
                .distinct()
                .all()
            )
            existing_dates = {r.pick_date for r in rows}
            logger.info(f"已有 picks 的日期：{len(existing_dates)} 個（將跳過）")

        total_added = 0
        skipped = 0
        for target_date in signal_dates:
            if target_date in existing_dates:
                skipped += 1
                continue

            count = generate_picks_for_date(db, target_date, optimal, reasons_map)
            if count > 0:
                total_added += count
                logger.info(f"  {target_date}: 寫入 {count} 檔推薦")
            else:
                logger.debug(f"  {target_date}: 無訊號或無收盤價，跳過")

        logger.info("=" * 50)
        logger.info(f"回補完成：新增 {total_added} 筆，跳過 {skipped} 個已有日期")

        # 統計最終 picks 數量
        total = db.query(StrategyMinerPick).count()
        logger.info(f"strategy_miner_picks 總計：{total} 筆")

    except Exception as e:
        logger.error(f"執行失敗: {e}", exc_info=True)
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()

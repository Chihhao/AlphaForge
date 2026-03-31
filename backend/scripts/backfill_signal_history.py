"""
backfill_signal_history.py
─────────────────────────
用現有訓練快照的因子係數，對過去 N 天每個交易日重算訊號並寫入 alpha_signal_history，
再一次性回填所有已到期訊號的實際報酬。

原理：
  LogisticRegression 排名 ∝ X @ coef（intercept 是常數，不影響相對排序）
  → 用儲存的 factor_weights[i].coefficient 重建 Top-20% 訊號即可

使用方法：
  cd backend
  ./.venv/bin/python scripts/backfill_signal_history.py [--days 35]
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import os

import numpy as np
import pandas as pd
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)


def main(days: int = 35, start_date: Optional[str] = None) -> None:
    from app.db.database import SessionLocal, engine, Base
    from app.models.alpha_miner_snapshot import AlphaMinerSnapshot
    from app.models.alpha_signal_history import AlphaSignalHistory
    from app.services.alpha_miner_service import AlphaMinerService

    # 確保資料表存在
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        _backfill(db, engine, days, start_date)
        logger.info("[Backfill] 開始回填實際報酬...")
        resolved = AlphaMinerService.update_signal_returns(db)
        logger.info(f"[Backfill] 結算完成：{resolved} 筆")
    finally:
        db.close()


def _backfill(db, engine, days: int, start_date: Optional[str] = None) -> None:
    from app.models.alpha_miner_snapshot import AlphaMinerSnapshot
    from app.models.alpha_signal_history import AlphaSignalHistory

    # ── 1. 載入快照 ──────────────────────────────────────────────────────────
    snap = db.query(AlphaMinerSnapshot).order_by(
        AlphaMinerSnapshot.train_date.desc()
    ).first()
    if snap is None:
        logger.error("沒有訓練快照，請先執行 Alpha Miner 訓練")
        return

    details: dict = json.loads(snap.details_json)
    logger.info(f"快照日期：{snap.train_date}，共 {len(details)} 個策略")

    # ── 2. 依維度分組顯著策略（做多 ic > 0，放空 ic < 0）──────────────────────
    DIMENSIONS = ["5d", "10d", "30d", "5d_short", "10d_short", "30d_short"]
    DIM_THR = {"5d": (0.03, 0.05), "10d": (0.03, 0.05), "30d": (0.05, 0.10),
               "5d_short": (0.03, 0.05), "10d_short": (0.03, 0.05), "30d_short": (0.05, 0.10)}

    sig_by_dim: Dict[str, List[dict]] = {d: [] for d in DIMENSIONS}
    for sid, det in details.items():
        if not det.get("is_significant"):
            continue
        dim = det.get("time_dimension")
        if dim not in sig_by_dim:
            continue
        ic_val = det.get("ic", 0)
        # 做多只用 ic > 0，放空只用 ic < 0
        if '_short' in dim and ic_val >= 0:
            continue
        if '_short' not in dim and ic_val <= 0:
            continue
        sig_by_dim[dim].append(det)

    for dim, strats in sig_by_dim.items():
        logger.info(f"  {dim}：{len(strats)} 個有效顯著策略")

    # ── 3. 載入過去 days 天（或指定 start_date 之後）的 stock_features ────────
    if start_date:
        cutoff = start_date
    else:
        cutoff = (date.today() - timedelta(days=days)).isoformat()
    all_factors = set()
    for strats in sig_by_dim.values():
        for det in strats:
            all_factors.update(det.get("factors", []))

    needed_cols = ["stock_id", "date", "close"] + sorted(all_factors)
    available_cols_sql = ", ".join(needed_cols)

    logger.info(f"載入 stock_features（{cutoff} 之後）...")
    df_all = pd.read_sql(
        f"SELECT {available_cols_sql} FROM stock_features WHERE date >= '{cutoff}'",
        engine,
    )
    if df_all.empty:
        logger.error("stock_features 無資料")
        return

    df_all["date"] = pd.to_datetime(df_all["date"]).dt.date
    trading_dates = sorted(df_all["date"].unique())
    logger.info(f"共 {len(trading_dates)} 個交易日")

    # ── 4. 查詢股票名稱 ─────────────────────────────────────────────────────
    import sqlalchemy as sa
    name_rows = engine.connect().execute(
        sa.text("SELECT stock_id, stock_name FROM stocks")
    ).fetchall()
    name_map = {r.stock_id: r.stock_name for r in name_rows}

    def lookup_name(sid: str) -> str:
        if sid in name_map:
            return name_map[sid]
        try:
            import twstock
            info = twstock.codes.get(sid)
            if info:
                name_map[sid] = info.name
                return info.name
        except Exception:
            pass
        return sid

    # ── 5. 查詢已存在的記錄，避免重複 ──────────────────────────────────────
    existing_keys = {
        (r.signal_date, r.stock_id, r.time_dimension, r.direction)
        for r in db.query(
            AlphaSignalHistory.signal_date,
            AlphaSignalHistory.stock_id,
            AlphaSignalHistory.time_dimension,
            AlphaSignalHistory.direction,
        ).all()
    }
    logger.info(f"已有 {len(existing_keys)} 筆歷史記錄，將跳過")

    # ── 6. 逐日逐維度計算訊號 ────────────────────────────────────────────────
    total_inserted = 0

    for target_date in trading_dates:
        df_day = df_all[df_all["date"] == target_date].copy()
        if len(df_day) < 50:
            continue  # 資料太少的日期跳過

        for dim in DIMENSIONS:
            strats = sig_by_dim[dim]
            if not strats:
                continue

            tlo, thi = DIM_THR[dim]
            stock_map: Dict[str, dict] = {}

            for det in strats:
                factors: List[str] = det["factors"]
                rank_cols = [f"{f}_rank" for f in factors]
                fw = {fw_item["factor"]: fw_item["coefficient"] for fw_item in det["factor_weights"]}
                ic = abs(float(det["ic"]))

                # 計算分位數排名
                df_scored = df_day.copy()
                missing = [f for f in factors if f not in df_scored.columns]
                if missing:
                    continue
                for f in factors:
                    df_scored[f"{f}_rank"] = df_scored[f].rank(pct=True, na_option="keep")

                df_scored = df_scored.dropna(subset=rank_cols)
                if len(df_scored) < 20:
                    continue

                # 線性組合分數（等價於 logistic regression 排名）
                X = df_scored[rank_cols].values
                coef = np.array([fw.get(f, 0.0) for f in factors])
                scores = X @ coef
                df_scored = df_scored.copy()
                df_scored["_score"] = scores

                # Top 20%
                threshold = np.percentile(scores, 80)
                top = df_scored[df_scored["_score"] >= threshold]

                win_rate = float(det.get("win_rate_outsample", 0))
                win_rate_hi = float(det.get("win_rate_outsample_hi", 0))
                loss_rate = float(det.get("loss_rate_outsample", 0))
                loss_rate_hi = float(det.get("loss_rate_outsample_hi", 0))

                for _, row in top.iterrows():
                    sid = str(row["stock_id"])
                    if sid not in stock_map:
                        stock_map[sid] = {
                            "stock_id": sid,
                            "trigger_count": 0,
                            "_ic_sum": 0.0,
                            "_w_win": 0.0,
                            "_w_loss": 0.0,
                        }
                    stock_map[sid]["trigger_count"] += 1
                    stock_map[sid]["_ic_sum"] += ic
                    stock_map[sid]["_w_win"] += win_rate * ic
                    stock_map[sid]["_w_loss"] += loss_rate * ic

            # 動態門檻：有效策略數 × 40%（至少 2），最多 20 支（與 get_today_signals 一致）
            direction = 'short' if '_short' in dim else 'long'
            base_dim = dim.replace('_short', '')
            min_triggers = max(2, round(len(strats) * 0.4))
            candidates = sorted(
                [s for s in stock_map.values() if s["trigger_count"] >= min_triggers],
                key=lambda x: x["trigger_count"],
                reverse=True,
            )[:20]
            rows_to_insert = []
            for s in candidates:
                key = (target_date, s["stock_id"], base_dim, direction)
                if key in existing_keys:
                    continue
                ic_sum = max(s["_ic_sum"], 1e-9)
                w_win = s["_w_win"] / ic_sum
                w_loss = s["_w_loss"] / ic_sum
                odds = round(w_win / max(w_loss, 0.001), 2)
                rows_to_insert.append(AlphaSignalHistory(
                    signal_date=target_date,
                    stock_id=s["stock_id"],
                    stock_name=lookup_name(s["stock_id"]),
                    time_dimension=base_dim,
                    direction=direction,
                    trigger_count=s["trigger_count"],
                    weighted_win_rate=round(w_win, 4),
                    weighted_odds_ratio=odds,
                ))
                existing_keys.add(key)

            if rows_to_insert:
                db.add_all(rows_to_insert)
                db.commit()
                total_inserted += len(rows_to_insert)

        logger.info(f"  {target_date} 處理完畢（累計寫入 {total_inserted} 筆）")

    logger.info(f"[Backfill] 共寫入 {total_inserted} 筆訊號歷史")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=35, help="回填天數（預設 35），--start-date 優先")
    parser.add_argument("--start-date", type=str, default=None, help="回填起始日期（YYYY-MM-DD），優先於 --days")
    args = parser.parse_args()
    main(days=args.days, start_date=args.start_date)

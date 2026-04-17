"""
backfill_signal_history_walkforward.py
──────────────────────────────────────
對缺漏的 alpha_signal_history 做 walk-forward 補寫。

背景：
- 2026-04-10 commit 89ca3bb 擴充 AlphaMinerService.DIMENSIONS 為 [5d, 10d, 20d]
  但 backend/app/core/scheduler.py 仍寫死 ["20d"]（今日 2026-04-17 commit 已修）。
- 結果 5d/long 4/1-4/16、10d/long 4/2-4/16 的訊號歷史遺漏。
- 本腳本用 walk-forward 方式補這段缺口，避免前視偏差。

無偏保證：
- 訓練只看 checkpoint_date（含）之前的 stock_features。
- Quantile rank 為 per-date 橫斷面 pct rank，只依賴單日資料。
- 推論日的 feature 由 df 取出 (訓練時已 rank 過)，不使用任何未來訊息。
- 同 (signal_date, stock_id, time_dimension, direction) 已存在跳過 (冪等)。

使用：
  cd backend
  ./.venv/bin/python scripts/backfill_signal_history_walkforward.py \\
      --checkpoint 2026-04-02 \\
      --targets 2026-04-02:2026-04-17 \\
      --dims 5d,10d
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, datetime, timedelta
from typing import List

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


DIM_MAP = {
    '5d':  {'key': '5d',  'forward_days': 5,  'threshold_low': 0.03, 'threshold_high': 0.05, 'direction': 'long'},
    '10d': {'key': '10d', 'forward_days': 10, 'threshold_low': 0.03, 'threshold_high': 0.05, 'direction': 'long'},
    '20d': {'key': '20d', 'forward_days': 20, 'threshold_low': 0.03, 'threshold_high': 0.05, 'direction': 'long'},
}


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def _parse_target_range(expr: str) -> tuple[date, date]:
    if ':' not in expr:
        d = _parse_date(expr)
        return d, d
    start, end = expr.split(':', 1)
    return _parse_date(start), _parse_date(end)


def _load_trading_dates(db, start: date, end: date) -> List[date]:
    from sqlalchemy import text
    rows = db.execute(
        text(
            "SELECT DISTINCT date FROM stock_features "
            "WHERE date >= :s AND date <= :e ORDER BY date"
        ),
        {'s': start.isoformat(), 'e': end.isoformat()},
    ).fetchall()
    return [r[0] for r in rows]


def _train_models_for_checkpoint(checkpoint: date, dims: List[str]):
    """訓練 dims 指定維度的模型，回傳 {dim_key: (clf, reg, reg_min, reg_range, rank_cols, factors, df_ranked)}。

    df_ranked 是完整含 rank 的 DataFrame（含訓練期 + 推論期的所有日期），
    推論時直接 filter date == target_date 取 snapshot。
    """
    from sqlalchemy import text
    import lightgbm as lgb
    from app.services.alpha_miner_service import (
        AlphaMinerService, TRAINING_FACTORS, _LOAD_COLS,
    )
    from app.db.database import engine

    # 載入 features（含推論期，per-date rank 無偏）
    cutoff = (checkpoint - timedelta(days=365 * 2)).isoformat()
    cols = ", ".join(_LOAD_COLS)
    sql = text(
        f"SELECT {cols} FROM stock_features WHERE date >= :cutoff "
        "AND stock_id ~ '^[1-9][0-9]{3}$'"
    )
    df = pd.read_sql(sql, engine, params={'cutoff': cutoff})
    df['date'] = pd.to_datetime(df['date'])
    if 'volume' in df.columns:
        df = df[df['volume'] >= 500_000].copy()

    # neg_ 衍生因子
    neg_map = {
        'trust_net_buy':  'neg_trust_net_buy',
        'trust_buy_5d':   'neg_trust_buy_5d',
        'trust_buy_10d':  'neg_trust_buy_10d',
        'trust_buy_20d':  'neg_trust_buy_20d',
        'bias5':          'neg_bias5',
    }
    for src, dst in neg_map.items():
        if src in df.columns:
            df[dst] = -df[src]

    # Per-date 橫斷面 pct rank（這對訓練期和推論期都安全，因為只看同日）
    df = AlphaMinerService._compute_quantile_ranks(df)

    # 訓練切割：以 checkpoint 為 max_date，往前推 6m test / 7m gap
    max_date = pd.Timestamp(checkpoint)
    test_start = (max_date - pd.DateOffset(months=AlphaMinerService.TEST_MONTHS)).date()
    train_end = (max_date - pd.DateOffset(
        months=AlphaMinerService.TEST_MONTHS + AlphaMinerService.GAP_MONTHS)).date()

    # 權重（以 train_end 為基準）— 需要 date.dt.year 欄位，全體套用
    df = AlphaMinerService._add_weights(df, train_end)

    factors = list(TRAINING_FACTORS.keys())
    rank_cols = [f'{f}_rank' for f in factors]
    available = [(f, rc) for f, rc in zip(factors, rank_cols) if rc in df.columns]
    factors = [a[0] for a in available]
    rank_cols = [a[1] for a in available]

    results = {}
    for dim_key in dims:
        dim = DIM_MAP[dim_key]
        thr_lo = dim['threshold_low']
        forward_days = dim['forward_days']
        dim_direction = dim['direction']

        # 只用 <= checkpoint 的資料算 forward_return，避免推論期資料進訓練 label
        df_until_cp = df[df['date'] <= pd.Timestamp(checkpoint)].copy()
        df_dim = AlphaMinerService._compute_forward_returns(
            df_until_cp, forward_days, thr_lo, dim_direction,
        )

        train_df = df_dim[df_dim['date'] <= pd.Timestamp(train_end)].dropna(subset=['label'])
        test_df = df_dim[df_dim['date'] >= pd.Timestamp(test_start)].dropna(
            subset=['label', 'forward_return']
        )
        if forward_days >= 20 and 'ma60' in df_dim.columns:
            if dim_direction == 'long':
                train_df = train_df[train_df['close'] > train_df['ma60']].copy()
                test_df = test_df[test_df['close'] > test_df['ma60']].copy()
            else:
                train_df = train_df[train_df['close'] < train_df['ma60']].copy()
                test_df = test_df[test_df['close'] < test_df['ma60']].copy()

        if len(train_df) < 200 or len(test_df) < 50:
            logger.warning(f"  {dim_key}: 訓練樣本不足 (train={len(train_df)}, test={len(test_df)})，跳過")
            continue

        X_train = train_df[rank_cols].values
        y_train = train_df['label'].values
        w_train = train_df['weight'].values
        y_train_ret = train_df['forward_return'].values.clip(-0.5, 0.5)

        clf = lgb.LGBMClassifier(
            n_estimators=200, max_depth=4, num_leaves=15,
            learning_rate=0.01, min_child_samples=100,
            subsample=0.8, colsample_bytree=0.8,
            reg_alpha=0.1, reg_lambda=1.0,
            random_state=42, verbose=-1, is_unbalance=True,
            importance_type='gain',
        )
        clf.fit(X_train, y_train, sample_weight=w_train)

        reg = lgb.LGBMRegressor(
            n_estimators=200, max_depth=4, num_leaves=15,
            learning_rate=0.01, min_child_samples=100,
            subsample=0.8, colsample_bytree=0.8,
            reg_alpha=0.1, reg_lambda=1.0,
            random_state=42, verbose=-1,
            importance_type='gain',
        )
        reg.fit(X_train, y_train_ret, sample_weight=w_train)

        # Regressor normalize 參數（訓練集決定，不受推論日影響）
        p_reg_train = reg.predict(X_train)
        reg_min = float(p_reg_train.min())
        reg_range = float(p_reg_train.max() - reg_min + 1e-9)

        logger.info(
            f"  {dim_key}: trained  train={len(train_df):,}  test={len(test_df):,} "
            f"(train_end={train_end}, test_start={test_start})"
        )
        results[dim_key] = (clf, reg, reg_min, reg_range, rank_cols, factors, df)
    return results


def _infer_and_write(db, model_bundle, dim_key: str, target_date: date, top_pct: float = 0.10) -> int:
    from app.models.alpha_signal_history import AlphaSignalHistory
    from app.services.alpha_miner_service import AlphaMinerService

    clf, reg, reg_min, reg_range, rank_cols, factors, df = model_bundle
    snap = df[df['date'] == pd.Timestamp(target_date)]
    if snap.empty:
        logger.info(f"    {dim_key} {target_date}: 無 feature snapshot，跳過")
        return 0

    X = snap[rank_cols].values
    if X.shape[0] < 10:
        logger.info(f"    {dim_key} {target_date}: 樣本 < 10，跳過")
        return 0

    p_clf = clf.predict_proba(X)[:, 1]
    p_reg = np.clip((reg.predict(X) - reg_min) / reg_range, 0, 1)
    prob = 0.5 * p_clf + 0.5 * p_reg

    snap = snap.copy()
    snap['_prob'] = prob
    threshold = np.percentile(prob, (1 - top_pct) * 100)
    top = snap[snap['_prob'] >= threshold].sort_values('_prob', ascending=False).head(50)
    if top.empty:
        return 0

    existing = {
        row.stock_id
        for row in db.query(AlphaSignalHistory.stock_id)
        .filter(
            AlphaSignalHistory.signal_date == target_date,
            AlphaSignalHistory.time_dimension == dim_key,
            AlphaSignalHistory.direction == 'long',
        )
        .all()
    }

    rows = []
    for _, row in top.iterrows():
        stock_id = str(row['stock_id'])
        if stock_id in existing:
            continue
        name = AlphaMinerService._lookup_name(stock_id)
        rows.append(AlphaSignalHistory(
            signal_date=target_date,
            stock_id=stock_id,
            stock_name=name,
            time_dimension=dim_key,
            direction='long',
            trigger_count=3,
            weighted_win_rate=float(row['_prob']),
            weighted_odds_ratio=1.0,
        ))
    if rows:
        db.add_all(rows)
        db.commit()
    return len(rows)


def main():
    parser = argparse.ArgumentParser(description="walk-forward backfill alpha_signal_history")
    parser.add_argument("--checkpoint", type=_parse_date, required=True,
                        help="訓練截止日期 (YYYY-MM-DD)。模型只用 <= 該日期資料訓練")
    parser.add_argument("--targets", type=str, required=True,
                        help="推論日期範圍 (YYYY-MM-DD 或 YYYY-MM-DD:YYYY-MM-DD)")
    parser.add_argument("--dims", type=str, default="5d,10d",
                        help="維度 csv (預設 5d,10d)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    dims = [d.strip() for d in args.dims.split(',') if d.strip()]
    for d in dims:
        if d not in DIM_MAP:
            logger.error(f"未知維度 {d}")
            sys.exit(1)

    t_start, t_end = _parse_target_range(args.targets)

    from app.db.database import SessionLocal
    db = SessionLocal()
    try:
        target_dates = _load_trading_dates(db, t_start, t_end)
        logger.info(f"checkpoint={args.checkpoint}  dims={dims}  targets={len(target_dates)} 個交易日 ({t_start}~{t_end})")
        if not target_dates:
            logger.warning("無目標交易日，結束")
            return
        if args.dry_run:
            for d in target_dates:
                logger.info(f"  (dry-run) 將推論 {d}")
            return

        logger.info("=== Step 1: 訓練模型 ===")
        bundles = _train_models_for_checkpoint(args.checkpoint, dims)
        if not bundles:
            logger.error("所有維度訓練失敗")
            sys.exit(1)

        logger.info("=== Step 2: 逐日推論 + 寫入 ===")
        total = 0
        for dim_key, bundle in bundles.items():
            logger.info(f"--- {dim_key} ---")
            for d in target_dates:
                n = _infer_and_write(db, bundle, dim_key, d)
                if n > 0:
                    logger.info(f"    {dim_key} {d}: 寫入 {n} 筆")
                    total += n
        logger.info(f"完成：共寫入 {total} 筆")
    finally:
        db.close()


if __name__ == "__main__":
    main()

"""
StrategyMinerService — 停利停損參數尋優 + 每日推薦清單

基於 alpha_signal_history 中的歷史訊號，對 18 種參數組合進行回測，
找出最優參數，生成每日推薦清單（strategy_miner_picks）。

前視偏差防護：進場以 signal_date 收盤價為基準，出場判斷僅用後續交易日收盤價。
"""
from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy import delete

from app.db.database import engine
from app.models.alpha_miner_snapshot import AlphaMinerSnapshot
from app.models.alpha_signal_history import AlphaSignalHistory
from app.models.stock_price import StockPrice
from app.models.strategy_backtest_param import StrategyBacktestParam
from app.models.strategy_miner_trade import StrategyMinerTrade
from app.models.strategy_miner_pick import StrategyMinerPick

logger = logging.getLogger(__name__)

# ─── 18 種參數組合 ─────────────────────────────────────────────────────────────
TAKE_PROFITS = [0.05, 0.08, 0.12]
STOP_LOSSES  = [0.03, 0.05, 0.08]
HOLD_DAYS    = [10, 20]

PARAMS_LIST = [
    {'take_profit_pct': tp, 'stop_loss_pct': sl, 'hold_days': hd}
    for tp in TAKE_PROFITS
    for sl in STOP_LOSSES
    for hd in HOLD_DAYS
]  # 18 combos

DIMENSIONS = ['5d', '10d', '30d']

# ─── 訊號品質門檻 ─────────────────────────────────────────────────────────────
TRIGGER_COUNT_PERCENTILE = 0.70   # 觸發數需 >= 該維度 P70
MIN_WIN_RATE = 0.50               # 最優參數回測勝率需 >= 50%
MAX_PICKS_PER_DIRECTION = 5       # 做多/放空各最多推薦 5 檔


def _sharpe(returns: List[float]) -> float:
    if len(returns) < 3:
        return 0.0
    arr = np.array(returns, dtype=float)
    std = arr.std()
    if std < 1e-9:
        return 0.0
    return float(arr.mean() / std)


class StrategyMinerService:

    # ─── 主要流程 ──────────────────────────────────────────────────────────────
    @classmethod
    def run_all(cls, db: Session) -> None:
        """對所有維度執行參數尋優，結果存 strategy_backtest_params + strategy_miner_trades。
        若訊號不足（< 20）則跳過該維度。做多和放空各自獨立尋優。
        """
        for dim in DIMENSIONS:
            # 做多
            try:
                cls._optimize_dimension(db, dim, direction='long')
            except Exception as e:
                logger.error(f"[StrategyMiner] {dim}/long 尋優失敗: {e}", exc_info=True)
            # 放空
            try:
                cls._optimize_dimension(db, dim, direction='short')
            except Exception as e:
                logger.error(f"[StrategyMiner] {dim}/short 尋優失敗: {e}", exc_info=True)

    @classmethod
    def run_daily(cls, db: Session) -> int:
        """生成今日推薦清單，存入 strategy_miner_picks。回傳寫入筆數。"""
        # 查最新訊號日期
        latest_row = (
            db.query(AlphaSignalHistory.signal_date)
            .order_by(AlphaSignalHistory.signal_date.desc())
            .first()
        )
        if latest_row is None:
            logger.info("[StrategyMiner] 無歷史訊號，跳過 run_daily")
            return 0
        latest_date = latest_row.signal_date

        # 查當日���多訊號
        rows = (
            db.query(AlphaSignalHistory)
            .filter(
                AlphaSignalHistory.signal_date == latest_date,
                AlphaSignalHistory.direction == 'long',
            )
            .all()
        )
        if not rows:
            return 0

        # 查各維度最優參數（僅勝率 >= MIN_WIN_RATE 的維度）
        optimal: Dict[str, Optional[StrategyBacktestParam]] = {}
        for dim in DIMENSIONS:
            opt = (
                db.query(StrategyBacktestParam)
                .filter(
                    StrategyBacktestParam.strategy_id == dim,
                    StrategyBacktestParam.is_optimal == True,  # noqa: E712
                )
                .first()
            )
            if opt and opt.win_rate_test is not None and opt.win_rate_test < MIN_WIN_RATE:
                logger.info(f"[StrategyMiner] {dim} 勝率 {opt.win_rate_test:.1%} < {MIN_WIN_RATE:.0%}，跳過")
                opt = None
            optimal[dim] = opt

        # 查最新收盤價（每檔股票各取自己最後一個有成交的收盤價）
        stock_ids = list({r.stock_id for r in rows})
        from sqlalchemy import func as sa_func, and_
        # 子查詢：每股最新有收盤的日期
        sub = (
            db.query(
                StockPrice.stock_id,
                sa_func.max(StockPrice.date).label("max_date"),
            )
            .filter(
                StockPrice.stock_id.in_(stock_ids),
                StockPrice.close > 0,
            )
            .group_by(StockPrice.stock_id)
            .subquery()
        )
        price_rows = (
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
        price_map: Dict[str, float] = {r.stock_id: float(r.close) for r in price_rows if r.close}

        # 分維度去重，同股票同維度保留 trigger_count 最高者
        by_dim: Dict[str, Dict[str, AlphaSignalHistory]] = {}
        for r in rows:
            if optimal.get(r.time_dimension) is None and not cls._default_params(r.time_dimension):
                continue  # 該維度被勝率門檻淘汰
            dim_map = by_dim.setdefault(r.time_dimension, {})
            existing = dim_map.get(r.stock_id)
            if existing is None or r.trigger_count > existing.trigger_count:
                dim_map[r.stock_id] = r

        # 訊號強度過濾：每個維度只保留 trigger_count >= P70 的訊號
        for dim, dim_map in by_dim.items():
            if not dim_map:
                continue
            counts = sorted([r.trigger_count for r in dim_map.values()])
            p70_idx = int(len(counts) * TRIGGER_COUNT_PERCENTILE)
            p70_val = counts[min(p70_idx, len(counts) - 1)]
            before = len(dim_map)
            by_dim[dim] = {sid: r for sid, r in dim_map.items() if r.trigger_count >= p70_val}
            after = len(by_dim[dim])
            logger.info(f"[StrategyMiner] {dim} 觸發數門檻 >= {p70_val}: {before} → {after} 筆")

        # 合併：收集每檔股票出現的所有維度��多維共鳴加分 10%/維度）
        combined: Dict[str, dict] = {}
        for dim, dim_map in by_dim.items():
            for stock_id, r in dim_map.items():
                base_score = r.trigger_count * (r.weighted_odds_ratio or 1.0)
                if stock_id not in combined:
                    combined[stock_id] = {
                        'primary': r,           # 主要維度（得分最高者）
                        'dims': [dim],
                        'score': base_score,
                    }
                else:
                    combined[stock_id]['dims'].append(dim)
                    if base_score > combined[stock_id]['score']:
                        combined[stock_id]['primary'] = r
                        combined[stock_id]['score'] = base_score
                    # 多維共鳴加分：每額外維度 +10%
                    combined[stock_id]['score'] *= 1.10

        # 計算最終分數，排序，取前 MAX_PICKS_PER_DIRECTION
        sorted_combined = sorted(
            combined.values(),
            key=lambda x: x['score'],
            reverse=True,
        )[:MAX_PICKS_PER_DIRECTION]

        # pick_date 用今天日期（推薦供明日操作），而非 signal_date
        pick_date = date.today()

        # 從 AlphaMinerSnapshot 的 details_json 建立買入理由 map
        # 找出哪些顯著策略（is_significant=True）在 recent_signals 裡有這支股票
        reasons_map: Dict[str, List[str]] = {}
        try:
            snap = (
                db.query(AlphaMinerSnapshot)
                .order_by(AlphaMinerSnapshot.train_date.desc())
                .first()
            )
            if snap:
                result_data = json.loads(snap.result_json)
                details_data = json.loads(snap.details_json)
                # 建立 strategy_id → strategy_name 的映射（僅顯著策略）
                sig_name_map: Dict[str, str] = {}
                for s in result_data.get('strategies', []):
                    if s.get('is_significant') and s.get('ic', 0) > 0:
                        sig_name_map[s['strategy_id']] = s['strategy_name']
                # 反向掃描：哪些顯著策略最近觸發了這支股票
                stock_strategy_names: Dict[str, List[str]] = {}
                for strat_id, name in sig_name_map.items():
                    detail = details_data.get(strat_id, {})
                    for sig in detail.get('recent_signals', []):
                        sid = sig.get('stock_id')
                        if sid:
                            lst = stock_strategy_names.setdefault(sid, [])
                            if name not in lst:
                                lst.append(name)
                # 每股最多保留 3 個策略名稱
                reasons_map = {k: v[:3] for k, v in stock_strategy_names.items()}
        except Exception as e:
            logger.warning(f"[StrategyMiner] 買入理由建立失敗: {e}")

        # 刪除今日已有的做多 picks（idempotent）
        db.execute(
            delete(StrategyMinerPick).where(
                StrategyMinerPick.pick_date == pick_date,
                StrategyMinerPick.direction == 'long',
            )
        )

        count = 0
        for item in sorted_combined:
            r = item['primary']
            dims = sorted(set(item['dims']))
            opt_params = optimal.get(r.time_dimension)
            entry_price = price_map.get(r.stock_id, 0.0)

            # fallback 參數：若尚無回測結果，用維度預設值
            if opt_params:
                tp = opt_params.take_profit_pct
                sl = opt_params.stop_loss_pct
                hd = opt_params.hold_days_max
            else:
                tp, sl, hd = cls._default_params(r.time_dimension)

            reasons = reasons_map.get(r.stock_id, [])

            db.add(StrategyMinerPick(
                pick_date=pick_date,
                stock_id=r.stock_id,
                stock_name=r.stock_name,
                strategy_ids=json.dumps(dims),
                weighted_score=round(item['score'], 4),
                entry_price=entry_price,
                take_profit_pct=tp,
                stop_loss_pct=sl,
                hold_days_max=hd,
                time_dimension=r.time_dimension,
                direction='long',
                buy_reasons=json.dumps(reasons, ensure_ascii=False) if reasons else None,
            ))
            count += 1

        # ─── 放空推薦 ──────────────────────────────────────────────────────────
        short_count = cls._generate_short_picks(db, latest_date, pick_date, price_map)
        count += short_count

        db.commit()
        logger.info(f"[StrategyMiner] 今日推薦清單已生成 {count} 筆（做多+放空，{pick_date}）")
        return count

    @classmethod
    def _generate_short_picks(
        cls, db: Session, latest_date, pick_date, price_map: Dict[str, float],
    ) -> int:
        """生成放空推薦，從 alpha_signal_history 的 short 訊號中取出。"""
        short_rows = (
            db.query(AlphaSignalHistory)
            .filter(
                AlphaSignalHistory.signal_date == latest_date,
                AlphaSignalHistory.direction == 'short',
            )
            .all()
        )
        if not short_rows:
            # 沒有歷史放空訊號時，直接從 Alpha Miner 即時產生
            from app.services.alpha_miner_service import AlphaMinerService
            short_signals = []
            for dim in DIMENSIONS:
                sigs = AlphaMinerService.get_today_signals(db, dimension=dim, direction='short')
                short_signals.extend(sigs)
            if not short_signals:
                return 0
            # 去重（同股票保留分數最高者）
            best: Dict[str, dict] = {}
            for s in short_signals:
                if s.stock_id not in best or s.trigger_count > best[s.stock_id]['score']:
                    best[s.stock_id] = {
                        'stock_id': s.stock_id,
                        'stock_name': s.stock_name,
                        'score': s.trigger_count,
                        'reasons': s.strategies,
                        'time_dimension': s.time_dimension,
                    }
            sorted_shorts = sorted(best.values(), key=lambda x: x['score'], reverse=True)
        else:
            # 從歷史訊號中取
            best = {}
            for r in short_rows:
                if r.stock_id not in best or r.trigger_count > best[r.stock_id].trigger_count:
                    best[r.stock_id] = r
            sorted_shorts = sorted(
                [{'stock_id': r.stock_id, 'stock_name': r.stock_name,
                  'score': r.trigger_count, 'reasons': [],
                  'time_dimension': r.time_dimension}
                 for r in best.values()],
                key=lambda x: x['score'], reverse=True,
            )

        # 過濾：只保留有歷史訊號資料的股票（無資料 = 無法驗證，不推薦）
        from datetime import timedelta as _td
        _cutoff = date.today() - _td(days=180)
        _short_sids_all = [s['stock_id'] for s in sorted_shorts]
        if _short_sids_all:
            _has_history = set(
                row.stock_id for row in
                db.query(AlphaSignalHistory.stock_id)
                .filter(
                    AlphaSignalHistory.stock_id.in_(_short_sids_all),
                    AlphaSignalHistory.is_resolved == True,  # noqa: E712
                    AlphaSignalHistory.actual_return.isnot(None),
                    AlphaSignalHistory.signal_date >= _cutoff,
                )
                .distinct()
                .all()
            )
            before = len(sorted_shorts)
            sorted_shorts = [s for s in sorted_shorts if s['stock_id'] in _has_history]
            if len(sorted_shorts) < before:
                logger.info(f"[StrategyMiner] 放空過濾無歷史資料: {before} → {len(sorted_shorts)} 筆")

        sorted_shorts = sorted_shorts[:MAX_PICKS_PER_DIRECTION]

        # 為放空股票即時補上看空理由（從 stock_features 判斷）
        short_sids = [s['stock_id'] for s in sorted_shorts]
        if short_sids:
            from app.models.stock_feature import StockFeature
            from sqlalchemy import func as sa_func_r
            feat_date = db.query(sa_func_r.max(StockFeature.date)).scalar()
            if feat_date:
                feats = db.query(StockFeature).filter(
                    StockFeature.date == feat_date,
                    StockFeature.stock_id.in_(short_sids),
                ).all()
                feat_map = {f.stock_id: f for f in feats}
                for item in sorted_shorts:
                    f = feat_map.get(item['stock_id'])
                    if not f:
                        continue
                    reasons = []
                    if f.rsi14 is not None and f.rsi14 > 70:
                        reasons.append('RSI 超買')
                    if f.k is not None and f.d is not None and f.k > 80 and f.k < f.d:
                        reasons.append('KD 高檔死叉')
                    if f.macd_osc is not None and f.macd_osc < 0:
                        reasons.append('MACD 空頭')
                    if f.bias20 is not None and f.bias20 > 5:
                        reasons.append('乖離率偏高')
                    if hasattr(f, 'foreign_buy_5d') and f.foreign_buy_5d is not None and f.foreign_buy_5d < 0:
                        reasons.append('外資賣超')
                    if hasattr(f, 'trust_buy_5d') and f.trust_buy_5d is not None and f.trust_buy_5d < 0:
                        reasons.append('投信賣超')
                    item['reasons'] = reasons[:3]

        # 為放空股票查詢最新收盤價（做多的 price_map 可能沒有這些股票）
        short_stock_ids = [s['stock_id'] for s in sorted_shorts if s['stock_id'] not in price_map]
        if short_stock_ids:
            from sqlalchemy import func as sa_func, and_
            sub = (
                db.query(StockPrice.stock_id, sa_func.max(StockPrice.date).label("max_date"))
                .filter(StockPrice.stock_id.in_(short_stock_ids), StockPrice.close > 0)
                .group_by(StockPrice.stock_id).subquery()
            )
            for r in db.query(StockPrice.stock_id, StockPrice.close).join(
                sub, and_(StockPrice.stock_id == sub.c.stock_id, StockPrice.date == sub.c.max_date)
            ).all():
                if r.close:
                    price_map[r.stock_id] = float(r.close)

        # 刪除今日已有的放空 picks
        db.execute(
            delete(StrategyMinerPick).where(
                StrategyMinerPick.pick_date == pick_date,
                StrategyMinerPick.direction == 'short',
            )
        )

        count = 0
        for item in sorted_shorts:
            entry_price = price_map.get(item['stock_id'], 0.0)
            # 放空用較保守的預設參數
            tp, sl, hd = cls._default_params(item.get('time_dimension', '10d'))

            db.add(StrategyMinerPick(
                pick_date=pick_date,
                stock_id=item['stock_id'],
                stock_name=item['stock_name'],
                strategy_ids=json.dumps([item.get('time_dimension', '10d')]),
                weighted_score=round(item['score'], 4),
                entry_price=entry_price,
                take_profit_pct=tp,
                stop_loss_pct=sl,
                hold_days_max=hd,
                time_dimension=item.get('time_dimension', '10d'),
                direction='short',
                buy_reasons=json.dumps(item.get('reasons', []), ensure_ascii=False) or None,
            ))
            count += 1

        logger.info(f"[StrategyMiner] 放空推薦 {count} 筆")
        return count

    # ─── 查詢介面 ──────────────────────────────────────────────────────────────
    @classmethod
    def get_today_picks(cls, db: Session) -> List[StrategyMinerPick]:
        today = date.today()
        picks = (
            db.query(StrategyMinerPick)
            .filter(StrategyMinerPick.pick_date == today)
            .order_by(StrategyMinerPick.weighted_score.desc())
            .all()
        )
        if not picks:
            # fallback: 最近一次 picks
            latest = (
                db.query(StrategyMinerPick.pick_date)
                .order_by(StrategyMinerPick.pick_date.desc())
                .first()
            )
            if latest:
                picks = (
                    db.query(StrategyMinerPick)
                    .filter(StrategyMinerPick.pick_date == latest.pick_date)
                    .order_by(StrategyMinerPick.weighted_score.desc())
                    .all()
                )
        return picks

    @classmethod
    def get_picks_history(cls, db: Session, days: int = 7) -> List[StrategyMinerPick]:
        cutoff = date.today() - timedelta(days=days)
        return (
            db.query(StrategyMinerPick)
            .filter(
                StrategyMinerPick.pick_date >= cutoff,
                StrategyMinerPick.pick_date < date.today(),  # 排除今日（今日在「明日建議買入」顯示）
            )
            .order_by(StrategyMinerPick.pick_date.desc(), StrategyMinerPick.weighted_score.desc())
            .all()
        )

    @classmethod
    def get_trades(cls, db: Session, stock_id: str) -> List[StrategyMinerTrade]:
        return (
            db.query(StrategyMinerTrade)
            .filter(StrategyMinerTrade.stock_id == stock_id)
            .order_by(StrategyMinerTrade.entry_date.desc())
            .all()
        )

    @classmethod
    def get_performance(cls, db: Session) -> dict:
        """整體績效統計（所有維度的最優參數回測結果）"""
        opt_params = (
            db.query(StrategyBacktestParam)
            .filter(StrategyBacktestParam.is_optimal == True)  # noqa: E712
            .all()
        )
        result = {}
        for p in opt_params:
            result[p.strategy_id] = {
                'take_profit_pct': p.take_profit_pct,
                'stop_loss_pct': p.stop_loss_pct,
                'hold_days_max': p.hold_days_max,
                'sharpe_train': p.sharpe_train,
                'sharpe_test': p.sharpe_test,
                'win_rate_test': p.win_rate_test,
                'avg_return_test': p.avg_return_test,
                'trade_count_test': p.trade_count_test,
                'computed_at': p.computed_at.isoformat() if p.computed_at else None,
            }
        return result

    # ─── 核心回測引擎 ──────────────────────────────────────────────────────────
    @classmethod
    def _optimize_dimension(cls, db: Session, dimension: str, direction: str = 'long') -> None:
        strategy_key = f"{dimension}_{direction}" if direction == 'short' else dimension
        logger.info(f"[StrategyMiner] 開始 {strategy_key} 維度參數尋優")

        # 載入歷史訊號（按 direction 過濾）
        cutoff = date.today() - timedelta(days=365 * 2)
        signal_rows = (
            db.query(AlphaSignalHistory)
            .filter(
                AlphaSignalHistory.time_dimension == dimension,
                AlphaSignalHistory.direction == direction,
                AlphaSignalHistory.signal_date >= cutoff,
            )
            .order_by(AlphaSignalHistory.signal_date)
            .all()
        )
        if len(signal_rows) < 20:
            logger.info(f"[StrategyMiner] {strategy_key} 訊號不足（{len(signal_rows)} 筆），跳過")
            return

        signals_df = pd.DataFrame([{
            'signal_date': r.signal_date,
            'stock_id': r.stock_id,
            'stock_name': r.stock_name,
        } for r in signal_rows])

        # 載入相關股票價格
        stock_ids = signals_df['stock_id'].unique().tolist()
        price_dict, sorted_dates_dict, open_dict = cls._load_prices(db, stock_ids, cutoff)

        # 訓練/測試切割（4/6 訓練、2/6 測試）
        n = len(signals_df)
        split_idx = n * 4 // 6
        train_df = signals_df.iloc[:split_idx].copy()
        test_df  = signals_df.iloc[split_idx:].copy()

        if len(train_df) < 10 or len(test_df) < 5:
            logger.info(f"[StrategyMiner] {dimension} 訓練/測試集樣本不足，跳過")
            return

        is_short = (direction == 'short')

        # 跑 18 組參數（訓練集）
        train_trades = cls._simulate_all_params(train_df, price_dict, sorted_dates_dict, is_short=is_short, open_dict=open_dict)

        # 找訓練集 Sharpe 前三
        train_sharpes: List[Tuple[int, float]] = []
        for param_idx, trades in enumerate(train_trades):
            s = _sharpe([t['return_pct'] for t in trades])
            train_sharpes.append((param_idx, s))
        train_sharpes.sort(key=lambda x: x[1], reverse=True)
        sharpe_by_param = {idx: s for idx, s in train_sharpes}
        top3_indices = [x[0] for x in train_sharpes[:3]]

        # 跑前三（測試集）
        top3_params = [PARAMS_LIST[i] for i in top3_indices]
        test_trades_raw = cls._simulate_entries(test_df, price_dict, sorted_dates_dict, top3_params, is_short=is_short, open_dict=open_dict)

        # 選測試集最穩定者
        best_idx_in_top3 = 0
        best_test_sharpe = -float('inf')
        for i, trades in enumerate(test_trades_raw):
            s = _sharpe([t['return_pct'] for t in trades])
            if s > best_test_sharpe:
                best_test_sharpe = s
                best_idx_in_top3 = i
        optimal_param_idx = top3_indices[best_idx_in_top3]
        optimal_params = PARAMS_LIST[optimal_param_idx]

        # 儲存 18 組回測結果到 strategy_backtest_params
        today = date.today()
        db.execute(
            delete(StrategyBacktestParam).where(StrategyBacktestParam.strategy_id == strategy_key)
        )
        for param_idx, params in enumerate(PARAMS_LIST):
            tr_sharpe = sharpe_by_param.get(param_idx, 0.0)
            # find test sharpe for this param (if in top3)
            te_sharpe = 0.0
            te_win = 0.0
            te_avg = 0.0
            te_count = 0
            if param_idx in top3_indices:
                top3_pos = top3_indices.index(param_idx)
                te_trades = test_trades_raw[top3_pos]
                te_sharpe = _sharpe([t['return_pct'] for t in te_trades])
                if te_trades:
                    returns = [t['return_pct'] for t in te_trades]
                    te_win = sum(1 for r in returns if r > 0) / len(returns)
                    te_avg = float(np.mean(returns))
                    te_count = len(returns)

            # recalculate train sharpe per param_idx
            tr_trades = train_trades[param_idx]
            tr_sharpe_val = _sharpe([t['return_pct'] for t in tr_trades])

            db.add(StrategyBacktestParam(
                strategy_id=strategy_key,
                take_profit_pct=params['take_profit_pct'],
                stop_loss_pct=params['stop_loss_pct'],
                hold_days_max=params['hold_days'],
                sharpe_train=round(tr_sharpe_val, 4),
                sharpe_test=round(te_sharpe, 4),
                win_rate_test=round(te_win, 4),
                avg_return_test=round(te_avg, 4),
                trade_count_test=te_count,
                is_optimal=(param_idx == optimal_param_idx),
                computed_at=today,
            ))

        db.commit()
        logger.info(
            f"[StrategyMiner] {strategy_key} 最優參數: "
            f"TP={optimal_params['take_profit_pct']*100}% "
            f"SL={optimal_params['stop_loss_pct']*100}% "
            f"HD={optimal_params['hold_days']}天"
        )

        # 以最優參數跑全部訊號，儲存逐筆交易記錄
        all_trades_by_param = cls._simulate_entries(
            signals_df, price_dict, sorted_dates_dict, [optimal_params], is_short=is_short, open_dict=open_dict,
        )
        optimal_all_trades = all_trades_by_param[0]

        db.execute(
            delete(StrategyMinerTrade).where(StrategyMinerTrade.strategy_id == strategy_key)
        )
        for t in optimal_all_trades:
            db.add(StrategyMinerTrade(
                strategy_id=strategy_key,
                stock_id=t['stock_id'],
                entry_date=t['entry_date'],
                entry_price=t['entry_price'],
                exit_date=t['exit_date'],
                exit_price=t['exit_price'],
                exit_reason=t['exit_reason'],
                return_pct=t['return_pct'],
                hold_days=t['hold_days'],
            ))
        db.commit()
        logger.info(f"[StrategyMiner] {strategy_key} 逐筆交易已儲存 {len(optimal_all_trades)} 筆")

    @classmethod
    def _simulate_all_params(
        cls,
        signals_df: pd.DataFrame,
        price_dict: Dict,
        sorted_dates_dict: Dict,
        is_short: bool = False,
        open_dict: Optional[Dict] = None,
    ) -> List[List[dict]]:
        """對所有 18 組參數進行回測，回傳 list of 18 trade lists"""
        return cls._simulate_entries(signals_df, price_dict, sorted_dates_dict, PARAMS_LIST, is_short=is_short, open_dict=open_dict)

    @classmethod
    def _simulate_entries(
        cls,
        signals_df: pd.DataFrame,
        price_dict: Dict[str, Dict],
        sorted_dates_dict: Dict[str, List],
        params_list: List[dict],
        is_short: bool = False,
        open_dict: Optional[Dict[str, Dict]] = None,
    ) -> List[List[dict]]:
        """對指定參數列表模擬回測，回傳每組參數的交易記錄列表"""
        results: List[List[dict]] = [[] for _ in params_list]
        max_hold = max(p['hold_days'] for p in params_list)

        # 預先建立 O(1) 日期 → 索引查找表，避免 list.index() 的 O(n) 搜尋
        date_idx: Dict[str, Dict] = {
            sid: {d: i for i, d in enumerate(dates)}
            for sid, dates in sorted_dates_dict.items()
        }

        for _, row in signals_df.iterrows():
            signal_date = row['signal_date']
            stock_id = str(row['stock_id'])

            px = price_dict.get(stock_id)
            dates = sorted_dates_dict.get(stock_id)
            if not px or not dates:
                continue

            # 找 signal_date 在 dates 中的位置（O(1) 查找）
            sig_idx = date_idx.get(stock_id, {}).get(signal_date)
            if sig_idx is None:
                continue

            # 進場價：隔日開盤價（更貼近實際操作）
            if sig_idx + 1 >= len(dates):
                continue
            next_date = dates[sig_idx + 1]
            if open_dict and stock_id in open_dict and next_date in open_dict[stock_id]:
                entry_price = open_dict[stock_id][next_date]
            else:
                # fallback：隔日收盤（open 不存在時）
                entry_price = px.get(next_date, 0)
            if not entry_price or entry_price <= 0:
                continue

            # 取隔日(含)之後 max_hold+5 個交易日的收盤
            fwd_dates = dates[sig_idx + 1 : sig_idx + 1 + max_hold + 5]
            if not fwd_dates:
                continue

            fwd_returns = np.array(
                [(px[d] - entry_price) / entry_price for d in fwd_dates],
                dtype=float,
            )

            for param_idx, params in enumerate(params_list):
                tp = params['take_profit_pct']
                sl = params['stop_loss_pct']
                max_days = params['hold_days']

                n_fwd = min(max_days, len(fwd_returns))
                if n_fwd == 0:
                    continue
                r = fwd_returns[:n_fwd]

                if is_short:
                    # 放空：股價下跌 = 獲利，上漲 = 虧損
                    tp_hits = np.where(r <= -tp)[0]   # 跌到 TP = 停利
                    sl_hits = np.where(r >= sl)[0]    # 漲到 SL = 停損
                else:
                    tp_hits = np.where(r >= tp)[0]
                    sl_hits = np.where(r <= -sl)[0]

                tp_day = int(tp_hits[0]) if len(tp_hits) > 0 else n_fwd
                sl_day = int(sl_hits[0]) if len(sl_hits) > 0 else n_fwd

                if tp_day <= sl_day and tp_day < n_fwd:
                    exit_idx = tp_day
                    exit_reason = 'take_profit'
                elif sl_day < tp_day and sl_day < n_fwd:
                    exit_idx = sl_day
                    exit_reason = 'stop_loss'
                else:
                    exit_idx = n_fwd - 1
                    exit_reason = 'time_limit'

                # 放空報酬反轉
                raw_return = float(r[exit_idx])
                exit_return = -raw_return if is_short else raw_return
                results[param_idx].append({
                    'stock_id': stock_id,
                    'entry_date': signal_date,
                    'entry_price': entry_price,
                    'exit_date': fwd_dates[exit_idx],
                    'exit_price': round(entry_price * (1 + exit_return), 2),
                    'exit_reason': exit_reason,
                    'return_pct': round(exit_return * 100, 4),
                    'hold_days': exit_idx + 1,
                })

        return results

    @classmethod
    def _load_prices(
        cls,
        db: Session,
        stock_ids: List[str],
        cutoff: date,
    ) -> Tuple[Dict[str, Dict], Dict[str, List]]:
        """批次載入股票歷史 open + close 價格"""
        rows = (
            db.query(StockPrice.stock_id, StockPrice.date, StockPrice.open, StockPrice.close)
            .filter(
                StockPrice.stock_id.in_(stock_ids),
                StockPrice.date >= cutoff,
                StockPrice.close.isnot(None),
            )
            .order_by(StockPrice.stock_id, StockPrice.date)
            .all()
        )

        price_dict: Dict[str, Dict] = {}     # {stock_id: {date: close}}
        open_dict: Dict[str, Dict] = {}      # {stock_id: {date: open}}
        sorted_dates_dict: Dict[str, List] = {}

        for r in rows:
            sid = str(r.stock_id)
            if sid not in price_dict:
                price_dict[sid] = {}
                open_dict[sid] = {}
                sorted_dates_dict[sid] = []
            price_dict[sid][r.date] = float(r.close)
            if r.open:
                open_dict[sid][r.date] = float(r.open)
            sorted_dates_dict[sid].append(r.date)

        return price_dict, sorted_dates_dict, open_dict

    @staticmethod
    def _default_params(dimension: str) -> Tuple[float, float, int]:
        """當尚無回測結果時的 fallback 參數"""
        if dimension == '30d':
            return 0.08, 0.05, 20
        return 0.05, 0.03, 10

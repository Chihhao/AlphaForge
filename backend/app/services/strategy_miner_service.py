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
        若訊號不足（< 20）則跳過該維度。
        """
        for dim in DIMENSIONS:
            try:
                cls._optimize_dimension(db, dim)
            except Exception as e:
                logger.error(f"[StrategyMiner] {dim} 尋優失敗: {e}", exc_info=True)

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

        # 查當日訊號（所有維度）
        rows = (
            db.query(AlphaSignalHistory)
            .filter(AlphaSignalHistory.signal_date == latest_date)
            .all()
        )
        if not rows:
            return 0

        # 查各維度最優參數
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
            dim_map = by_dim.setdefault(r.time_dimension, {})
            existing = dim_map.get(r.stock_id)
            if existing is None or r.trigger_count > existing.trigger_count:
                dim_map[r.stock_id] = r

        # 合併：收集每檔股票出現的所有維度（多維共鳴加分 10%/維度）
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

        # 計算最終分數，排序，取前 10
        sorted_combined = sorted(
            combined.values(),
            key=lambda x: x['score'],
            reverse=True,
        )[:10]

        pick_date = date.today()
        # 刪除今日已有的 picks（idempotent）
        db.execute(
            delete(StrategyMinerPick).where(StrategyMinerPick.pick_date == pick_date)
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
            ))
            count += 1

        db.commit()
        logger.info(f"[StrategyMiner] 今日推薦清單已生成 {count} 筆（{pick_date}）")
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
            .filter(StrategyMinerPick.pick_date >= cutoff)
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
    def _optimize_dimension(cls, db: Session, dimension: str) -> None:
        logger.info(f"[StrategyMiner] 開始 {dimension} 維度參數尋優")

        # 載入歷史訊號
        cutoff = date.today() - timedelta(days=365 * 2)
        signal_rows = (
            db.query(AlphaSignalHistory)
            .filter(
                AlphaSignalHistory.time_dimension == dimension,
                AlphaSignalHistory.signal_date >= cutoff,
            )
            .order_by(AlphaSignalHistory.signal_date)
            .all()
        )
        if len(signal_rows) < 20:
            logger.info(f"[StrategyMiner] {dimension} 訊號不足（{len(signal_rows)} 筆），跳過")
            return

        signals_df = pd.DataFrame([{
            'signal_date': r.signal_date,
            'stock_id': r.stock_id,
            'stock_name': r.stock_name,
        } for r in signal_rows])

        # 載入相關股票價格
        stock_ids = signals_df['stock_id'].unique().tolist()
        price_dict, sorted_dates_dict = cls._load_prices(db, stock_ids, cutoff)

        # 訓練/測試切割（4/6 訓練、2/6 測試）
        n = len(signals_df)
        split_idx = n * 4 // 6
        train_df = signals_df.iloc[:split_idx].copy()
        test_df  = signals_df.iloc[split_idx:].copy()

        if len(train_df) < 10 or len(test_df) < 5:
            logger.info(f"[StrategyMiner] {dimension} 訓練/測試集樣本不足，跳過")
            return

        # 跑 18 組參數（訓練集）
        train_trades = cls._simulate_all_params(train_df, price_dict, sorted_dates_dict)

        # 找訓練集 Sharpe 前三
        train_sharpes: List[Tuple[int, float]] = []
        for param_idx, trades in enumerate(train_trades):
            s = _sharpe([t['return_pct'] for t in trades])
            train_sharpes.append((param_idx, s))
        train_sharpes.sort(key=lambda x: x[1], reverse=True)
        top3_indices = [x[0] for x in train_sharpes[:3]]

        # 跑前三（測試集）
        top3_params = [PARAMS_LIST[i] for i in top3_indices]
        test_trades_raw = cls._simulate_entries(test_df, price_dict, sorted_dates_dict, top3_params)

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
            delete(StrategyBacktestParam).where(StrategyBacktestParam.strategy_id == dimension)
        )
        for param_idx, params in enumerate(PARAMS_LIST):
            tr_sharpe = train_sharpes[param_idx][1] if param_idx < len(train_sharpes) else 0.0
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
                strategy_id=dimension,
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
            f"[StrategyMiner] {dimension} 最優參數: "
            f"TP={optimal_params['take_profit_pct']*100}% "
            f"SL={optimal_params['stop_loss_pct']*100}% "
            f"HD={optimal_params['hold_days']}天"
        )

        # 以最優參數跑全部訊號，儲存逐筆交易記錄
        all_trades_by_param = cls._simulate_entries(signals_df, price_dict, sorted_dates_dict, [optimal_params])
        optimal_all_trades = all_trades_by_param[0]

        db.execute(
            delete(StrategyMinerTrade).where(StrategyMinerTrade.strategy_id == dimension)
        )
        for t in optimal_all_trades:
            db.add(StrategyMinerTrade(
                strategy_id=dimension,
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
        logger.info(f"[StrategyMiner] {dimension} 逐筆交易已儲存 {len(optimal_all_trades)} 筆")

    @classmethod
    def _simulate_all_params(
        cls,
        signals_df: pd.DataFrame,
        price_dict: Dict,
        sorted_dates_dict: Dict,
    ) -> List[List[dict]]:
        """對所有 18 組參數進行回測，回傳 list of 18 trade lists"""
        return cls._simulate_entries(signals_df, price_dict, sorted_dates_dict, PARAMS_LIST)

    @classmethod
    def _simulate_entries(
        cls,
        signals_df: pd.DataFrame,
        price_dict: Dict[str, Dict],
        sorted_dates_dict: Dict[str, List],
        params_list: List[dict],
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

            # 查進場價（signal_date 收盤）
            entry_price = px.get(signal_date)
            if not entry_price or entry_price <= 0:
                continue

            # 找 signal_date 在 dates 中的位置（O(1) 查找）
            sig_idx = date_idx.get(stock_id, {}).get(signal_date)
            if sig_idx is None:
                continue

            # 取後續 max_hold+5 個交易日的收盤
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

                exit_return = float(r[exit_idx])
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
        """批次載入股票歷史收盤價，回傳 price_dict 和 sorted_dates_dict"""
        rows = (
            db.query(StockPrice.stock_id, StockPrice.date, StockPrice.close)
            .filter(
                StockPrice.stock_id.in_(stock_ids),
                StockPrice.date >= cutoff,
                StockPrice.close.isnot(None),
            )
            .order_by(StockPrice.stock_id, StockPrice.date)
            .all()
        )

        price_dict: Dict[str, Dict] = {}
        sorted_dates_dict: Dict[str, List] = {}

        for r in rows:
            sid = str(r.stock_id)
            if sid not in price_dict:
                price_dict[sid] = {}
                sorted_dates_dict[sid] = []
            price_dict[sid][r.date] = float(r.close)
            sorted_dates_dict[sid].append(r.date)

        return price_dict, sorted_dates_dict

    @staticmethod
    def _default_params(dimension: str) -> Tuple[float, float, int]:
        """當尚無回測結果時的 fallback 參數"""
        if dimension == '30d':
            return 0.08, 0.05, 20
        return 0.05, 0.03, 10

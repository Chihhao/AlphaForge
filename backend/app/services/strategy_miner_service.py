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
from app.models.stock_feature import StockFeature

logger = logging.getLogger(__name__)

# ─── 參數組合（持有天數與維度對齊）──────────────────────────────────────────────
TP_ATR_MULTIPLIERS = [1.5, 2.5, 3.5]   # 停利 = N × ATR
SL_ATR_MULTIPLIERS = [1.0, 1.5, 2.0]   # 停損 = M × ATR
DIM_HOLD_DAYS = {'5d': 5, '10d': 10, '20d': 20}
ROUND_TRIP_COST = 0.006   # 來回交易成本 ~0.6%（手續費 0.1425%×2 + 交易稅 0.3%）


def get_params_list(dimension: str) -> list:
    """回傳指定維度的參數組合（9 種：3 TP × 3 SL × 1 HD）"""
    hd = DIM_HOLD_DAYS[dimension]
    return [
        {'tp_atr_mult': tp, 'sl_atr_mult': sl, 'hold_days': hd}
        for tp in TP_ATR_MULTIPLIERS
        for sl in SL_ATR_MULTIPLIERS
    ]  # 9 combos

DIMENSIONS = ['5d', '10d', '20d']

# ─── 訊號品質門檻 ─────────────────────────────────────────────────────────────
TRIGGER_COUNT_PERCENTILE = 0.70   # 觸發數需 >= 該維度 P70
EXCESS_WIN_RATE_THRESHOLD = 0.05  # 超額勝率需 > baseline + 5pp
MAX_PICKS_PER_DIRECTION = 5       # 做多/放空各最多推薦 5 檔


def _sharpe(returns: List[float]) -> float:
    if len(returns) < 3:
        return 0.0
    arr = np.array(returns, dtype=float)
    std = arr.std()
    if std < 1e-9:
        return 0.0
    return float(arr.mean() / std)


def _load_stock_perf_map(
    db: Session, stock_ids: list, direction: str = 'long'
) -> dict:
    """載入指定股票的回測交易績效（strategy_miner_trades）。

    查詢所有活躍維度（DIMENSIONS）的 trades，每檔股票取平均報酬最高
    的維度作為 stock_best_dim。

    回傳 {stock_id: {stock_win_rate, stock_avg_return, stock_trade_count, stock_best_dim}}
    """
    if not stock_ids:
        return {}
    from collections import defaultdict
    target_ids = [f"{d}_short" if direction == 'short' else d for d in DIMENSIONS]
    rows = (
        db.query(StrategyMinerTrade)
        .filter(
            StrategyMinerTrade.stock_id.in_(stock_ids),
            StrategyMinerTrade.strategy_id.in_(target_ids),
        )
        .all()
    )
    # {stock_id: {dim: [return_pct, ...]}}
    by_stock_dim: dict = defaultdict(lambda: defaultdict(list))
    for r in rows:
        dim = r.strategy_id.replace('_short', '')
        by_stock_dim[r.stock_id][dim].append(r.return_pct)
    result = {}
    for sid, dim_rets in by_stock_dim.items():
        best_dim = None
        best_avg = -999.0
        total_rets: list = []
        for dim, rets in dim_rets.items():
            avg = sum(rets) / len(rets) if rets else -999.0
            if avg > best_avg:
                best_avg = avg
                best_dim = dim
            total_rets.extend(rets)
        if not total_rets:
            continue
        wins = sum(1 for x in total_rets if x > 0)
        result[sid] = {
            "stock_win_rate": round(wins / len(total_rets), 4),
            "stock_avg_return": round(sum(total_rets) / len(total_rets), 1),
            "stock_trade_count": len(total_rets),
            "stock_best_dim": best_dim or DIMENSIONS[0],
        }
    return result


def _load_stock_perf_from_picks(
    db: Session, stock_ids: list, direction: str = 'long',
) -> dict:
    """基於 strategy_miner_picks 的真實推薦紀錄, 逐筆用當時存的 tp/sl/hd
    追蹤後續 stock_prices 判定結案, 計算勝率/均報酬/筆數/最佳維度。

    已結案筆數 = tp/sl 觸發 + 到 hold_days_max 到期。
    持有中不計入 ( 符合使用者「命中率視角」需求 )。

    回傳格式與 _load_stock_perf_map 一致, 方便端點層無縫替換。
    """
    if not stock_ids:
        return {}

    from collections import defaultdict

    picks = (
        db.query(StrategyMinerPick)
        .filter(
            StrategyMinerPick.stock_id.in_(stock_ids),
            StrategyMinerPick.direction == direction,
        )
        .all()
    )
    if not picks:
        return {}

    sids_set = {p.stock_id for p in picks}
    min_pick = min(p.pick_date for p in picks)
    today = date.today()

    price_rows = (
        db.query(StockPrice.stock_id, StockPrice.date, StockPrice.close)
        .filter(
            StockPrice.stock_id.in_(sids_set),
            StockPrice.date >= min_pick,
            StockPrice.date <= today,
            StockPrice.close > 0,
        )
        .all()
    )
    # dict 天然去重對抗 stock_prices 重複列
    price_map: dict = defaultdict(dict)
    for r in price_rows:
        price_map[r.stock_id][r.date] = float(r.close)

    by_stock_dim: dict = defaultdict(lambda: defaultdict(list))
    for p in picks:
        stock_prices = price_map.get(p.stock_id, {})
        # 明確傳 ROUND_TRIP_COST, 因 Task 1 default 為 0.0
        concluded = StrategyMinerService._evaluate_pick_concluded(
            p, stock_prices, round_trip_cost=ROUND_TRIP_COST,
        )
        if concluded is None:
            continue
        dim = (p.time_dimension or '20d').replace('_short', '')
        by_stock_dim[p.stock_id][dim].append(concluded['return_pct'])

    result = {}
    for sid, dim_rets in by_stock_dim.items():
        best_dim = None
        best_avg = -999.0
        total_rets: list = []
        for dim, rets in dim_rets.items():
            avg = sum(rets) / len(rets) if rets else -999.0
            if avg > best_avg:
                best_avg = avg
                best_dim = dim
            total_rets.extend(rets)
        if not total_rets:
            continue
        wins = sum(1 for x in total_rets if x > 0)
        result[sid] = {
            "stock_win_rate": round(wins / len(total_rets), 4),
            "stock_avg_return": round(sum(total_rets) / len(total_rets), 1),
            "stock_trade_count": len(total_rets),
            "stock_best_dim": best_dim or DIMENSIONS[0],
        }
    return result


def _load_market_baselines_from_snapshot(db: Session) -> Dict[str, float]:
    """從 Alpha Miner snapshot 取各維度市場基準勝率。
    回傳 {'5d': 0.194, '10d': 0.244, '30d': 0.261}"""
    from collections import defaultdict
    snap = (
        db.query(AlphaMinerSnapshot)
        .order_by(AlphaMinerSnapshot.train_date.desc())
        .first()
    )
    if not snap:
        return {}
    result_data = json.loads(snap.result_json)
    dim_rates: dict = defaultdict(list)
    for s in result_data.get('strategies', []):
        dim = s['time_dimension'].replace('_short', '')
        mwr = s.get('market_win_rate')
        if mwr is not None:
            dim_rates[dim].append(mwr)
    baselines = {}
    for dim, rates in dim_rates.items():
        rates.sort()
        baselines[dim] = rates[len(rates) // 2]
    return baselines


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
        pick_date = latest_date

        count = cls._generate_direction_picks(db, latest_date, pick_date, 'long')

        db.commit()
        logger.info(f"[StrategyMiner] 今日推薦清單已生成 {count} 筆（做多，{pick_date}）")
        return count

    @classmethod
    def _generate_direction_picks(
        cls, db: Session, latest_date, pick_date, direction: str,
    ) -> int:
        """生成指定方向（long/short）的推薦，管線與做多完全一致。"""
        from sqlalchemy import func as sa_func, and_
        dir_label = '做多' if direction == 'long' else '放空'

        # ─── Regime Filter：根據市場廣度動態調整推薦數量與門檻 ───
        from app.models.stock_feature import StockFeature as SF
        regime_row = (
            db.query(SF.market_breadth)
            .filter(SF.date == latest_date, SF.market_breadth.isnot(None))
            .first()
        )
        breadth = regime_row.market_breadth if regime_row else 0.5

        if direction == 'long':
            if breadth < 0.30:
                max_picks = 3
                trigger_pct = 0.80
            elif breadth < 0.45:
                max_picks = 4
                trigger_pct = 0.75
            else:
                max_picks = MAX_PICKS_PER_DIRECTION
                trigger_pct = TRIGGER_COUNT_PERCENTILE
        else:  # short
            if breadth > 0.70:
                max_picks = 3
                trigger_pct = 0.80
            elif breadth > 0.55:
                max_picks = 4
                trigger_pct = 0.75
            else:
                max_picks = MAX_PICKS_PER_DIRECTION
                trigger_pct = TRIGGER_COUNT_PERCENTILE

        logger.info(f"[StrategyMiner] {dir_label} Regime: breadth={breadth:.2f}, max_picks={max_picks}, trigger_pct={trigger_pct}")

        # 1. 查當日訊號
        rows = (
            db.query(AlphaSignalHistory)
            .filter(
                AlphaSignalHistory.signal_date == latest_date,
                AlphaSignalHistory.direction == direction,
            )
            .all()
        )
        if not rows:
            logger.info(f"[StrategyMiner] {dir_label} 無訊號（{latest_date}），跳過")
            return 0

        # 2. 查各維度最優參數 + 相對品質門檻
        baselines = _load_market_baselines_from_snapshot(db)
        optimal: Dict[str, Optional[StrategyBacktestParam]] = {}
        for dim in DIMENSIONS:
            strategy_key = f"{dim}_short" if direction == 'short' else dim
            opt = (
                db.query(StrategyBacktestParam)
                .filter(
                    StrategyBacktestParam.strategy_id == strategy_key,
                    StrategyBacktestParam.is_optimal == True,  # noqa: E712
                )
                .first()
            )
            if opt and opt.win_rate_test is not None:
                baseline = baselines.get(dim, 0.25)
                if opt.win_rate_test < baseline + EXCESS_WIN_RATE_THRESHOLD:
                    logger.info(
                        f"[StrategyMiner] {strategy_key} 勝率 {opt.win_rate_test:.1%} "
                        f"< baseline {baseline:.1%} + {EXCESS_WIN_RATE_THRESHOLD:.0%}，跳過")
                    opt = None
            optimal[dim] = opt

        # 3. 查收盤價：以 latest_date 為準切片（避免 walk-forward backfill 時寫入未來價）
        stock_ids = list({r.stock_id for r in rows})
        sub = (
            db.query(
                StockPrice.stock_id,
                sa_func.max(StockPrice.date).label("max_date"),
            )
            .filter(
                StockPrice.stock_id.in_(stock_ids),
                StockPrice.close > 0,
                StockPrice.date <= latest_date,
            )
            .group_by(StockPrice.stock_id)
            .subquery()
        )
        price_rows = (
            db.query(StockPrice.stock_id, StockPrice.close)
            .join(sub, and_(
                StockPrice.stock_id == sub.c.stock_id,
                StockPrice.date == sub.c.max_date,
            ))
            .all()
        )
        price_map: Dict[str, float] = {r.stock_id: float(r.close) for r in price_rows if r.close}

        # 4. 分維度去重，同股票同維度保留 trigger_count 最高者
        # 品管門檻：optimal[dim] 為 None 代表該維度沒過 baseline + 5pp 門檻，
        # 整個維度的訊號全部跳過 — 不再 fallback 到 _default_params 偷渡 picks。
        # 原本的 `not cls._default_params(...)` 是 dead check（永遠回 truthy tuple，
        # 整個 if 永遠 False），等於 quality gate 完全沒擋。
        by_dim: Dict[str, Dict[str, AlphaSignalHistory]] = {}
        for r in rows:
            if optimal.get(r.time_dimension) is None:
                continue
            dim_map = by_dim.setdefault(r.time_dimension, {})
            existing = dim_map.get(r.stock_id)
            if existing is None or r.trigger_count > existing.trigger_count:
                dim_map[r.stock_id] = r

        # 5. 訊號強度過濾：每個維度只保留 trigger_count >= P70
        for dim, dim_map in by_dim.items():
            if not dim_map:
                continue
            counts = sorted([r.trigger_count for r in dim_map.values()])
            p70_idx = int(len(counts) * trigger_pct)
            p70_val = counts[min(p70_idx, len(counts) - 1)]
            before = len(dim_map)
            by_dim[dim] = {sid: r for sid, r in dim_map.items() if r.trigger_count >= p70_val}
            after = len(by_dim[dim])
            logger.info(f"[StrategyMiner] {dir_label}/{dim} 觸發數門檻 >= {p70_val}: {before} → {after} 筆")

        # 6. per-dimension 排序 (每維度獨立 Top, 不再跨維度融合)
        #    共鳴資訊由 API 層動態計算 (同 pick_date+stock_id+direction 有幾個 dim)
        per_dim_sorted: Dict[str, list] = {}
        for dim, dim_map in by_dim.items():
            items = [
                {
                    'primary': r,
                    'score': r.trigger_count * (r.weighted_odds_ratio or 1.0),
                }
                for r in dim_map.values()
            ]
            per_dim_sorted[dim] = sorted(items, key=lambda x: x['score'], reverse=True)

        # 7. 從 AlphaMinerSnapshot 建立理由 map
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
                sig_name_map: Dict[str, str] = {}
                for s in result_data.get('strategies', []):
                    if not s.get('is_significant'):
                        continue
                    s_ic = s.get('ic', 0)
                    is_short_strat = 'short' in s.get('strategy_id', '')
                    # 做多只用 ic > 0，放空只用 ic < 0
                    if is_short_strat and s_ic >= 0:
                        continue
                    if not is_short_strat and s_ic <= 0:
                        continue
                    sid = s['strategy_id']
                    is_short_strat = 'short' in sid
                    if (direction == 'short') == is_short_strat:
                        sig_name_map[sid] = s['strategy_name']
                stock_strategy_names: Dict[str, List[str]] = {}
                for strat_id, name in sig_name_map.items():
                    detail = details_data.get(strat_id, {})
                    for sig in detail.get('recent_signals', []):
                        sid = sig.get('stock_id')
                        if sid:
                            lst = stock_strategy_names.setdefault(sid, [])
                            if name not in lst:
                                lst.append(name)
                reasons_map = {k: v[:3] for k, v in stock_strategy_names.items()}
        except Exception as e:
            logger.warning(f"[StrategyMiner] {dir_label}理由建立失敗: {e}")

        # 8. 刪除今日所有三維度同方向 picks (整批覆寫, 避免殘留舊融合列)
        db.execute(
            delete(StrategyMinerPick).where(
                StrategyMinerPick.pick_date == pick_date,
                StrategyMinerPick.direction == direction,
            )
        )

        # 9. per-dim 全輸過濾 + Top 寫入
        count = 0
        for dim, sorted_items in per_dim_sorted.items():
            opt_params = optimal.get(dim)
            if opt_params is None:
                continue

            # 9a. 全輸過濾: 歷史該股該方向平均報酬 <0 則跳過 (不論樣本數)。
            # 統計口徑跨維度 (_load_stock_perf_from_picks 按 direction 合併),
            # 維持與 UI 勝率顯示同源。
            candidate_ids = [item['primary'].stock_id for item in sorted_items]
            perf_map = _load_stock_perf_from_picks(db, candidate_ids, direction=direction)
            filtered: list = []
            for item in sorted_items:
                sid = item['primary'].stock_id
                perf = perf_map.get(sid)
                if perf is not None:
                    raw_count = perf.get('stock_trade_count') or 0
                    raw_avg = perf.get('stock_avg_return')
                    if raw_count > 0 and raw_avg is not None and raw_avg < 0:
                        logger.info(
                            f"[StrategyMiner] {dir_label}/{dim} skip {sid} "
                            f"(歷史 {raw_count} 筆平均 {raw_avg:.2f}% < 0)"
                        )
                        continue
                filtered.append(item)
                if len(filtered) >= max_picks:
                    break

            # 9b. 寫入該 dim 的 picks
            tp_mult = opt_params.take_profit_pct
            sl_mult = opt_params.stop_loss_pct
            hd = opt_params.hold_days_max

            for item in filtered:
                r = item['primary']
                entry_price = price_map.get(r.stock_id, 0.0)

                atr_row = (
                    db.query(StockFeature.atr20)
                    .filter(StockFeature.stock_id == r.stock_id, StockFeature.date == latest_date)
                    .first()
                )
                if atr_row and atr_row.atr20 and entry_price > 0:
                    tp = tp_mult * atr_row.atr20 / entry_price
                    sl = sl_mult * atr_row.atr20 / entry_price
                else:
                    tp = tp_mult * 0.03
                    sl = sl_mult * 0.03

                reasons = reasons_map.get(r.stock_id, [])

                db.add(StrategyMinerPick(
                    pick_date=pick_date,
                    stock_id=r.stock_id,
                    stock_name=r.stock_name,
                    strategy_ids=json.dumps([dim]),
                    weighted_score=round(item['score'], 4),
                    entry_price=entry_price,
                    take_profit_pct=tp,
                    stop_loss_pct=sl,
                    hold_days_max=hd,
                    time_dimension=dim,
                    direction=direction,
                    buy_reasons=json.dumps(reasons, ensure_ascii=False) if reasons else None,
                ))
                count += 1

        logger.info(f"[StrategyMiner] {dir_label}推薦 {count} 筆 (per-dim)")
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
    def _evaluate_pick_concluded(
        cls,
        pick,
        prices: Dict[date, float],
        round_trip_cost: float = 0.0,
    ) -> Optional[dict]:
        """判定一筆 pick 是否已結案。

        Args:
            pick: StrategyMinerPick instance
            prices: {trade_date: close_price} 僅該股後續交易日的收盤。
                    呼叫端負責查好此 dict ( 排除 pick_date 當日、僅含 > pick_date 的日期 )。
            round_trip_cost: 來回交易成本比率 ( 預設 0.0 ; 呼叫端可傳 ROUND_TRIP_COST=0.006 )。

        Returns:
            結案字典 {entry_date, entry_price, exit_date, exit_price, exit_reason,
                      return_pct, hold_days, strategy_id, stock_id, direction}
            或 None ( 尚未結案 )。
        """
        entry_price = float(pick.entry_price or 0.0)
        if entry_price <= 0:
            return None

        is_short = (pick.direction == 'short')
        tp = float(pick.take_profit_pct or 0.0)
        sl = float(pick.stop_loss_pct or 0.0)
        hd = int(pick.hold_days_max or 0)
        if hd <= 0:
            return None

        tp_price_long = entry_price * (1 + tp)
        sl_price_long = entry_price * (1 - sl)

        # 僅用 pick_date 之後的日期, 且按日期順序走訪
        sorted_dates = sorted(d for d in prices.keys() if d > pick.pick_date)
        if not sorted_dates:
            return None

        for i, d in enumerate(sorted_dates, start=1):
            close = prices[d]
            if close is None or close <= 0:
                continue

            if is_short:
                # 放空: 價格上漲 = 虧損、下跌 = 獲利
                if close <= entry_price * (1 - tp):
                    exit_reason = 'take_profit'
                elif close >= entry_price * (1 + sl):
                    exit_reason = 'stop_loss'
                else:
                    if i >= hd:
                        exit_reason = 'time_limit'
                    else:
                        continue
            else:
                if close >= tp_price_long:
                    exit_reason = 'take_profit'
                elif close <= sl_price_long:
                    exit_reason = 'stop_loss'
                else:
                    if i >= hd:
                        exit_reason = 'time_limit'
                    else:
                        continue

            raw_pct = (close - entry_price) / entry_price * 100.0
            ret_pct = -raw_pct if is_short else raw_pct
            ret_pct -= round_trip_cost * 100.0

            return {
                'entry_date': pick.pick_date,
                'entry_price': entry_price,
                'exit_date': d,
                'exit_price': float(close),
                'exit_reason': exit_reason,
                'return_pct': round(ret_pct, 4),
                'hold_days': i,
                'strategy_id': pick.time_dimension or '20d',
                'stock_id': pick.stock_id,
                'direction': pick.direction or 'long',
            }

        return None

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
    def _optimize_dimension(
        cls,
        db: Session,
        dimension: str,
        direction: str = 'long',
        as_of_date: Optional[date] = None,
    ) -> None:
        strategy_key = f"{dimension}_{direction}" if direction == 'short' else dimension
        logger.info(f"[StrategyMiner] 開始 {strategy_key} 維度參數尋優 (as_of={as_of_date})")

        # 決定切片上界: None 使用今日 (原排程行為); 有值則以該日期切片 (walk-forward backfill)
        cutoff_upper = as_of_date if as_of_date is not None else date.today()
        cutoff_lower = cutoff_upper - timedelta(days=365 * 2)

        # 載入歷史訊號 (按 direction 過濾 + 僅取 cutoff_upper 之前避免 look-ahead)
        signal_rows = (
            db.query(AlphaSignalHistory)
            .filter(
                AlphaSignalHistory.time_dimension == dimension,
                AlphaSignalHistory.direction == direction,
                AlphaSignalHistory.signal_date >= cutoff_lower,
                AlphaSignalHistory.signal_date <= cutoff_upper,
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
        price_dict, sorted_dates_dict, open_dict, atr_dict = cls._load_prices(db, stock_ids, cutoff_lower)

        # 訓練/測試切割（4/6 訓練、2/6 測試）
        n = len(signals_df)
        split_idx = n * 4 // 6
        train_df = signals_df.iloc[:split_idx].copy()
        test_df  = signals_df.iloc[split_idx:].copy()

        if len(train_df) < 10 or len(test_df) < 5:
            logger.info(f"[StrategyMiner] {dimension} 訓練/測試集樣本不足，跳過")
            return

        is_short = (direction == 'short')

        # 跑 9 組參數（訓練集）
        params_list = get_params_list(dimension)
        train_trades = cls._simulate_all_params(train_df, price_dict, sorted_dates_dict, params_list, is_short=is_short, open_dict=open_dict, atr_dict=atr_dict)

        # 找訓練集 Sharpe 前三
        train_sharpes: List[Tuple[int, float]] = []
        for param_idx, trades in enumerate(train_trades):
            s = _sharpe([t['return_pct'] for t in trades])
            train_sharpes.append((param_idx, s))
        train_sharpes.sort(key=lambda x: x[1], reverse=True)
        sharpe_by_param = {idx: s for idx, s in train_sharpes}
        top3_indices = [x[0] for x in train_sharpes[:3]]

        # 跑前三（測試集）
        top3_params = [params_list[i] for i in top3_indices]
        test_trades_raw = cls._simulate_entries(test_df, price_dict, sorted_dates_dict, top3_params, is_short=is_short, open_dict=open_dict, atr_dict=atr_dict)

        # 選測試集最穩定者
        best_idx_in_top3 = 0
        best_test_sharpe = -float('inf')
        for i, trades in enumerate(test_trades_raw):
            s = _sharpe([t['return_pct'] for t in trades])
            if s > best_test_sharpe:
                best_test_sharpe = s
                best_idx_in_top3 = i
        optimal_param_idx = top3_indices[best_idx_in_top3]
        optimal_params = params_list[optimal_param_idx]

        # 儲存 18 組回測結果到 strategy_backtest_params
        today = cutoff_upper
        db.execute(
            delete(StrategyBacktestParam).where(StrategyBacktestParam.strategy_id == strategy_key)
        )
        for param_idx, params in enumerate(params_list):
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
                take_profit_pct=params['tp_atr_mult'],    # ATR 倍數
                stop_loss_pct=params['sl_atr_mult'],      # ATR 倍數
                hold_days_max=params['hold_days'],
                sharpe_train=round(tr_sharpe_val, 4),
                sharpe_test=round(te_sharpe, 4),
                win_rate_test=round(te_win, 4),
                avg_return_test=round(te_avg, 4),
                trade_count_test=te_count,
                is_optimal=(param_idx == optimal_param_idx),
                computed_at=today,
                is_atr_based=True,
            ))

        db.commit()
        logger.info(
            f"[StrategyMiner] {strategy_key} 最優參數: "
            f"TP={optimal_params['tp_atr_mult']}×ATR "
            f"SL={optimal_params['sl_atr_mult']}×ATR "
            f"HD={optimal_params['hold_days']}天"
        )

        # 以最優參數跑全部訊號，儲存逐筆交易記錄
        all_trades_by_param = cls._simulate_entries(
            signals_df, price_dict, sorted_dates_dict, [optimal_params], is_short=is_short, open_dict=open_dict, atr_dict=atr_dict,
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
        params_list: list,
        is_short: bool = False,
        open_dict: Optional[Dict] = None,
        atr_dict: Optional[Dict] = None,
    ) -> List[List[dict]]:
        """對所有參數組合進行回測，回傳 list of trade lists"""
        return cls._simulate_entries(signals_df, price_dict, sorted_dates_dict, params_list, is_short=is_short, open_dict=open_dict, atr_dict=atr_dict)

    @classmethod
    def _simulate_entries(
        cls,
        signals_df: pd.DataFrame,
        price_dict: Dict[str, Dict],
        sorted_dates_dict: Dict[str, List],
        params_list: List[dict],
        is_short: bool = False,
        open_dict: Optional[Dict[str, Dict]] = None,
        atr_dict: Optional[Dict[str, Dict]] = None,
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
                continue  # open 不可用時跳過，避免用收盤價造成回測偏差
            if not entry_price or entry_price <= 0:
                continue

            # ATR-based TP/SL：查詢訊號日 ATR
            stock_atr = atr_dict.get(stock_id, {}).get(signal_date) if atr_dict else None
            if stock_atr is None or stock_atr <= 0:
                continue  # ATR 不可用時跳過

            # 取隔日(含)之後 max_hold+5 個交易日的收盤
            fwd_dates = dates[sig_idx + 1 : sig_idx + 1 + max_hold + 5]
            if not fwd_dates:
                continue

            fwd_returns = np.array(
                [(px[d] - entry_price) / entry_price for d in fwd_dates],
                dtype=float,
            )

            for param_idx, params in enumerate(params_list):
                tp_pct = params['tp_atr_mult'] * stock_atr / entry_price
                sl_pct = params['sl_atr_mult'] * stock_atr / entry_price
                max_days = params['hold_days']

                n_fwd = min(max_days, len(fwd_returns))
                if n_fwd == 0:
                    continue
                r = fwd_returns[:n_fwd]

                if is_short:
                    # 放空：股價下跌 = 獲利，上漲 = 虧損
                    tp_hits = np.where(r <= -tp_pct)[0]   # 跌到 TP = 停利
                    sl_hits = np.where(r >= sl_pct)[0]    # 漲到 SL = 停損
                else:
                    tp_hits = np.where(r >= tp_pct)[0]
                    sl_hits = np.where(r <= -sl_pct)[0]

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
                exit_return = (-raw_return if is_short else raw_return) - ROUND_TRIP_COST
                results[param_idx].append({
                    'stock_id': stock_id,
                    'entry_date': signal_date,
                    'entry_price': entry_price,
                    'exit_date': fwd_dates[exit_idx],
                    'exit_price': round(entry_price * (1 + raw_return), 2),
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
    ) -> Tuple[Dict[str, Dict], Dict[str, List], Dict[str, Dict], Dict[str, Dict]]:
        """批次載入股票歷史 open + close 價格 + ATR"""
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

        # 載入 ATR（新增）
        atr_rows = (
            db.query(StockFeature.stock_id, StockFeature.date, StockFeature.atr20)
            .filter(
                StockFeature.stock_id.in_(stock_ids),
                StockFeature.date >= cutoff,
                StockFeature.atr20.isnot(None),
            )
            .all()
        )
        atr_dict: Dict[str, Dict] = {}
        for r in atr_rows:
            sid = str(r.stock_id)
            atr_dict.setdefault(sid, {})[r.date] = float(r.atr20)

        return price_dict, sorted_dates_dict, open_dict, atr_dict

    @staticmethod
    def _default_params(dimension: str) -> Tuple[float, float, int]:
        """當尚無回測結果時的 fallback ATR 倍數"""
        hd = DIM_HOLD_DAYS.get(dimension, 20)
        return 1.5, 1.0, hd      # TP=1.5×ATR, SL=1.0×ATR

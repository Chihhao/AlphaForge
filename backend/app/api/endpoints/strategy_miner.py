"""
Strategy Miner API — 每日推薦清單 + 歷史交易記錄
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List
from datetime import date, timedelta
from collections import defaultdict

from app.db.database import get_db
from app.services.strategy_miner_service import StrategyMinerService
from app.models.strategy_backtest_param import StrategyBacktestParam
from app.models.strategy_miner_trade import StrategyMinerTrade
from app.models.strategy_miner_pick import StrategyMinerPick
from app.models.stock_price import StockPrice
from app.models.alpha_signal_history import AlphaSignalHistory
from app.models.alpha_miner_snapshot import AlphaMinerSnapshot
from sqlalchemy import func, and_
import json

router = APIRouter(prefix="/strategy-miner", tags=["strategy-miner"])


def _load_stock_perf_map(db: Session, stock_ids: list[str], direction: str = 'long') -> dict:
    """載入指定股票的回測交易績效（strategy_miner_trades），
    按維度(5d/10d/30d)分別計算勝率，回傳最高勝率維度的績效。
    direction 決定只取做多或放空的 trades。
    回傳 {stock_id: {win_rate, avg_return, trade_count, best_dim}}"""
    if not stock_ids:
        return {}
    rows = (
        db.query(StrategyMinerTrade)
        .filter(StrategyMinerTrade.stock_id.in_(stock_ids))
        .all()
    )
    # 依方向過濾：放空的 strategy_id 含 '_short'
    if direction == 'short':
        rows = [r for r in rows if '_short' in r.strategy_id]
    else:
        rows = [r for r in rows if '_short' not in r.strategy_id]
    # {stock_id: {dim: [return_pct, ...]}}
    by_stock_dim: dict = defaultdict(lambda: defaultdict(list))
    for r in rows:
        dim = r.strategy_id.replace('_short', '')
        by_stock_dim[r.stock_id][dim].append(r.return_pct)
    result = {}
    for sid, dims in by_stock_dim.items():
        best_dim = None
        best_wr = -1
        for dim, rets in dims.items():
            wr = sum(1 for x in rets if x > 0) / len(rets) if rets else 0
            if wr > best_wr or (wr == best_wr and len(rets) > len(dims.get(best_dim, []))):
                best_wr = wr
                best_dim = dim
        rets = dims[best_dim]
        wins = sum(1 for x in rets if x > 0)
        result[sid] = {
            "stock_win_rate": round(wins / len(rets), 4),
            "stock_avg_return": round(sum(rets) / len(rets), 1),
            "stock_trade_count": len(rets),
            "stock_best_dim": best_dim,
        }
    return result


def _load_market_baselines(db: Session) -> dict:
    """從 Alpha Miner snapshot 取各維度市場基準勝率。
    回傳 {'5d': 0.194, '10d': 0.244, '30d': 0.261}"""
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


def _load_buy_reasons_fallback(db: Session, picks) -> dict:
    """當 DB 中 buy_reasons 為 null 時，基於 alpha_signal_history + 維度最佳策略生成近似理由。

    策略：取 alpha_signal_history 的最新 trigger_count，
    加上 Alpha Miner snapshot 中該維度 top-3 顯著策略名稱作為近似因子。
    """
    import json
    from app.models.alpha_miner_snapshot import AlphaMinerSnapshot
    from app.models.alpha_signal_history import AlphaSignalHistory
    from sqlalchemy import func as sa_func

    # 1. 取各股最新 alpha_signal_history 資訊
    stock_ids = [p.stock_id for p in picks if p.buy_reasons is None]
    if not stock_ids:
        return {}

    sub = (
        db.query(
            AlphaSignalHistory.stock_id,
            sa_func.max(AlphaSignalHistory.signal_date).label("max_date"),
        )
        .filter(AlphaSignalHistory.stock_id.in_(stock_ids))
        .group_by(AlphaSignalHistory.stock_id)
        .subquery()
    )
    hist_rows = (
        db.query(AlphaSignalHistory)
        .join(
            sub,
            (AlphaSignalHistory.stock_id == sub.c.stock_id)
            & (AlphaSignalHistory.signal_date == sub.c.max_date),
        )
        .all()
    )
    hist_map = {r.stock_id: r for r in hist_rows}

    # 2. 取 alpha_miner_snapshot 中各維度 top-3 顯著策略名稱
    dim_top_strats: dict = {}
    try:
        snap = (
            db.query(AlphaMinerSnapshot)
            .order_by(AlphaMinerSnapshot.train_date.desc())
            .first()
        )
        if snap:
            result_data = json.loads(snap.result_json)
            for dim in ["5d", "10d", "30d"]:
                dim_strats = sorted(
                    [
                        s for s in result_data.get("strategies", [])
                        if s.get("is_significant") and s.get("time_dimension") == dim and s.get("ic", 0) > 0
                    ],
                    key=lambda x: x.get("ic", 0),
                    reverse=True,
                )
                dim_top_strats[dim] = [s["strategy_name"] for s in dim_strats[:3]]
    except Exception:
        pass

    # 3. 組合每股的 buy_reasons
    result = {}
    for p in picks:
        if p.buy_reasons is not None:
            continue
        hist = hist_map.get(p.stock_id)
        reasons = []
        if hist:
            reasons.append(f"近期 {hist.trigger_count} 個策略共同觸發")
        reasons.extend(dim_top_strats.get(p.time_dimension, []))
        result[p.stock_id] = reasons[:3]

    return result


def _get_current_prices(db: Session, stock_ids: list[str]) -> dict:
    """批次取得各股最新收盤價，回傳 {stock_id: close}"""
    if not stock_ids:
        return {}
    sub = (
        db.query(
            StockPrice.stock_id,
            func.max(StockPrice.date).label("max_date"),
        )
        .filter(StockPrice.stock_id.in_(stock_ids), StockPrice.close > 0)
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


@router.get("/picks/today")
def get_today_picks(db: Session = Depends(get_db)):
    """今日推薦清單（含停利停損參數 + 個股回測績效 + 買入理由）"""
    import json as _json
    all_picks = StrategyMinerService.get_today_picks(db)
    picks = [p for p in all_picks if (getattr(p, 'direction', 'long') or 'long') == 'long']
    stock_ids = [p.stock_id for p in picks]
    stock_perf = _load_stock_perf_map(db, stock_ids, direction='long')
    baselines = _load_market_baselines(db)

    # 優先使用 DB 儲存的 buy_reasons；若為 null（舊資料），使用 fallback 近似值
    any_missing = any(p.buy_reasons is None for p in picks)
    live_reasons: dict = _load_buy_reasons_fallback(db, picks) if any_missing else {}

    result = []
    for p in picks:
        perf = stock_perf.get(p.stock_id, {
            "stock_win_rate": None,
            "stock_avg_return": None,
            "stock_trade_count": 0,
            "stock_best_dim": None,
        })
        # 品質過濾：相對門檻 + 最低樣本數
        trade_count = perf.get("stock_trade_count", 0)
        if trade_count < 10:
            perf["stock_win_rate"] = None
            perf["stock_avg_return"] = None
        else:
            dim = (p.time_dimension or '10d').replace('_short', '')
            baseline = baselines.get(dim, 0.25)
            wr = perf.get("stock_win_rate")
            avg = perf.get("stock_avg_return")
            if wr is not None and wr <= baseline + 0.05:
                continue
            if avg is not None and avg < 0:
                continue

        result.append({
            "pick_date": p.pick_date.isoformat(),
            "stock_id": p.stock_id,
            "stock_name": p.stock_name,
            "strategy_ids": p.strategy_ids,
            "weighted_score": p.weighted_score,
            "entry_price": p.entry_price,
            "take_profit_pct": p.take_profit_pct,
            "stop_loss_pct": p.stop_loss_pct,
            "hold_days_max": p.hold_days_max,
            "time_dimension": p.time_dimension,
            "direction": getattr(p, 'direction', 'long') or 'long',
            "buy_reasons": (
                _json.loads(p.buy_reasons) if p.buy_reasons
                else live_reasons.get(p.stock_id, [])
            ),
            **perf,
        })
    return result


@router.get("/picks/active")
def get_active_picks(db: Session = Depends(get_db)):
    """過去持有中的推薦清單，計算目前浮動損益與出場提醒。

    遍歷最近 30 天的 picks，根據最新收盤價判斷：
    - 停利觸發：current >= entry * (1 + tp_pct)
    - 停損觸發：current <= entry * (1 - sl_pct)
    - 到期：持有天數 >= hold_days_max
    - 持有中：其餘
    """
    today = date.today()
    cutoff = today - timedelta(days=30)

    # 不含今日（今日是「買入」，past 才是「持倉」）
    rows = (
        db.query(StrategyMinerPick)
        .filter(
            StrategyMinerPick.pick_date >= cutoff,
            StrategyMinerPick.pick_date < today,
        )
        .order_by(StrategyMinerPick.pick_date.desc())
        .all()
    )

    if not rows:
        return []

    # 同股票只保留最早一筆推薦（代表「首次推薦時的進場價」，可顯示完整持倉期間的浮動損益）
    # rows 已按 pick_date desc 排序（新到舊），持續覆寫後保留的是最舊（最早）一筆
    seen: dict = {}
    for p in rows:
        seen[p.stock_id] = p  # 覆寫到最後 = 最舊一筆
    rows = list(seen.values())

    stock_ids = [p.stock_id for p in rows]
    price_map = _get_current_prices(db, stock_ids)

    result = []
    for p in rows:
        entry = p.entry_price or 0
        current = price_map.get(p.stock_id, 0)
        days_held = (today - p.pick_date).days
        direction = getattr(p, 'direction', 'long') or 'long'
        is_short = (direction == 'short')

        if entry <= 0 or current <= 0:
            status = "資料不足"
            float_pct = None
        else:
            # 放空：股價下跌 = 獲利
            raw_pct = (current - entry) / entry * 100
            float_pct = round(-raw_pct if is_short else raw_pct, 2)

            if is_short:
                # 放空 TP/SL 反轉
                if current <= entry * (1 - p.take_profit_pct):
                    status = "建議停利"
                elif current >= entry * (1 + p.stop_loss_pct):
                    status = "建議停損"
                elif days_held >= p.hold_days_max:
                    if days_held > p.hold_days_max + 7:
                        status = "已結算"
                    else:
                        status = "到期出場"
                elif days_held >= p.hold_days_max - 1:
                    status = "明日到期"
                else:
                    status = "持有中"
            else:
                if current >= entry * (1 + p.take_profit_pct):
                    status = "建議停利"
                elif current <= entry * (1 - p.stop_loss_pct):
                    status = "建議停損"
                elif days_held >= p.hold_days_max:
                    if days_held > p.hold_days_max + 7:
                        status = "已結算"
                    else:
                        status = "到期出場"
                elif days_held >= p.hold_days_max - 1:
                    status = "明日到期"
                else:
                    status = "持有中"

        result.append({
            "pick_date": p.pick_date.isoformat(),
            "stock_id": p.stock_id,
            "stock_name": p.stock_name,
            "entry_price": entry,
            "current_price": current,
            "take_profit_pct": p.take_profit_pct,
            "stop_loss_pct": p.stop_loss_pct,
            "hold_days_max": p.hold_days_max,
            "days_held": days_held,
            "float_pct": float_pct,
            "status": status,
            "time_dimension": p.time_dimension,
            "direction": direction,
        })

    # 出場提醒排前面；同狀態內，停利按 float_pct 由高到低，停損按 float_pct 由低到高
    EXIT_ORDER = {"建議停利": 0, "建議停損": 1, "到期出場": 2, "明日到期": 3, "持有中": 4, "資料不足": 5}
    result.sort(key=lambda x: (
        EXIT_ORDER.get(x["status"], 9),
        -(x.get("float_pct") or 0),  # 停利：獲利大的排前；停損：虧損多的也排前（負值大=虧多）
    ))
    return result


@router.get("/picks/live-performance")
def get_live_performance(db: Session = Depends(get_db)):
    """即時追蹤績效：基於歷史 picks 的真實前向表現（非回測）

    統計所有「已有結果」的 picks（到期出場 + 已結算 + 停利 + 停損）的勝率與均報酬。
    「建議停利/停損」使用當前收盤價的浮動損益作為近似出場報酬。
    持有中的 picks 不計入（結果未定）。
    """
    today = date.today()
    # 取最近 60 天的 picks（涵蓋完整的歷史回補資料）
    cutoff = today - timedelta(days=60)

    rows = (
        db.query(StrategyMinerPick)
        .filter(
            StrategyMinerPick.pick_date >= cutoff,
            StrategyMinerPick.pick_date < today,
        )
        .order_by(StrategyMinerPick.pick_date.desc())
        .all()
    )
    if not rows:
        return {"trade_count": 0, "win_rate": None, "avg_return": None, "total_return": None}

    # 同股票只保留最早一筆
    seen: dict = {}
    for p in rows:
        seen[p.stock_id] = p
    rows = list(seen.values())

    stock_ids = [p.stock_id for p in rows]
    price_map = _get_current_prices(db, stock_ids)

    finished = []  # (return_pct, is_win)
    for p in rows:
        entry = p.entry_price or 0
        current = price_map.get(p.stock_id, 0)
        if entry <= 0 or current <= 0:
            continue
        days_held = (today - p.pick_date).days
        direction = getattr(p, 'direction', 'long') or 'long'
        is_short = (direction == 'short')
        raw_pct = (current - entry) / entry * 100
        float_pct = -raw_pct if is_short else raw_pct

        # 判斷是否已「有定論」
        if is_short:
            tp_hit = current <= entry * (1 - p.take_profit_pct)
            sl_hit = current >= entry * (1 + p.stop_loss_pct)
        else:
            tp_hit = current >= entry * (1 + p.take_profit_pct)
            sl_hit = current <= entry * (1 - p.stop_loss_pct)

        if tp_hit:
            finished.append(float_pct)
        elif sl_hit:
            finished.append(float_pct)
        elif days_held > p.hold_days_max + 7:
            # 已結算（到期超寬限）
            finished.append(float_pct)
        elif days_held >= p.hold_days_max:
            # 到期出場（寬限期內）
            finished.append(float_pct)
        # else: 持有中，不計入

    if not finished:
        return {"trade_count": 0, "win_rate": None, "avg_return": None, "total_return": None}

    wins = sum(1 for r in finished if r > 0)
    win_rate = round(wins / len(finished), 4)
    avg_return = round(sum(finished) / len(finished), 2)
    total_return = round(sum(finished), 2)

    return {
        "trade_count": len(finished),
        "win_rate": win_rate,
        "avg_return": avg_return,
        "total_return": total_return,
        "still_holding": len(rows) - len(finished),
    }


@router.get("/picks/concluded")
def get_concluded_picks(
    limit: int = 20,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    """已出場 picks 的逐筆成績單（停利 / 停損 / 到期 / 已結算）。

    與 live-performance 使用相同的去重與判斷邏輯，
    但回傳每筆明細而非彙總數字，並支援 limit/offset 分頁。
    """
    today = date.today()
    cutoff = today - timedelta(days=60)

    rows = (
        db.query(StrategyMinerPick)
        .filter(
            StrategyMinerPick.pick_date >= cutoff,
            StrategyMinerPick.pick_date < today,
        )
        .order_by(StrategyMinerPick.pick_date.desc())
        .all()
    )
    if not rows:
        return {"items": [], "total": 0}

    # 同股票只保留最早一筆（與 live-performance 邏輯一致）
    seen: dict = {}
    for p in rows:
        seen[p.stock_id] = p
    deduped = list(seen.values())

    stock_ids = [p.stock_id for p in deduped]
    price_map = _get_current_prices(db, stock_ids)

    concluded = []
    for p in deduped:
        entry = p.entry_price or 0
        current = price_map.get(p.stock_id, 0)
        if entry <= 0 or current <= 0:
            continue
        days_held = (today - p.pick_date).days
        direction = getattr(p, 'direction', 'long') or 'long'
        is_short = (direction == 'short')
        raw_pct = (current - entry) / entry * 100
        float_pct = round(-raw_pct if is_short else raw_pct, 2)

        if is_short:
            tp_hit = current <= entry * (1 - p.take_profit_pct)
            sl_hit = current >= entry * (1 + p.stop_loss_pct)
        else:
            tp_hit = current >= entry * (1 + p.take_profit_pct)
            sl_hit = current <= entry * (1 - p.stop_loss_pct)

        if tp_hit:
            exit_reason = "take_profit"
        elif sl_hit:
            exit_reason = "stop_loss"
        elif days_held > p.hold_days_max + 7:
            exit_reason = "settled"
        elif days_held >= p.hold_days_max:
            exit_reason = "time_limit"
        else:
            continue  # 持有中，跳過

        buy_reasons: list = []
        if p.buy_reasons:
            try:
                buy_reasons = json.loads(p.buy_reasons)
            except Exception:
                pass

        concluded.append({
            "pick_date": p.pick_date.isoformat(),
            "stock_id": p.stock_id,
            "stock_name": p.stock_name,
            "entry_price": entry,
            "exit_reason": exit_reason,
            "return_pct": float_pct,
            "days_held": days_held,
            "time_dimension": p.time_dimension or "10d",
            "direction": getattr(p, 'direction', 'long') or 'long',
            "buy_reasons": buy_reasons,
            "take_profit_pct": p.take_profit_pct,
            "stop_loss_pct": p.stop_loss_pct,
            "hold_days_max": p.hold_days_max,
        })

    concluded.sort(key=lambda x: x["pick_date"], reverse=True)
    total = len(concluded)
    return {"items": concluded[offset: offset + limit], "total": total}


@router.get("/picks/history")
def get_picks_history(days: int = 7, db: Session = Depends(get_db)):
    """過去 N 天的推薦記錄（含個股回測績效）"""
    all_picks = StrategyMinerService.get_picks_history(db, days=days)
    picks = [p for p in all_picks if (getattr(p, 'direction', 'long') or 'long') == 'long']
    stock_ids = [p.stock_id for p in picks]
    stock_perf = _load_stock_perf_map(db, stock_ids, direction='long')
    baselines = _load_market_baselines(db)

    result = []
    for p in picks:
        perf = stock_perf.get(p.stock_id, {
            "stock_win_rate": None,
            "stock_avg_return": None,
            "stock_trade_count": 0,
            "stock_best_dim": None,
        })
        trade_count = perf.get("stock_trade_count", 0)
        if trade_count < 10:
            perf["stock_win_rate"] = None
            perf["stock_avg_return"] = None
        else:
            dim = (p.time_dimension or '10d').replace('_short', '')
            baseline = baselines.get(dim, 0.25)
            wr = perf.get("stock_win_rate")
            avg = perf.get("stock_avg_return")
            if wr is not None and wr <= baseline + 0.05:
                continue
            if avg is not None and avg < 0:
                continue

        result.append({
            "pick_date": p.pick_date.isoformat(),
            "stock_id": p.stock_id,
            "stock_name": p.stock_name,
            "weighted_score": p.weighted_score,
            "entry_price": p.entry_price,
            "hold_days_max": p.hold_days_max,
            "time_dimension": p.time_dimension,
            "direction": getattr(p, 'direction', 'long') or 'long',
            **perf,
        })
    return result


@router.get("/trades/{stock_id}")
def get_trades(stock_id: str, db: Session = Depends(get_db)):
    """某股票的歷史逐筆交易記錄"""
    trades = StrategyMinerService.get_trades(db, stock_id)
    return [
        {
            "strategy_id": t.strategy_id,
            "stock_id": t.stock_id,
            "entry_date": t.entry_date.isoformat(),
            "entry_price": t.entry_price,
            "exit_date": t.exit_date.isoformat() if t.exit_date else None,
            "exit_price": t.exit_price,
            "exit_reason": t.exit_reason,
            "return_pct": t.return_pct,
            "hold_days": t.hold_days,
        }
        for t in trades
    ]


@router.get("/performance")
def get_performance(db: Session = Depends(get_db)):
    """整體績效統計（各維度最優參數回測結果）"""
    return StrategyMinerService.get_performance(db)


@router.post("/run-optimization")
def run_optimization(db: Session = Depends(get_db)):
    """手動觸發參數尋優（通常由排程執行）"""
    StrategyMinerService.run_all(db)
    return {"status": "ok", "message": "Strategy Miner 參數尋優已完成"}


@router.post("/run-daily")
def run_daily(db: Session = Depends(get_db)):
    """手動觸發今日推薦生成（通常由排程執行）"""
    count = StrategyMinerService.run_daily(db)
    return {"status": "ok", "picks_generated": count}

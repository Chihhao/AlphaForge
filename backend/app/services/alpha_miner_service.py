"""
AlphaMinerService — 邏輯迴歸多因子模型 (Phase 5A)

設計原則：
- 分位數排名消除跨股票量綱差異
- 時間衰減權重（近期資料比舊資料重要）
- 訓練/測試嚴格時間切割，留一個月空白期避免標籤洩漏
- Bonferroni 多重校正防止 p-hacking（每個持有期各自校正）
- 多時間維度：5日、10日、30日各自訓練，每維度報告兩個門檻
- 樣本外 Spearman IC 為排序依據
- 訓練結果持久化至 DB，後端重啟免重算
"""
from __future__ import annotations

import json
import logging
import multiprocessing
import os
import threading
import numpy as np
import pandas as pd
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session
from sqlalchemy import delete

logger = logging.getLogger(__name__)

from app.core.config import settings
from app.db.database import engine
from app.models.stock_feature import StockFeature
from app.models.alpha_miner_snapshot import AlphaMinerSnapshot
from app.models.alpha_signal_history import AlphaSignalHistory
from app.schemas.alpha_miner import (
    AlphaMinerResult, StrategyRanking, StrategyDetail,
    FactorWeight, RecentAlphaSignal, EquityCurvePoint, TodaySignal,
    SignalHistoryItem,
)

# ─── 因子中文標籤 ──────────────────────────────────────────────────────────────
FACTOR_LABELS: Dict[str, str] = {
    'rsi14':           'RSI',
    'rsi2':            'RSI(2)',
    'k':               'KD-K',
    'd':               'KD-D',
    'macd_dif':        'MACD DIF',
    'macd_osc':        'MACD 柱',
    'bias5':           '乖離率5',
    'bias10':          '乖離率10',
    'bias20':          '乖離率20',
    'bb_pctb':         '布林%B',
    'vol_ratio':       '量比',
    'yield_rate':      '殖利率',
    'roe':             'ROE',
    'pb_ratio':        '股淨比',
    'revenue_yoy':     '營收YoY',
    # Phase 4B 籌碼面因子
    'foreign_net_buy': '外資買超',
    'foreign_buy_5d':  '外資5日累積',
    'trust_net_buy':   '投信買超',
    'trust_buy_5d':    '投信5日累積',
    'margin_chg_5d':   '融資5日變化',
    # Phase 5B 新增
    'dealer_net_buy':  '自營商買超',
    'dealer_buy_5d':   '自營商5日累積',
    'price_vs_high20': '距高點乖離',
    'ma_trend':        '均線多頭排列',
    # Phase 6 新增
    'sector_rs':            '產業相對強度',
    'foreign_hold_pct':     '外資持股比率',
    'foreign_hold_chg_5d':  '外資持股5日變化',
    # Phase 3B ETF 申贖資金流向
    'etf_net_flow_5d':    'ETF資金流入',
    # Phase 7 籌碼面中長期
    'foreign_buy_10d':  '外資10日累積',
    'foreign_buy_20d':  '外資20日累積',
    'trust_buy_10d':    '投信10日累積',
    'trust_buy_20d':    '投信20日累積',
    'dealer_buy_10d':   '自營商10日累積',
    'dealer_buy_20d':   '自營商20日累積',
}

# ─── 預定義因子組合（63 組，Bonferroni 校正門檻 = 0.05/63 ≈ 0.00079）─────────
FACTOR_COMBINATIONS: List[List[str]] = [
    # 單因子技術面
    ['rsi14'], ['k'], ['bias20'], ['bb_pctb'], ['vol_ratio'],
    ['macd_dif'], ['macd_osc'], ['bias5'], ['bias10'], ['d'],
    # 單因子基本面
    ['pb_ratio'], ['roe'], ['yield_rate'], ['revenue_yoy'],
    # 單因子籌碼面（Phase 4B）
    ['foreign_net_buy'], ['foreign_buy_5d'],
    ['trust_net_buy'], ['trust_buy_5d'],
    ['margin_chg_5d'],
    # 技術面 + 量比
    ['rsi14', 'vol_ratio'], ['k', 'vol_ratio'],
    ['bias20', 'vol_ratio'], ['bb_pctb', 'vol_ratio'],
    ['macd_dif', 'vol_ratio'],
    # 技術面複合
    ['rsi14', 'macd_dif'], ['k', 'd'], ['bias20', 'rsi14'],
    # 技術 + 基本面
    ['rsi14', 'pb_ratio'], ['rsi14', 'roe'],
    ['bias20', 'pb_ratio'], ['k', 'revenue_yoy'],
    ['rsi14', 'yield_rate'],
    # 基本面複合
    ['pb_ratio', 'roe'], ['yield_rate', 'roe'],
    ['revenue_yoy', 'pb_ratio'],
    # 技術 + 籌碼（Phase 4B）
    ['rsi14', 'foreign_net_buy'], ['rsi14', 'foreign_buy_5d'],
    ['k', 'foreign_net_buy'], ['bias20', 'foreign_buy_5d'],
    ['rsi14', 'trust_net_buy'], ['k', 'trust_buy_5d'],
    ['vol_ratio', 'foreign_net_buy'], ['vol_ratio', 'foreign_buy_5d'],
    # 籌碼複合
    ['foreign_buy_5d', 'trust_buy_5d'],
    ['foreign_net_buy', 'trust_net_buy'],
    ['foreign_buy_5d', 'margin_chg_5d'],
    # 三因子（含籌碼）
    ['rsi14', 'vol_ratio', 'pb_ratio'],
    ['k', 'vol_ratio', 'roe'],
    ['bias20', 'vol_ratio', 'revenue_yoy'],
    ['rsi14', 'foreign_buy_5d', 'pb_ratio'],
    ['k', 'trust_buy_5d', 'roe'],
    ['bias20', 'foreign_buy_5d', 'vol_ratio'],
    # 單因子（Phase 5B）
    ['dealer_net_buy'], ['dealer_buy_5d'], ['price_vs_high20'],
    # 自營商複合
    ['dealer_buy_5d', 'trust_buy_5d'],
    ['dealer_buy_5d', 'foreign_buy_5d'],
    ['foreign_buy_5d', 'trust_buy_5d', 'dealer_buy_5d'],
    # 技術面新因子複合
    ['price_vs_high20', 'vol_ratio'],
    ['price_vs_high20', 'trust_buy_5d'],
    ['ma_trend', 'vol_ratio'],
    ['ma_trend', 'trust_buy_5d'],
    ['ma_trend', 'foreign_buy_5d'],
    # 單因子（Phase 6）
    ['sector_rs'],
    ['foreign_hold_pct'],
    ['foreign_hold_chg_5d'],
    # 產業相對強度複合
    ['sector_rs', 'rsi14'],
    ['sector_rs', 'vol_ratio'],
    ['sector_rs', 'foreign_buy_5d'],
    # 外資持股複合
    ['foreign_hold_chg_5d', 'foreign_buy_5d'],   # 存量+流量
    ['foreign_hold_pct', 'pb_ratio'],
    ['foreign_hold_chg_5d', 'rsi14'],
    ['foreign_hold_chg_5d', 'trust_buy_5d'],
    # 三因子（Phase 6）
    ['sector_rs', 'rsi14', 'vol_ratio'],
    # ETF 申贖資金流向（Phase 3B）
    ['etf_net_flow_5d'],
    ['etf_net_flow_5d', 'foreign_buy_5d'],
    ['etf_net_flow_5d', 'rsi14'],
    # Phase 7 — 中長期籌碼單因子
    ['foreign_buy_10d'], ['foreign_buy_20d'],
    ['trust_buy_10d'], ['trust_buy_20d'],
    # Phase 7 — 跨期籌碼動量（短 vs 中期差異 = 加速度信號）
    ['foreign_buy_5d', 'foreign_buy_20d'],
    ['trust_buy_5d', 'trust_buy_20d'],
    # Phase 7 — 中期籌碼 + 技術面
    ['foreign_buy_20d', 'rsi14'],
    ['trust_buy_20d', 'sector_rs'],
    # Phase 8 — RSI(2) 極短期反轉
    ['rsi2'],
    ['rsi2', 'vol_ratio'],
    ['rsi2', 'pb_ratio'],
    ['rsi2', 'foreign_buy_5d'],
    ['rsi2', 'bias10'],
    ['rsi2', 'bias10', 'vol_ratio'],
]

_LOAD_COLS = ['stock_id', 'date', 'close', 'ma60'] + list(FACTOR_LABELS.keys())

# Bonferroni 校正：組合數自動計算
_BONFERRONI_N = len(FACTOR_COMBINATIONS)

# ─── 進度檔案（跨 process 通訊）─────────────────────────────────────────────
_PROGRESS_FILE = '/tmp/alpha_miner_progress.json'

def _write_progress(data: dict) -> None:
    try:
        with open(_PROGRESS_FILE, 'w') as f:
            json.dump(data, f)
    except Exception:
        pass

def _read_progress() -> dict:
    try:
        with open(_PROGRESS_FILE) as f:
            return json.load(f)
    except Exception:
        return {"current": 0, "total": 0, "percent": 0, "current_dim": "", "current_strategy": ""}

def _run_training_subprocess() -> None:
    """訓練子程序進入點（multiprocessing.Process 需要 module-level function）"""
    import logging as _log
    from app.db.database import SessionLocal
    _log.basicConfig(level=logging.INFO)
    db = SessionLocal()
    try:
        AlphaMinerService._train_all(db)
    except Exception as e:
        _log.getLogger(__name__).error(f"[AlphaMiner] 訓練子程序失敗: {e}", exc_info=True)
        _write_progress({"current": 0, "total": 0, "percent": 0,
                         "current_dim": "", "current_strategy": "", "error": str(e)})
    finally:
        db.close()


_TRAINING_STUB = AlphaMinerResult(
    strategies=[], last_trained='', train_period='計算中…', test_period='計算中…',
    total_combinations_tested=0, bonferroni_threshold=1.0, is_training=True,
)


class AlphaMinerService:
    """多因子邏輯迴歸訓練與排行榜快取"""

    _cache: Optional[AlphaMinerResult] = None
    _cache_date: Optional[date] = None
    _details: Dict[str, StrategyDetail] = {}
    _process: Optional[multiprocessing.Process] = None  # 訓練子程序
    _lock: threading.Lock = threading.Lock()
    _stock_names: Dict[str, str] = {}  # 股票代號 → 名稱快取

    @classmethod
    def _lookup_name(cls, stock_id: str) -> str:
        """查詢股票名稱：優先用 twstock，找不到再查本地 DB"""
        if stock_id in cls._stock_names:
            return cls._stock_names[stock_id]
        try:
            import twstock
            info = twstock.codes.get(stock_id)
            if info:
                cls._stock_names[stock_id] = info.name
                return info.name
        except Exception:
            pass
        # fallback：查本地 stocks 表
        try:
            from app.models.user import Stock as StockModel
            db = engine.connect()
            import sqlalchemy as sa
            row = db.execute(sa.text("SELECT stock_name FROM stocks WHERE stock_id = :sid"), {"sid": stock_id}).fetchone()
            db.close()
            if row and row[0]:
                cls._stock_names[stock_id] = row[0]
                return row[0]
        except Exception:
            pass
        # 查詢失敗也寫入快取（避免下次重複查 DB）
        cls._stock_names[stock_id] = stock_id
        return stock_id

    TEST_MONTHS = 6   # 測試集保留最後幾個月
    GAP_MONTHS  = 1   # 訓練/測試之間的空白月數（避免標籤洩漏）

    # 多時間維度設定：各維度獨立訓練，各自做 Bonferroni 校正（N=63）
    # direction="short" 的維度會反轉 label（預測下跌而非上漲）
    DIMENSIONS = [
        {"key": "5d",        "forward_days": 5,  "threshold_low": 0.03, "threshold_high": 0.05, "direction": "long"},
        {"key": "10d",       "forward_days": 10, "threshold_low": 0.03, "threshold_high": 0.05, "direction": "long"},
        {"key": "30d",       "forward_days": 30, "threshold_low": 0.05, "threshold_high": 0.10, "direction": "long"},
        {"key": "5d_short",  "forward_days": 5,  "threshold_low": 0.03, "threshold_high": 0.05, "direction": "short"},
        {"key": "10d_short", "forward_days": 10, "threshold_low": 0.03, "threshold_high": 0.05, "direction": "short"},
        {"key": "30d_short", "forward_days": 30, "threshold_low": 0.05, "threshold_high": 0.10, "direction": "short"},
    ]

    # ─── 公開介面 ──────────────────────────────────────────────────────────────
    @classmethod
    def get_strategies(cls, db: Session) -> AlphaMinerResult:
        today = date.today()
        if cls._cache is not None and cls._cache_date == today:
            return cls._cache

        # 子程序剛結束 → 從 DB 快照恢復
        if cls._process is not None and not cls._process.is_alive():
            cls._process.join()
            cls._process = None
            restored = cls._load_snapshot(db, today)
            if restored:
                return cls._cache  # type: ignore[return-value]

        # 嘗試從 DB 快照恢復（後端重啟後的第一次請求）
        if cls._cache is None:
            restored = cls._load_snapshot(db, today)
            if restored:
                return cls._cache  # type: ignore[return-value]

        # READONLY 模式（本地 dev）：不觸發重訓，直接回傳 stub
        if settings.ALPHA_MINER_READONLY:
            logger.info("[AlphaMiner] READONLY 模式，跳過重訓")
            return cls._cache or _TRAINING_STUB

        # 若沒有正在執行的子程序，啟動新的
        with cls._lock:
            if cls._process is None or not cls._process.is_alive():
                _write_progress({"current": 0, "total": 0, "percent": 0,
                                 "current_dim": "", "current_strategy": ""})
                p = multiprocessing.Process(target=_run_training_subprocess, daemon=True)
                p.start()
                cls._process = p
                logger.info(f"[AlphaMiner] 訓練子程序已啟動 (PID {p.pid})")

        return cls._cache if cls._cache is not None else _TRAINING_STUB

    @classmethod
    def get_strategy_detail(cls, strategy_id: str, db: Session) -> Optional[StrategyDetail]:
        return cls._details.get(strategy_id)

    @classmethod
    def get_today_signals(
        cls, db: Session, dimension: str = "10d", direction: str = "long",
    ) -> List[TodaySignal]:
        """彙整訊號。

        direction='long': 找被多個策略同時看多的股票（現有邏輯）
        direction='short': 從 stock_features 找滿足多個看空條件的股票
        """
        result = cls.get_strategies(db)
        if result.is_training or not result.strategies:
            return []

        tlo = 0.05 if dimension == '30d' else 0.03
        thi = 0.10 if dimension == '30d' else 0.05

        # 放空：使用訓練好的 short 模型策略
        dim_key = f"{dimension}_short" if direction == 'short' else dimension

        stock_map: Dict[str, dict] = {}
        for ranking in result.strategies:
            if not ranking.is_significant or ranking.time_dimension != dim_key:
                continue
            # 做多只用 IC > 0（預測漲→實際漲）；放空只用 IC < 0（預測跌→實際跌）
            if direction == 'short':
                if ranking.ic >= 0:
                    continue
                ic = abs(ranking.ic)
            else:
                if ranking.ic <= 0:
                    continue
                ic = ranking.ic
            detail = cls._details.get(ranking.strategy_id)
            if not detail or not detail.recent_signals:
                continue
            for sig in detail.recent_signals:
                sid = sig.stock_id
                if sid not in stock_map:
                    stock_map[sid] = {
                        'stock_id': sid,
                        'stock_name': sig.stock_name,
                        'trigger_count': 0,
                        'strategies': [],
                        'signal_date': sig.signal_date,
                        '_ic_sum': 0.0,
                        '_w_win': 0.0,
                        '_w_win_hi': 0.0,
                        '_w_loss': 0.0,
                        '_w_loss_hi': 0.0,
                        '_w_mkt_win': 0.0,
                        '_w_mkt_win_hi': 0.0,
                        '_w_mkt_loss': 0.0,
                        '_w_mkt_loss_hi': 0.0,
                    }
                stock_map[sid]['trigger_count'] += 1
                stock_map[sid]['strategies'].append(ranking.strategy_name)
                stock_map[sid]['_ic_sum'] += ic
                stock_map[sid]['_w_win'] += ranking.win_rate_outsample * ic
                stock_map[sid]['_w_win_hi'] += ranking.win_rate_outsample_hi * ic
                stock_map[sid]['_w_loss'] += ranking.loss_rate_outsample * ic
                stock_map[sid]['_w_loss_hi'] += ranking.loss_rate_outsample_hi * ic
                stock_map[sid]['_w_mkt_win'] += ranking.market_win_rate * ic
                stock_map[sid]['_w_mkt_win_hi'] += ranking.market_win_rate_hi * ic
                stock_map[sid]['_w_mkt_loss'] += ranking.market_loss_rate * ic
                stock_map[sid]['_w_mkt_loss_hi'] += ranking.market_loss_rate_hi * ic

        # 動態門檻（做多和放空共用同一邏輯）
        valid_strategy_count = sum(
            1 for r in result.strategies
            if r.is_significant and r.time_dimension == dim_key
            and (r.ic < 0 if direction == 'short' else r.ic > 0)
        )
        min_triggers = max(2, round(valid_strategy_count * 0.4))

        signals = []
        for s in stock_map.values():
            if s['trigger_count'] < min_triggers:
                continue
            ic_sum = max(s['_ic_sum'], 1e-9)
            w_win = s['_w_win'] / ic_sum
            w_win_hi = s['_w_win_hi'] / ic_sum
            w_loss = s['_w_loss'] / ic_sum
            w_loss_hi = s['_w_loss_hi'] / ic_sum
            signals.append(TodaySignal(
                stock_id=s['stock_id'],
                stock_name=s['stock_name'],
                trigger_count=s['trigger_count'],
                strategies=s['strategies'],
                signal_date=s['signal_date'],
                time_dimension=dimension,
                threshold_low=tlo,
                threshold_high=thi,
                weighted_odds_ratio=w_win / max(w_loss, 0.001),
                weighted_odds_ratio_hi=w_win_hi / max(w_loss_hi, 0.001),
                weighted_win_rate=w_win,
                weighted_win_rate_hi=w_win_hi,
                weighted_loss_rate=w_loss,
                weighted_loss_rate_hi=w_loss_hi,
                weighted_market_win_rate=s['_w_mkt_win'] / ic_sum,
                weighted_market_win_rate_hi=s['_w_mkt_win_hi'] / ic_sum,
                weighted_market_loss_rate=s['_w_mkt_loss'] / ic_sum,
                weighted_market_loss_rate_hi=s['_w_mkt_loss_hi'] / ic_sum,
            ))

        signals.sort(key=lambda x: x.trigger_count, reverse=True)
        return signals[:20]

    @classmethod
    def invalidate_cache(cls) -> None:
        if cls._process is not None and cls._process.is_alive():
            cls._process.terminate()
            cls._process.join()
        cls._process = None
        cls._cache = None
        cls._cache_date = None
        cls._details = {}

    @classmethod
    def get_progress(cls) -> dict:
        is_training = cls._process is not None and cls._process.is_alive()
        p = _read_progress()
        p['is_training'] = is_training
        return p

    # ─── 訓練流程 ──────────────────────────────────────────────────────────────
    @classmethod
    def _train_all(cls, db: Session) -> AlphaMinerResult:
        df_base = cls._load_features(db)

        if df_base.empty:
            result = AlphaMinerResult(
                strategies=[], last_trained=date.today().isoformat(),
                train_period='N/A', test_period='N/A',
                total_combinations_tested=0, bonferroni_threshold=1.0,
            )
            cls._cache = result
            cls._cache_date = date.today()
            return result

        # ── 動態切割：依實際資料的最後日期往前推算 ─────────────────────────
        max_date = df_base['date'].max()
        test_start = (max_date - pd.DateOffset(months=cls.TEST_MONTHS)).date()
        train_end  = (max_date - pd.DateOffset(
            months=cls.TEST_MONTHS + cls.GAP_MONTHS)).date()

        # 分位數排名與時間權重只需計算一次（不依賴持有期）
        df_base = cls._compute_quantile_ranks(df_base)
        df_base = cls._add_weights(df_base, train_end)

        n_combos = len(FACTOR_COMBINATIONS)
        n_total = n_combos * len(cls.DIMENSIONS)
        all_rankings: List[StrategyRanking] = []
        all_details: Dict[str, StrategyDetail] = {}

        _write_progress({"current": 0, "total": n_total, "percent": 0,
                         "current_dim": "", "current_strategy": ""})

        completed = 0
        for dim in cls.DIMENSIONS:
            # 每個持有期各自計算 forward_return 與 label
            dim_direction = dim.get('direction', 'long')
            df_dim = cls._compute_forward_returns(df_base, dim['forward_days'], dim['threshold_low'], dim_direction)
            logger.info(f"[AlphaMiner] 開始訓練 {dim['key']} 維度（{n_combos} 組）")

            for i, factors in enumerate(FACTOR_COMBINATIONS):
                strategy_name = " + ".join(FACTOR_LABELS.get(f, f) for f in factors)
                _write_progress({
                    "current": completed, "total": n_total,
                    "percent": round(completed / n_total * 100),
                    "current_dim": dim['key'], "current_strategy": strategy_name,
                })
                logger.info(f"[AlphaMiner] [{dim['key']}] {i+1}/{n_combos}: {factors}")
                ranking, detail = cls._train_one(df_dim, factors, n_total, train_end, test_start, dim)
                if ranking is not None:
                    all_rankings.append(ranking)
                    all_details[ranking.strategy_id] = detail  # type: ignore[arg-type]
                completed += 1

        all_rankings.sort(key=lambda x: x.ic, reverse=True)

        min_date = df_base['date'].min()
        result = AlphaMinerResult(
            strategies=all_rankings,
            last_trained=date.today().isoformat(),
            train_period=f"{pd.Timestamp(min_date).strftime('%Y-%m')} ~ {train_end.strftime('%Y-%m')}",
            test_period=f"{test_start.strftime('%Y-%m')} ~ {pd.Timestamp(max_date).strftime('%Y-%m')}",
            total_combinations_tested=n_combos,
            bonferroni_threshold=round(0.05 / n_total, 6),
        )
        cls._cache = result
        cls._cache_date = date.today()
        cls._details = all_details

        # 持久化到 DB（訓練完成後存快照，重啟免重算）
        try:
            cls._save_snapshot(db, result, all_details)
        except Exception as e:
            logger.warning(f"[AlphaMiner] 快照存儲失敗（不影響結果）: {e}")

        return result

    # ─── 快照持久化 ────────────────────────────────────────────────────────────
    @classmethod
    def _save_snapshot(
        cls,
        db: Session,
        result: AlphaMinerResult,
        details: Dict[str, StrategyDetail],
    ) -> None:
        today = date.today()
        result_json  = result.model_dump_json()
        details_json = json.dumps({k: v.model_dump() for k, v in details.items()})

        db.execute(delete(AlphaMinerSnapshot))  # 只保留最新一筆
        db.add(AlphaMinerSnapshot(
            train_date=today,
            result_json=result_json,
            details_json=details_json,
        ))
        db.commit()
        logger.info(f"[AlphaMiner] 快照已儲存（{today}）")

    @classmethod
    def _load_snapshot(cls, db: Session, today: date) -> bool:
        """從 DB 恢復快取，回傳是否成功"""
        snap = db.query(AlphaMinerSnapshot).order_by(
            AlphaMinerSnapshot.train_date.desc()
        ).first()
        if snap is None:
            return False

        try:
            result  = AlphaMinerResult.model_validate_json(snap.result_json)
            raw_det = json.loads(snap.details_json)
            details = {k: StrategyDetail.model_validate(v) for k, v in raw_det.items()}
        except Exception as e:
            logger.warning(f"[AlphaMiner] 快照格式錯誤，將重新訓練: {e}")
            return False

        cls._cache      = result
        cls._cache_date = snap.train_date
        cls._details    = details

        if snap.train_date == today:
            logger.info(f"[AlphaMiner] 從 DB 快照恢復今日結果（{today}），跳過重算")
        elif settings.ALPHA_MINER_READONLY:
            logger.info(f"[AlphaMiner] READONLY 模式：使用舊快照（{snap.train_date}），不觸發重訓")
        else:
            logger.info(
                f"[AlphaMiner] 從 DB 快照恢復舊結果（{snap.train_date}），"
                "將在背景重新訓練今日模型"
            )
            # 有舊快取可以立即回傳，但同時啟動子程序重訓
            with cls._lock:
                if cls._process is None or not cls._process.is_alive():
                    _write_progress({"current": 0, "total": 0, "percent": 0,
                                     "current_dim": "", "current_strategy": ""})
                    p = multiprocessing.Process(target=_run_training_subprocess, daemon=True)
                    p.start()
                    cls._process = p
                    logger.info(f"[AlphaMiner] 背景重訓子程序已啟動 (PID {p.pid})")
        return True

    # ─── 資料載入 ──────────────────────────────────────────────────────────────
    @classmethod
    def _load_features(cls, db: Session) -> pd.DataFrame:
        from sqlalchemy import text
        cutoff = (date.today() - timedelta(days=365 * 2)).isoformat()
        cols = ", ".join(_LOAD_COLS)
        sql = text(f"SELECT {cols} FROM stock_features WHERE date >= :cutoff")
        df = pd.read_sql(sql, engine, params={"cutoff": cutoff})
        if df.empty:
            return df
        df['date'] = pd.to_datetime(df['date'])
        return df

    # ─── 特徵工程 ──────────────────────────────────────────────────────────────
    @classmethod
    def _compute_forward_returns(
        cls, df: pd.DataFrame, forward_days: int, threshold: float, direction: str = "long",
    ) -> pd.DataFrame:
        df = df.sort_values(['stock_id', 'date']).copy()
        df['forward_close'] = df.groupby('stock_id')['close'].shift(-forward_days)
        close = df['close'].replace(0, np.nan)
        df['forward_return'] = (df['forward_close'] - close) / close
        if direction == "short":
            # 放空：預測會跌（forward_return < -threshold = 1）
            df['label'] = np.where(df['forward_return'].isna(), np.nan,
                                   (df['forward_return'] < -threshold).astype(float))
        else:
            df['label'] = np.where(df['forward_return'].isna(), np.nan,
                                   (df['forward_return'] > threshold).astype(float))
        return df

    @classmethod
    def _compute_quantile_ranks(cls, df: pd.DataFrame) -> pd.DataFrame:
        all_factors = {f for combo in FACTOR_COMBINATIONS for f in combo}
        for factor in all_factors:
            if factor in df.columns:
                df[f'{factor}_rank'] = (
                    df.groupby('date')[factor]
                    .rank(pct=True, na_option='keep')
                )
        return df

    @classmethod
    def _add_weights(cls, df: pd.DataFrame, train_end: date) -> pd.DataFrame:
        # 以訓練集最後一年為基準，往前每年衰減 0.2（向量化，避免 .apply 逐列）
        base_year = train_end.year
        delta = base_year - df['date'].dt.year
        df['weight'] = (1.0 - delta * 0.2).clip(lower=0.2)
        return df

    # ─── 單策略訓練 ────────────────────────────────────────────────────────────
    @classmethod
    def _train_one(
        cls,
        df: pd.DataFrame,
        factors: List[str],
        n_total: int,
        train_end: date,
        test_start: date,
        dim: dict,
    ) -> Tuple[Optional[StrategyRanking], Optional[StrategyDetail]]:
        from sklearn.linear_model import LogisticRegression
        from scipy import stats

        thr_lo = dim['threshold_low']
        thr_hi = dim['threshold_high']

        rank_cols = [f'{f}_rank' for f in factors]
        if any(c not in df.columns for c in rank_cols):
            return None, None

        train_df = df[df['date'] <= pd.Timestamp(train_end)].dropna(
            subset=rank_cols + ['label'])
        test_df = df[df['date'] >= pd.Timestamp(test_start)].dropna(
            subset=rank_cols + ['label', 'forward_return'])

        # 趨勢過濾：10d/30d 做多只用上升趨勢、做空只用下降趨勢
        # 5d 不過濾——短期均值回歸在下跌趨勢中反彈更強（診斷實證）
        dim_direction = dim.get('direction', 'long')
        forward_days = dim.get('forward_days', 5)
        if 'ma60' in df.columns and forward_days >= 10:
            if dim_direction == 'long':
                train_df = train_df[train_df['close'] > train_df['ma60']].copy()
                test_df = test_df[test_df['close'] > test_df['ma60']].copy()
            else:
                train_df = train_df[train_df['close'] < train_df['ma60']].copy()
                test_df = test_df[test_df['close'] < test_df['ma60']].copy()

        if len(train_df) < 100 or len(test_df) < 30:
            return None, None

        X_train = train_df[rank_cols].values
        y_train = train_df['label'].values
        w_train = train_df['weight'].values

        try:
            model = LogisticRegression(
                tol=1e-3, max_iter=500, random_state=42, solver='lbfgs', C=1.0,
                class_weight='balanced')
            model.fit(X_train, y_train, sample_weight=w_train)
        except Exception:
            return None, None

        prob_train = model.predict_proba(X_train)[:, 1]
        X_test = test_df[rank_cols].values
        y_test  = test_df['label'].values
        prob_test = model.predict_proba(X_test)[:, 1]

        # 勝率/踩雷率：預測機率前 20%（Top Quintile）的實際報酬分布
        # 邏輯迴歸輸出聚集在 0.5 附近，用分位數門檻比固定 0.5 更有意義
        train_threshold = np.percentile(prob_train, 80)
        pos_train_mask  = prob_train >= train_threshold
        # 樣本內勝率（>+3%，用於過擬合檢測）
        train_returns = train_df['forward_return'].values
        win_rate_insample = (
            float((train_returns[pos_train_mask] > thr_lo).mean())
            if pos_train_mask.sum() > 0 else 0.5
        )

        test_threshold = np.percentile(prob_test, 80)
        pos_test_mask  = prob_test >= test_threshold
        sample_count_test = int(pos_test_mask.sum())

        top_returns = test_df['forward_return'].values[pos_test_mask]
        all_returns = test_df['forward_return'].values

        # 策略勝率（Top20%）— 低門檻與高門檻
        win_rate_outsample = (
            float((top_returns > thr_lo).mean()) if len(top_returns) > 0 else 0.0
        )
        win_rate_outsample_hi = (
            float((top_returns > thr_hi).mean()) if len(top_returns) > 0 else 0.0
        )
        # 策略踩雷率（Top20% 中 < -thr_lo 與 < -thr_hi）
        loss_rate_outsample = (
            float((top_returns < -thr_lo).mean()) if len(top_returns) > 0 else 0.0
        )
        loss_rate_outsample_hi = (
            float((top_returns < -thr_hi).mean()) if len(top_returns) > 0 else 0.0
        )
        # 賠率比（勝率 / 踩雷率，踩雷率為 0 時用 0.001 避免除零）
        odds_ratio    = round(win_rate_outsample    / max(loss_rate_outsample,    0.001), 2)
        odds_ratio_hi = round(win_rate_outsample_hi / max(loss_rate_outsample_hi, 0.001), 2)

        # 全市場基準（測試集所有股票）
        market_win_rate     = float((all_returns > thr_lo).mean())  if len(all_returns) > 0 else 0.0
        market_win_rate_hi  = float((all_returns > thr_hi).mean())  if len(all_returns) > 0 else 0.0
        market_loss_rate    = float((all_returns < -thr_lo).mean()) if len(all_returns) > 0 else 0.0
        market_loss_rate_hi = float((all_returns < -thr_hi).mean()) if len(all_returns) > 0 else 0.0

        # IC：逐日計算 Spearman 相關後對 IC 時間序列做 t-test
        # 原本用整個 panel 一次 spearmanr 會因樣本數膨脹（~20萬筆）導致 p-value 趨近 0
        # 正確做法：每日 IC 為一個獨立觀測值，t-test 自然處理橫截面相關性
        if len(prob_test) < 10:
            return None, None
        test_df_copy = test_df.copy()
        test_df_copy['_prob'] = prob_test
        daily_ics = []
        for _, grp in test_df_copy.groupby('date'):
            if len(grp) < 10:
                continue
            if grp['_prob'].nunique() < 2 or grp['forward_return'].nunique() < 2:
                continue
            ic_day, _ = stats.spearmanr(grp['_prob'], grp['forward_return'])
            if not np.isnan(ic_day):
                daily_ics.append(ic_day)
        if len(daily_ics) < 10:
            return None, None
        daily_ics_arr = np.array(daily_ics)
        ic = float(np.mean(daily_ics_arr))
        t_stat, p_val = stats.ttest_1samp(daily_ics_arr, 0)
        p_value = float(p_val) if not np.isnan(p_val) else 1.0
        p_value_corrected = min(p_value * n_total, 1.0)

        is_significant = p_value_corrected < 0.05
        overfit_warning = abs(win_rate_insample - win_rate_outsample) > 0.05

        integrity_flags: List[str] = []
        if sample_count_test < 30:
            integrity_flags.append("樣本不足，結果不具統計意義")
        elif sample_count_test < 80:
            integrity_flags.append("樣本數偏少，謹慎參考")
        if overfit_warning:
            integrity_flags.append("此策略可能存在過擬合")

        strategy_id   = f"{dim['key']}_{'_'.join(factors)}"
        strategy_name = " + ".join(FACTOR_LABELS.get(f, f) for f in factors)

        factor_weights = [
            FactorWeight(
                factor=f,
                factor_label=FACTOR_LABELS.get(f, f),
                coefficient=float(coef),
                direction="bullish" if coef > 0 else "bearish",
            )
            for f, coef in zip(factors, model.coef_[0])
        ]

        equity_curve   = cls._build_equity_curve(test_df, prob_test)
        recent_signals = cls._build_recent_signals(df, model, rank_cols, factors)

        ranking = StrategyRanking(
            strategy_id=strategy_id,
            strategy_name=strategy_name,
            factors=factors,
            time_dimension=dim['key'],
            threshold_low=thr_lo,
            threshold_high=thr_hi,
            win_rate_insample=win_rate_insample,
            win_rate_outsample=win_rate_outsample,
            win_rate_outsample_hi=win_rate_outsample_hi,
            loss_rate_outsample=loss_rate_outsample,
            loss_rate_outsample_hi=loss_rate_outsample_hi,
            odds_ratio=odds_ratio,
            odds_ratio_hi=odds_ratio_hi,
            market_win_rate=round(market_win_rate, 4),
            market_win_rate_hi=round(market_win_rate_hi, 4),
            market_loss_rate=round(market_loss_rate, 4),
            market_loss_rate_hi=round(market_loss_rate_hi, 4),
            ic=ic,
            p_value=p_value,
            p_value_corrected=p_value_corrected,
            is_significant=is_significant,
            overfit_warning=overfit_warning,
            sample_count_train=len(train_df),
            sample_count_test=sample_count_test,
            integrity_flags=integrity_flags,
        )
        detail = StrategyDetail(
            **ranking.model_dump(),
            equity_curve=equity_curve,
            recent_signals=recent_signals,
            factor_weights=factor_weights,
        )
        return ranking, detail

    # ─── 輔助：損益曲線 ────────────────────────────────────────────────────────
    @classmethod
    def _build_equity_curve(
        cls, test_df: pd.DataFrame, prob_test: np.ndarray
    ) -> List[EquityCurvePoint]:
        signals = test_df[prob_test > 0.5].copy()
        if signals.empty:
            return []
        signals['month'] = signals['date'].dt.to_period('M')
        monthly = signals.groupby('month')['forward_return'].mean().sort_index()
        cumulative = 0.0
        curve = []
        for period, ret in monthly.items():
            cumulative += float(ret)
            curve.append(EquityCurvePoint(
                date=str(period),
                cumulative_return=round(cumulative, 4),
            ))
        return curve

    # ─── 輔助：近期訊號 ────────────────────────────────────────────────────────
    @classmethod
    def _build_recent_signals(
        cls,
        df: pd.DataFrame,
        model,
        rank_cols: List[str],
        factors: List[str],
    ) -> List[RecentAlphaSignal]:
        try:
            import twstock
        except Exception:
            twstock = None

        # 找最近有完整資料的日期（至少 200 支股票）
        date_counts = df.groupby('date')['stock_id'].count()
        complete_dates = date_counts[date_counts >= 200].index
        if len(complete_dates) == 0:
            return []
        latest_date = complete_dates.max()

        recent = df[df['date'] == latest_date].dropna(subset=rank_cols)
        if recent.empty:
            return []

        X = recent[rank_cols].values
        prob = model.predict_proba(X)[:, 1]
        # Top 20% 作為訊號門檻，按機率排序後取前 50
        threshold = np.percentile(prob, 80)
        recent = recent.copy()
        recent['_prob'] = prob
        top_recent = recent[recent['_prob'] >= threshold].sort_values('_prob', ascending=False).head(50)

        result: List[RecentAlphaSignal] = []
        for _, row in top_recent.iterrows():
            stock_id = str(row['stock_id'])
            name = cls._lookup_name(stock_id)
            result.append(RecentAlphaSignal(
                stock_id=stock_id,
                stock_name=name,
                signal_date=latest_date.strftime('%Y-%m-%d'),
                predicted_prob=round(float(row['_prob']), 3),
                trigger_factors=factors,
            ))
        return result

    # ─── 訊號歷史：儲存 / 回填 / 查詢 ────────────────────────────────────────
    @classmethod
    def save_today_signals(cls, db: Session, dimension: str, direction: str = 'long') -> int:
        """將今日 get_today_signals 結果持久化到 alpha_signal_history。

        同一 (signal_date, stock_id, time_dimension, direction) 組合已存在時跳過（冪等）。
        若訓練尚未完成，每 2 分鐘重試，最多等待 60 分鐘。
        回傳實際寫入筆數。
        """
        import time as _time
        max_wait_minutes = 60
        for attempt in range(max_wait_minutes // 2):
            result = cls.get_strategies(db)
            if not result.is_training:
                break
            logger.info(f"[SignalHistory] {dimension}/{direction} 訓練尚未完成，等待 2 分鐘後重試（第 {attempt + 1} 次）...")
            _time.sleep(120)
        else:
            logger.error(f"[SignalHistory] {dimension}/{direction} 等待訓練逾時（{max_wait_minutes} 分鐘），放棄本日儲存")
            return 0

        signals = cls.get_today_signals(db, dimension=dimension, direction=direction)
        if not signals:
            logger.info(f"[SignalHistory] {dimension}/{direction} 無訊號，跳過儲存")
            return 0

        # 使用訊號中的實際資料日期（stock_features 最新交易日），而非 date.today()
        sig_date = date.fromisoformat(signals[0].signal_date)

        # 查出該日已存在的 stock_id 集合（避免重複）
        existing = {
            row.stock_id
            for row in db.query(AlphaSignalHistory.stock_id)
            .filter(
                AlphaSignalHistory.signal_date == sig_date,
                AlphaSignalHistory.time_dimension == dimension,
                AlphaSignalHistory.direction == direction,
            )
            .all()
        }

        rows = []
        for s in signals:
            if s.stock_id in existing:
                continue
            rows.append(AlphaSignalHistory(
                signal_date=sig_date,
                stock_id=s.stock_id,
                stock_name=s.stock_name,
                time_dimension=dimension,
                direction=direction,
                trigger_count=s.trigger_count,
                weighted_win_rate=s.weighted_win_rate,
                weighted_odds_ratio=s.weighted_odds_ratio,
            ))

        if rows:
            db.add_all(rows)
            db.commit()
            logger.info(f"[SignalHistory] 儲存 {dimension}/{direction} 訊號 {len(rows)} 筆（{sig_date}）")
        return len(rows)

    @classmethod
    def update_signal_returns(cls, db: Session) -> int:
        """對已到期但尚未結算的歷史訊號回填實際報酬率。

        持有期到期判斷（加 buffer 確保收盤資料已入庫）：
          5d  → signal_date + 7 天前（5 交易日 + 2 天 buffer）
          10d → signal_date + 14 天前（10 交易日 + 4 天 buffer）
          30d → signal_date + 45 天前（30 交易日 + 15 天 buffer）

        使用批次查詢避免 N+1。回傳成功結算筆數。
        """
        today = date.today()
        HOLDING = {"5d": 7, "10d": 14, "30d": 45}

        pending = (
            db.query(AlphaSignalHistory)
            .filter(AlphaSignalHistory.is_resolved == False)  # noqa: E712
            .all()
        )
        if not pending:
            return 0

        # 篩出已到期的記錄
        expired = [
            r for r in pending
            if (today - r.signal_date).days >= HOLDING.get(r.time_dimension, 14)
        ]
        if not expired:
            logger.info("[SignalHistory] 尚無到期訊號需要結算")
            return 0

        # 批次取所有需要的 stock_prices（用 ORM 避免 SQLite tuple 綁定問題）
        from app.models.stock_price import StockPrice as SP
        stock_ids = list({r.stock_id for r in expired})
        min_date  = min(r.signal_date for r in expired)

        price_rows = (
            db.query(SP.stock_id, SP.date, SP.close)
            .filter(SP.stock_id.in_(stock_ids), SP.date >= min_date)
            .order_by(SP.stock_id, SP.date)
            .all()
        )

        # 建立 {stock_id: {date: close}} 一次性預計算，避免 _find_price 重複建立字典
        price_map: Dict[str, Dict] = {}
        for row in price_rows:
            if row.stock_id not in price_map:
                price_map[row.stock_id] = {}
            price_map[row.stock_id][row.date] = float(row.close)

        def _find_price(stock_id: str, target_date) -> Optional[float]:
            """找 target_date 當日或最接近的後一個交易日收盤價（最多往後 20 天）
            放寬至 20 天以涵蓋長假期（農曆春節約 7-10 天停市）及個股停牌情況。
            """
            price_dict = price_map.get(stock_id, {})
            # 先精確查
            if target_date in price_dict:
                return price_dict[target_date]
            # fallback：往後找最近交易日（最多 20 天）
            for delta in range(1, 21):
                fallback_date = target_date + timedelta(days=delta)
                if fallback_date in price_dict:
                    return price_dict[fallback_date]
            return None

        resolved_count = 0
        for rec in expired:
            holding_days = {"5d": 5, "10d": 10, "30d": 30}[rec.time_dimension]
            entry = _find_price(rec.stock_id, rec.signal_date)
            exit_date = rec.signal_date + timedelta(days=holding_days)
            exit_price = _find_price(rec.stock_id, exit_date)

            if entry is None or exit_price is None or entry == 0:
                continue

            raw_return = (exit_price - entry) / entry
            # 放空訊號：報酬反轉（股價跌 = 獲利）
            if getattr(rec, 'direction', 'long') == 'short':
                raw_return = -raw_return
            rec.actual_return = round(raw_return, 4)
            rec.resolved_date = today
            rec.is_resolved   = True
            resolved_count += 1

        if resolved_count:
            db.commit()
            logger.info(f"[SignalHistory] 結算 {resolved_count} 筆訊號報酬")
        return resolved_count

    @classmethod
    def get_signal_history(
        cls, db: Session, days: int = 14, dimension: str = "10d"
    ) -> List[SignalHistoryItem]:
        """查詢近 days 天的訊號歷史記錄"""
        cutoff = date.today() - timedelta(days=days)
        rows = (
            db.query(AlphaSignalHistory)
            .filter(
                AlphaSignalHistory.time_dimension == dimension,
                AlphaSignalHistory.signal_date >= cutoff,
            )
            .order_by(AlphaSignalHistory.signal_date.desc(), AlphaSignalHistory.trigger_count.desc())
            .all()
        )
        return [
            SignalHistoryItem(
                signal_date=r.signal_date.isoformat(),
                stock_id=r.stock_id,
                stock_name=r.stock_name,
                time_dimension=r.time_dimension,
                direction=getattr(r, 'direction', 'long') or 'long',
                trigger_count=r.trigger_count,
                weighted_win_rate=r.weighted_win_rate,
                weighted_odds_ratio=r.weighted_odds_ratio,
                actual_return=r.actual_return,
                resolved_date=r.resolved_date.isoformat() if r.resolved_date else None,
                is_resolved=r.is_resolved,
            )
            for r in rows
        ]

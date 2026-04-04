"""
AlphaMinerService — LightGBM 多因子模型

設計原則：
- 每個時間維度訓練一個 LightGBM 模型，使用 11 個穩定因子（基本面+外資動向）
- Walk-forward 驗證：11 因子 IC 100% 為正，34 因子只有 71%（技術指標是噪音）
- 分位數排名消除跨股票量綱差異
- 時間衰減權重（近期資料比舊資料重要）
- 訓練/測試嚴格時間切割，留一個月空白期避免標籤洩漏
- Bonferroni 多重校正（N=2）防止 p-hacking
- 樣本外 Spearman IC 為排序依據
- SHAP-style factor contributions（pred_contrib）提取每支股票的 trigger_factors
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
from sqlalchemy import delete, func

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

# ─── 因子中文標籤（全量，用於 UI 顯示與特徵載入）─────────────────────────────
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
    # Phase 8 波動率
    'ivol_20d':         '特異波動率',
}

# ─── 訓練用因子（每個維度可用不同因子集）────────────────────────────
# 2026-04-04 全方位因子篩選（40 因子）→ 10 因子 baseline
# 2026-04-04 多維度研究：5d/10d/20d walk-forward 驗證
TRAINING_FACTORS: Dict[str, str] = {
    # 基本面 — 全期穩定正 IC
    'roe':                  'ROE',
    'yield_rate':           '殖利率',
    'pb_ratio':             '股淨比',
    'revenue_yoy':          '營收YoY',
    # 營收衍生 — IC 0.15+，穩定性最高
    'rev_surprise':         '營收驚喜',
    'rev_accel':            '營收加速度',
    # 穩定籌碼 — 長期 IC 正且不隨市場風格反轉
    'foreign_hold_chg_5d':  '外資持股5日變化',
    'dealer_buy_20d':       '自營商20日累積',
    'vol_ratio':            '量比',
    # 波動率 — 低特異波動率溢酬，獨立於基本面和籌碼（Phase 8）
    'ivol_20d':             '特異波動率',
}

# 5d 專用因子：基本面 + 短線指標（research IC=0.019，L-S +0.51%）
TRAINING_FACTORS_5D: Dict[str, str] = {
    'roe':                  'ROE',
    'yield_rate':           '殖利率',
    'pb_ratio':             '股淨比',
    'revenue_yoy':          '營收YoY',
    'rsi2':                 'RSI(2)',
    'vol_ratio':            '量比',
    'neg_bias5':            '反向乖離5日',
}

# 20d 專用因子：10 因子 + 反向投信（research IC +18%: 0.029→0.034）
TRAINING_FACTORS_20D: Dict[str, str] = {
    **TRAINING_FACTORS,
    'neg_trust_net_buy':    '反向投信',
}

# 每個維度使用的因子
DIMENSION_FACTORS: Dict[str, Dict[str, str]] = {
    '5d':  TRAINING_FACTORS_5D,
    '10d': TRAINING_FACTORS,
    '20d': TRAINING_FACTORS_20D,
}

# 收集所有維度需要的原始欄位（去重）
_ALL_FACTOR_COLS = set()
for _fmap in DIMENSION_FACTORS.values():
    for _f in _fmap.keys():
        _ALL_FACTOR_COLS.add(_f.replace('neg_', '') if _f.startswith('neg_') else _f)

_LOAD_COLS = ['stock_id', 'date', 'close', 'ma60'] + sorted(_ALL_FACTOR_COLS)

# Bonferroni 校正：3 個維度
_BONFERRONI_N = 3

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
    from app.db.database import SessionLocal, engine as _engine
    _log.basicConfig(level=logging.INFO)
    # fork 後必須 dispose 父程序的連線池，避免父子共用同一 PostgreSQL 連線
    # 導致 "lost synchronization with server" 錯誤
    _engine.dispose()
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
    """LightGBM 多因子模型訓練與排行榜快取（每維度一個模型，共 6 個）"""

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

    # 維度設定：5d/10d/20d 三維度獨立模型
    # 2026-04-04 多維度研究驗證：
    #   5d: IC=0.019, L-S=0.51%, 做空WR=53% — 參考級（受交易成本限制）
    #  10d: IC=0.020, L-S=1.45%, 做空WR=55% — 可用（Bot10%為負）
    #  20d: IC=0.034, L-S=3.34%, 做空WR=58% — 主力（+反向投信 IC +18%）
    DIMENSIONS = [
        {"key": "5d",  "forward_days": 5,  "threshold_low": 0.02, "threshold_high": 0.03, "direction": "long"},
        {"key": "10d", "forward_days": 10, "threshold_low": 0.03, "threshold_high": 0.05, "direction": "long"},
        {"key": "20d", "forward_days": 20, "threshold_low": 0.03, "threshold_high": 0.05, "direction": "long"},
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
        cls, db: Session, dimension: str = "20d", direction: str = "long",
    ) -> List[TodaySignal]:
        """從該維度的 Ensemble 模型的 recent_signals 轉換為 TodaySignal。

        20d 使用「10d 共振」過濾：只推薦同時在 10d 模型 Top 訊號的股票。
        共振回測：報酬 +3.62%（20d 單獨 +2.05%），勝率 51%（20d 47%）。
        """
        result = cls.get_strategies(db)
        if result.is_training or not result.strategies:
            return []

        tlo = 0.03
        thi = 0.05

        # 找該維度對應的策略
        strategy_id = f"lgb_{dimension}"
        detail = cls._details.get(strategy_id)
        if not detail or not detail.recent_signals:
            return []

        # 找對應 ranking 取得維度層級的統計數據
        ranking = None
        for r in result.strategies:
            if r.strategy_id == strategy_id:
                ranking = r
                break
        if ranking is None:
            return []

        # 共振過濾：取得 10d 模型的 Top 股票集合
        resonance_ids: set = set()
        if dimension == "20d":
            detail_10d = cls._details.get("lgb_10d")
            if detail_10d and detail_10d.recent_signals:
                resonance_ids = {sig.stock_id for sig in detail_10d.recent_signals}
                logger.info(f"[AlphaMiner] 共振過濾：10d Top {len(resonance_ids)} 檔")

        # 低波動 Overlay：查最新一天的 ivol_20d，取中位數做為穩定型門檻
        # 研究驗證：低波動過濾 Sharpe +17%, MDD -12%
        from app.models.stock_feature import StockFeature
        latest_feat_date = db.query(func.max(StockFeature.date)).scalar()
        ivol_map: Dict[str, float] = {}
        ivol_median: float = float('inf')
        if latest_feat_date:
            feat_rows = db.query(
                StockFeature.stock_id, StockFeature.ivol_20d
            ).filter(
                StockFeature.date == latest_feat_date,
                StockFeature.ivol_20d.isnot(None),
            ).all()
            ivol_map = {r.stock_id: r.ivol_20d for r in feat_rows}
            if ivol_map:
                ivol_median = float(sorted(ivol_map.values())[len(ivol_map) // 2])

        signals = []
        for sig in detail.recent_signals:
            # 如果有共振集合，只保留同時在 10d Top 的股票
            if resonance_ids and sig.stock_id not in resonance_ids:
                continue

            n_positive = len(sig.trigger_factors)
            top_factors = [TRAINING_FACTORS.get(f, FACTOR_LABELS.get(f, f)) for f in sig.trigger_factors[:3]]
            prob = sig.predicted_prob
            odds = prob / max(1 - prob, 1e-6)

            # 低波動 = ivol_20d < 中位數（波動率低於市場一半的股票）
            stock_ivol = ivol_map.get(sig.stock_id)
            is_stable = stock_ivol is not None and stock_ivol <= ivol_median

            signals.append(TodaySignal(
                stock_id=sig.stock_id,
                stock_name=sig.stock_name,
                trigger_count=n_positive,
                strategies=top_factors,
                signal_date=sig.signal_date,
                time_dimension=dimension,
                threshold_low=tlo,
                threshold_high=thi,
                weighted_odds_ratio=round(odds, 2),
                weighted_odds_ratio_hi=round(odds, 2),
                weighted_win_rate=ranking.win_rate_outsample,
                weighted_win_rate_hi=ranking.win_rate_outsample_hi,
                weighted_loss_rate=ranking.loss_rate_outsample,
                weighted_loss_rate_hi=ranking.loss_rate_outsample_hi,
                weighted_market_win_rate=ranking.market_win_rate,
                weighted_market_win_rate_hi=ranking.market_win_rate_hi,
                weighted_market_loss_rate=ranking.market_loss_rate,
                weighted_market_loss_rate_hi=ranking.market_loss_rate_hi,
                is_stable=is_stable,
            ))

        n_stable = sum(1 for s in signals if s.is_stable)
        logger.info(f"[AlphaMiner] {dimension} 訊號{'（共振後）' if resonance_ids else ''}: {len(signals)} 檔（穩定型 {n_stable} 檔）")
        # 按 odds ratio 降序排列
        signals.sort(key=lambda x: x.weighted_odds_ratio, reverse=True)
        return signals[:20]

    @classmethod
    def get_recommendations(cls, db: Session, top_n: int = 5) -> 'RecommendationTable':
        """產生多維度多空推薦清單（5d/10d/20d × 看漲/看跌 × Top N）"""
        from app.schemas.alpha_miner import (
            RecommendationPick, DimensionRecommendation, RecommendationTable,
        )
        from app.models.stock_feature import StockFeature

        result = cls.get_strategies(db)
        if result.is_training or not result.strategies:
            return RecommendationTable(
                dimensions=[], last_trained=result.last_trained,
                train_period=result.train_period, test_period=result.test_period,
            )

        # 低波動 Overlay
        latest_feat_date = db.query(func.max(StockFeature.date)).scalar()
        ivol_map: Dict[str, float] = {}
        ivol_median: float = float('inf')
        if latest_feat_date:
            feat_rows = db.query(
                StockFeature.stock_id, StockFeature.ivol_20d
            ).filter(
                StockFeature.date == latest_feat_date,
                StockFeature.ivol_20d.isnot(None),
            ).all()
            ivol_map = {r.stock_id: r.ivol_20d for r in feat_rows}
            if ivol_map:
                ivol_median = float(sorted(ivol_map.values())[len(ivol_map) // 2])

        dimensions = []
        for ranking in result.strategies:
            dim_key = ranking.time_dimension
            strategy_id = ranking.strategy_id
            detail = cls._details.get(strategy_id)
            if not detail or not detail.recent_signals:
                continue

            dim_factors = DIMENSION_FACTORS.get(dim_key, TRAINING_FACTORS)
            # 分離做多/做空訊號（按 predicted_prob 分）
            all_sigs = detail.recent_signals
            if not all_sigs:
                continue

            # 中位數作為分界：高於中位數 = 做多候選，低於 = 做空候選
            probs = [s.predicted_prob for s in all_sigs]
            median_prob = sorted(probs)[len(probs) // 2]

            long_sigs = sorted(
                [s for s in all_sigs if s.predicted_prob >= median_prob],
                key=lambda s: s.predicted_prob, reverse=True
            )[:top_n]

            # 做空：最低分排前面
            short_sigs = sorted(
                [s for s in all_sigs if s.predicted_prob < median_prob],
                key=lambda s: s.predicted_prob
            )[:top_n]

            def _to_picks(sigs: list, is_short: bool = False) -> List[RecommendationPick]:
                picks = []
                for i, sig in enumerate(sigs):
                    stock_ivol = ivol_map.get(sig.stock_id)
                    is_stable = stock_ivol is not None and stock_ivol <= ivol_median
                    top_labels = [
                        dim_factors.get(f, TRAINING_FACTORS.get(f, FACTOR_LABELS.get(f, f)))
                        for f in sig.trigger_factors[:3]
                    ]
                    picks.append(RecommendationPick(
                        rank=i + 1,
                        stock_id=sig.stock_id,
                        stock_name=sig.stock_name,
                        score=round(sig.predicted_prob, 4),
                        trigger_factors=top_labels,
                        is_stable=is_stable,
                    ))
                return picks

            signal_date = long_sigs[0].signal_date if long_sigs else (short_sigs[0].signal_date if short_sigs else '')

            # 信心等級
            if ranking.ic > 0.03 and ranking.is_significant:
                confidence = "high"
            elif ranking.ic > 0.015:
                confidence = "medium"
            else:
                confidence = "low"

            dim_config = next((d for d in cls.DIMENSIONS if d['key'] == dim_key), {})
            forward_days = dim_config.get('forward_days', 20)

            dimensions.append(DimensionRecommendation(
                dimension=dim_key,
                forward_days=forward_days,
                signal_date=signal_date,
                long_picks=_to_picks(long_sigs),
                long_win_rate=round(ranking.win_rate_positive * 100, 1),
                long_avg_return=round(ranking.avg_return_top, 2),
                short_picks=_to_picks(short_sigs, is_short=True),
                short_win_rate=round(ranking.short_win_rate * 100, 1),
                short_avg_return=round(ranking.avg_return_bottom, 2),
                ic=round(ranking.ic, 4),
                is_significant=ranking.is_significant,
                confidence=confidence,
            ))

        # 按 forward_days 排序（5d → 10d → 20d）
        dimensions.sort(key=lambda d: d.forward_days)

        return RecommendationTable(
            dimensions=dimensions,
            last_trained=result.last_trained,
            train_period=result.train_period,
            test_period=result.test_period,
        )

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

        n_dims = len(cls.DIMENSIONS)
        all_rankings: List[StrategyRanking] = []
        all_details: Dict[str, StrategyDetail] = {}

        _write_progress({"current": 0, "total": n_dims, "percent": 0,
                         "current_dim": "", "current_strategy": ""})

        for idx, dim in enumerate(cls.DIMENSIONS):
            dim_direction = dim.get('direction', 'long')
            dir_label = "做多" if dim_direction == "long" else "做空"
            strategy_name = f"LightGBM {dim['key'].replace('_short', '')} {dir_label}"
            _write_progress({
                "current": idx, "total": n_dims,
                "percent": round(idx / n_dims * 100),
                "current_dim": dim['key'], "current_strategy": strategy_name,
            })

            # 每個持有期各自計算 forward_return 與 label
            df_dim = cls._compute_forward_returns(
                df_base, dim['forward_days'], dim['threshold_low'], dim_direction)
            logger.info(f"[AlphaMiner] 開始訓練 {dim['key']} 維度（LightGBM，{len(TRAINING_FACTORS)} 穩定因子）")

            ranking, detail = cls._train_dimension(
                df_dim, train_end, test_start, dim)
            if ranking is not None:
                all_rankings.append(ranking)
                all_details[ranking.strategy_id] = detail  # type: ignore[arg-type]

        all_rankings.sort(key=lambda x: x.ic, reverse=True)

        min_date = df_base['date'].min()
        result = AlphaMinerResult(
            strategies=all_rankings,
            last_trained=date.today().isoformat(),
            train_period=f"{pd.Timestamp(min_date).strftime('%Y-%m')} ~ {train_end.strftime('%Y-%m')}",
            test_period=f"{test_start.strftime('%Y-%m')} ~ {pd.Timestamp(max_date).strftime('%Y-%m')}",
            total_combinations_tested=n_dims,
            bonferroni_threshold=round(0.05 / _BONFERRONI_N, 6),
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
        # 衍生反向因子（neg_ = 取負數）
        neg_map = {
            'trust_net_buy':  'neg_trust_net_buy',
            'trust_buy_5d':   'neg_trust_buy_5d',
            'trust_buy_10d':  'neg_trust_buy_10d',
            'trust_buy_20d':  'neg_trust_buy_20d',
            'bias5':          'neg_bias5',
        }
        for src, dst in neg_map.items():
            if src in df.columns:
                df[dst] = -df[src].fillna(0)
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
        # 計算所有維度因子的分位數排名
        all_factors = set()
        for fmap in DIMENSION_FACTORS.values():
            all_factors.update(fmap.keys())
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

    # ─── 單維度 Ensemble 訓練（Classifier + Regressor 等權混合）──────────────────
    @classmethod
    def _train_dimension(
        cls,
        df: pd.DataFrame,
        train_end: date,
        test_start: date,
        dim: dict,
    ) -> Tuple[Optional[StrategyRanking], Optional[StrategyDetail]]:
        import lightgbm as lgb
        from scipy import stats

        thr_lo = dim['threshold_low']
        thr_hi = dim['threshold_high']
        dim_direction = dim.get('direction', 'long')
        forward_days = dim.get('forward_days', 5)

        # 每個維度使用自己的因子集
        dim_key = dim['key']
        dim_factors = DIMENSION_FACTORS.get(dim_key, TRAINING_FACTORS)
        factors = list(dim_factors.keys())
        rank_cols = [f'{f}_rank' for f in factors]
        # 只留存在於 DataFrame 中的因子
        available = [(f, rc) for f, rc in zip(factors, rank_cols) if rc in df.columns]
        if len(available) < 5:
            return None, None
        factors = [a[0] for a in available]
        rank_cols = [a[1] for a in available]

        # LightGBM 原生支援 NaN，只需 drop label 為空的列
        train_df = df[df['date'] <= pd.Timestamp(train_end)].dropna(
            subset=['label'])
        test_df = df[df['date'] >= pd.Timestamp(test_start)].dropna(
            subset=['label', 'forward_return'])

        # MA60 趨勢過濾：僅 20d+ 使用（回測 IC 從 0.025→0.10）
        # 5d/10d 不過濾（回測 IC 無差異，移除後樣本更多）
        if 'ma60' in df.columns and forward_days >= 20:
            if dim_direction == 'long':
                train_df = train_df[train_df['close'] > train_df['ma60']].copy()
                test_df = test_df[test_df['close'] > test_df['ma60']].copy()
            else:
                train_df = train_df[train_df['close'] < train_df['ma60']].copy()
                test_df = test_df[test_df['close'] < test_df['ma60']].copy()

        if len(train_df) < 200 or len(test_df) < 50:
            return None, None

        X_train = train_df[rank_cols].values
        y_train = train_df['label'].values
        w_train = train_df['weight'].values
        X_test = test_df[rank_cols].values
        y_test = test_df['label'].values

        try:
            # ── Classifier ──
            clf = lgb.LGBMClassifier(
                n_estimators=200, max_depth=4, num_leaves=15,
                learning_rate=0.01, min_child_samples=100,
                subsample=0.8, colsample_bytree=0.8,
                reg_alpha=0.1, reg_lambda=1.0,
                random_state=42, verbose=-1, is_unbalance=True,
                importance_type='gain',
            )
            clf.fit(X_train, y_train, sample_weight=w_train)

            # ── Regressor（預測實際報酬率，clip 極端值）──
            y_train_ret = train_df['forward_return'].values.clip(-0.5, 0.5)
            reg = lgb.LGBMRegressor(
                n_estimators=200, max_depth=4, num_leaves=15,
                learning_rate=0.01, min_child_samples=100,
                subsample=0.8, colsample_bytree=0.8,
                reg_alpha=0.1, reg_lambda=1.0,
                random_state=42, verbose=-1,
                importance_type='gain',
            )
            reg.fit(X_train, y_train_ret, sample_weight=w_train)
        except Exception as e:
            logger.warning(f"[AlphaMiner] LightGBM 訓練失敗 ({dim['key']}): {e}")
            return None, None

        # ── Ensemble：Classifier 機率 + Regressor 預測 等權混合 ──
        p_clf_train = clf.predict_proba(X_train)[:, 1]
        p_clf_test  = clf.predict_proba(X_test)[:, 1]
        p_reg_train = reg.predict(X_train)
        p_reg_test  = reg.predict(X_test)

        # Regressor 預測 normalize 到 [0, 1]（與 Classifier 機率對齊）
        reg_min, reg_max = p_reg_train.min(), p_reg_train.max()
        reg_range = reg_max - reg_min + 1e-9
        p_reg_train_n = (p_reg_train - reg_min) / reg_range
        p_reg_test_n  = np.clip((p_reg_test - reg_min) / reg_range, 0, 1)

        prob_train = 0.5 * p_clf_train + 0.5 * p_reg_train_n
        prob_test  = 0.5 * p_clf_test  + 0.5 * p_reg_test_n
        model = clf  # factor_weights 用 Classifier 的 importance

        # 勝率/踩雷率：預測機率前 20%（Top Quintile）的實際報酬分布
        train_threshold = np.percentile(prob_train, 80)
        pos_train_mask = prob_train >= train_threshold
        train_returns = train_df['forward_return'].values
        win_rate_insample = (
            float((train_returns[pos_train_mask] > thr_lo).mean())
            if pos_train_mask.sum() > 0 else 0.5
        )

        test_threshold = np.percentile(prob_test, 80)
        pos_test_mask = prob_test >= test_threshold
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
        # 策略踩雷率
        loss_rate_outsample = (
            float((top_returns < -thr_lo).mean()) if len(top_returns) > 0 else 0.0
        )
        loss_rate_outsample_hi = (
            float((top_returns < -thr_hi).mean()) if len(top_returns) > 0 else 0.0
        )
        # 真實勝率（報酬 > 0%）與 Top20% 平均報酬 — 用於前端顯示
        win_rate_positive = (
            float((top_returns > 0).mean()) if len(top_returns) > 0 else 0.0
        )
        avg_return_top = (
            float(np.nanmean(top_returns) * 100) if len(top_returns) > 0 else 0.0
        )

        # 做空端指標（Bottom 20%）：模型分數最低的股票
        bot_threshold = np.percentile(prob_test, 20)
        bot_test_mask = prob_test <= bot_threshold
        bot_returns = test_df['forward_return'].values[bot_test_mask]
        short_win_rate = (
            float((bot_returns < 0).mean()) if len(bot_returns) > 0 else 0.0
        )
        avg_return_bottom = (
            float(np.nanmean(bot_returns) * 100) if len(bot_returns) > 0 else 0.0
        )

        odds_ratio    = round(win_rate_outsample    / max(loss_rate_outsample,    0.001), 2)
        odds_ratio_hi = round(win_rate_outsample_hi / max(loss_rate_outsample_hi, 0.001), 2)

        # 全市場基準
        market_win_rate     = float((all_returns > thr_lo).mean())  if len(all_returns) > 0 else 0.0
        market_win_rate_hi  = float((all_returns > thr_hi).mean())  if len(all_returns) > 0 else 0.0
        market_loss_rate    = float((all_returns < -thr_lo).mean()) if len(all_returns) > 0 else 0.0
        market_loss_rate_hi = float((all_returns < -thr_hi).mean()) if len(all_returns) > 0 else 0.0

        # IC：逐日計算 Spearman 相關後對 IC 時間序列做 t-test
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
        p_value_corrected = min(p_value * _BONFERRONI_N, 1.0)

        is_significant = p_value_corrected < 0.05
        overfit_warning = abs(win_rate_insample - win_rate_outsample) > 0.05

        integrity_flags: List[str] = []
        if sample_count_test < 30:
            integrity_flags.append("樣本不足，結果不具統計意義")
        elif sample_count_test < 80:
            integrity_flags.append("樣本數偏少，謹慎參考")
        if overfit_warning:
            integrity_flags.append("此策略可能存在過擬合")

        dir_label = "做多" if dim_direction == "long" else "做空"
        dim_base = dim['key'].replace('_short', '')
        strategy_id   = f"lgb_{dim['key']}"
        strategy_name = f"LightGBM {dim_base} {dir_label}"

        # factor_weights：按 gain-based feature importance 排序
        importances = model.feature_importances_
        sorted_indices = np.argsort(importances)[::-1]
        factor_weights = [
            FactorWeight(
                factor=factors[i],
                factor_label=dim_factors.get(factors[i], TRAINING_FACTORS.get(factors[i], FACTOR_LABELS.get(factors[i], factors[i]))),
                coefficient=float(importances[i]),
                direction="bullish",  # LightGBM 無法直接判定方向，統一標 bullish
            )
            for i in sorted_indices
            if importances[i] > 0
        ]

        equity_curve   = cls._build_equity_curve(test_df, prob_test)
        recent_signals = cls._build_recent_signals_lgb(df, clf, reg, reg_min, reg_range, rank_cols, factors)

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
            win_rate_positive=round(win_rate_positive, 4),
            avg_return_top=round(avg_return_top, 2),
            short_win_rate=round(short_win_rate, 4),
            avg_return_bottom=round(avg_return_bottom, 2),
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

    # ─── 輔助：近期訊號（LightGBM pred_contrib）─────────────────────────────────
    @classmethod
    def _build_recent_signals_lgb(
        cls,
        df: pd.DataFrame,
        clf,
        reg,
        reg_min: float,
        reg_range: float,
        rank_cols: List[str],
        factors: List[str],
    ) -> List[RecentAlphaSignal]:
        # 找最近有完整資料的日期（至少 200 支股票）
        date_counts = df.groupby('date')['stock_id'].count()
        complete_dates = date_counts[date_counts >= 200].index
        if len(complete_dates) == 0:
            return []
        latest_date = complete_dates.max()

        recent = df[df['date'] == latest_date]
        if recent.empty:
            return []

        X = recent[rank_cols].values
        # Ensemble：Classifier + Regressor 等權混合
        p_clf = clf.predict_proba(X)[:, 1]
        p_reg = np.clip((reg.predict(X) - reg_min) / reg_range, 0, 1)
        prob = 0.5 * p_clf + 0.5 * p_reg
        # Top 10% + Bottom 10% 都作為訊號
        threshold_top = np.percentile(prob, 90)
        threshold_bot = np.percentile(prob, 10)
        recent = recent.copy()
        recent['_prob'] = prob
        top_recent = recent[recent['_prob'] >= threshold_top].sort_values('_prob', ascending=False).head(50)
        # 做空訊號：分數最低的股票（預期下跌）
        bot_recent = recent[recent['_prob'] <= threshold_bot].sort_values('_prob', ascending=True).head(50)

        if top_recent.empty and bot_recent.empty:
            return []

        def _extract_signals(subset: pd.DataFrame, is_short: bool = False) -> List[RecentAlphaSignal]:
            if subset.empty:
                return []
            X_sub = subset[rank_cols].values
            try:
                contribs = clf.booster_.predict(X_sub, pred_contrib=True)[:, :-1]
            except Exception:
                contribs = None

            signals_list: List[RecentAlphaSignal] = []
            for idx_enum, (_, row) in enumerate(subset.iterrows()):
                stock_id = str(row['stock_id'])
                name = cls._lookup_name(stock_id)

                if contribs is not None:
                    contrib_row = contribs[idx_enum]
                    if is_short:
                        # 做空：取「負貢獻」最大的因子（拉低分數的因子）
                        negative_indices = np.where(contrib_row < 0)[0]
                        sorted_neg = negative_indices[np.argsort(contrib_row[negative_indices])]
                        trigger = [factors[i] for i in sorted_neg[:3]]
                    else:
                        positive_indices = np.where(contrib_row > 0)[0]
                        sorted_pos = positive_indices[np.argsort(contrib_row[positive_indices])[::-1]]
                        trigger = [factors[i] for i in sorted_pos[:3]]
                else:
                    importances = clf.feature_importances_
                    top_idx = np.argsort(importances)[::-1][:3]
                    trigger = [factors[i] for i in top_idx]

                signals_list.append(RecentAlphaSignal(
                    stock_id=stock_id,
                    stock_name=name,
                    signal_date=latest_date.strftime('%Y-%m-%d'),
                    predicted_prob=round(float(row['_prob']), 6),
                    trigger_factors=trigger,
                ))
            return signals_list

        # 合併：先 top（正序）再 bot（反序），前端用 predicted_prob 區分多空
        result = _extract_signals(top_recent, is_short=False)
        result += _extract_signals(bot_recent, is_short=True)
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
          20d → signal_date + 30 天前（20 交易日 + 10 天 buffer）

        使用批次查詢避免 N+1。回傳成功結算筆數。
        """
        today = date.today()
        HOLDING = {"20d": 30, "10d": 14}

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
            if (today - r.signal_date).days >= HOLDING.get(r.time_dimension, 30)
        ]
        if not expired:
            logger.info("[SignalHistory] 尚無到期訊號需要結算")
            return 0

        # 批次取所有需要的 stock_prices
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

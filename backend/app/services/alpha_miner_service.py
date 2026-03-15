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

from app.models.stock_feature import StockFeature
from app.models.alpha_miner_snapshot import AlphaMinerSnapshot
from app.schemas.alpha_miner import (
    AlphaMinerResult, StrategyRanking, StrategyDetail,
    FactorWeight, RecentAlphaSignal, EquityCurvePoint, TodaySignal,
)

# ─── 因子中文標籤 ──────────────────────────────────────────────────────────────
FACTOR_LABELS: Dict[str, str] = {
    'rsi14':           'RSI',
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
]

_LOAD_COLS = ['stock_id', 'date', 'close'] + list(FACTOR_LABELS.keys())

# Bonferroni 校正說明更新：63 組組合
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

    TEST_MONTHS = 6   # 測試集保留最後幾個月
    GAP_MONTHS  = 1   # 訓練/測試之間的空白月數（避免標籤洩漏）

    # 多時間維度設定：各維度獨立訓練，各自做 Bonferroni 校正（N=63）
    DIMENSIONS = [
        {"key": "5d",  "forward_days": 5,  "threshold_low": 0.03, "threshold_high": 0.05},
        {"key": "10d", "forward_days": 10, "threshold_low": 0.03, "threshold_high": 0.05},
        {"key": "30d", "forward_days": 30, "threshold_low": 0.05, "threshold_high": 0.10},
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
    def get_today_signals(cls, db: Session, dimension: str = "10d") -> List[TodaySignal]:
        """彙整所有顯著策略的近期訊號，找出被多個策略同時看好的股票"""
        result = cls.get_strategies(db)
        if result.is_training or not result.strategies:
            return []

        tlo = 0.05 if dimension == '30d' else 0.03
        thi = 0.10 if dimension == '30d' else 0.05

        stock_map: Dict[str, dict] = {}
        for ranking in result.strategies:
            if not ranking.is_significant or ranking.time_dimension != dimension:
                continue
            detail = cls._details.get(ranking.strategy_id)
            if not detail or not detail.recent_signals:
                continue
            ic = max(ranking.ic, 0.0)  # 負 IC 不貢獻加權（避免 ic_sum 趨零爆炸）
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

        signals = []
        for s in stock_map.values():
            if s['trigger_count'] < 2:
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
        return signals[:30]

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
            df_dim = cls._compute_forward_returns(df_base, dim['forward_days'], dim['threshold_low'])
            logger.info(f"[AlphaMiner] 開始訓練 {dim['key']} 維度（{n_combos} 組）")

            for i, factors in enumerate(FACTOR_COMBINATIONS):
                strategy_name = " + ".join(FACTOR_LABELS.get(f, f) for f in factors)
                _write_progress({
                    "current": completed, "total": n_total,
                    "percent": round(completed / n_total * 100),
                    "current_dim": dim['key'], "current_strategy": strategy_name,
                })
                logger.info(f"[AlphaMiner] [{dim['key']}] {i+1}/{n_combos}: {factors}")
                ranking, detail = cls._train_one(df_dim, factors, n_combos, train_end, test_start, dim)
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
            bonferroni_threshold=round(0.05 / n_combos, 6),
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
        cutoff = (date.today() - timedelta(days=365 * 2)).isoformat()
        cols = ", ".join(_LOAD_COLS)
        sql = f"SELECT {cols} FROM stock_features WHERE date >= '{cutoff}'"
        df = pd.read_sql(sql, db.bind)
        if df.empty:
            return df
        df['date'] = pd.to_datetime(df['date'])
        return df

    # ─── 特徵工程 ──────────────────────────────────────────────────────────────
    @classmethod
    def _compute_forward_returns(cls, df: pd.DataFrame, forward_days: int, threshold: float) -> pd.DataFrame:
        df = df.sort_values(['stock_id', 'date']).copy()
        df['forward_close'] = df.groupby('stock_id')['close'].shift(-forward_days)
        close = df['close'].replace(0, np.nan)
        df['forward_return'] = (df['forward_close'] - close) / close
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

        # IC：預測機率與實際報酬的 Spearman 相關
        actual_returns = test_df['forward_return'].values
        if len(prob_test) < 10:
            return None, None
        ic_val, p_val = stats.spearmanr(prob_test, actual_returns)
        ic = float(ic_val) if not np.isnan(ic_val) else 0.0
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
        # Top 20% 作為訊號門檻
        threshold = np.percentile(prob, 80)
        mask = prob >= threshold

        result: List[RecentAlphaSignal] = []
        for i, (_, row) in enumerate(recent[mask].head(50).iterrows()):
            stock_id = str(row['stock_id'])
            name = stock_id
            if twstock:
                try:
                    info = twstock.codes.get(stock_id)
                    if info:
                        name = info.name
                except Exception:
                    pass
            result.append(RecentAlphaSignal(
                stock_id=stock_id,
                stock_name=name,
                signal_date=latest_date.strftime('%Y-%m-%d'),
                predicted_prob=round(float(prob[mask][i]), 3),
                trigger_factors=factors,
            ))
        return result

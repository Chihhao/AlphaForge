"""
BacktestService — 全市場技術訊號勝率統計
Phase 2 of Alpha Miner: 從 stock_prices 計算技術指標後偵測歷史訊號，統計前向報酬
掃描範圍：全市場所有股票（不限基本面條件）
"""
from __future__ import annotations

from datetime import date
from typing import Optional

import pandas as pd
from sqlalchemy.orm import Session

from app.db.database import engine

from app.models.stock_price import StockPrice
from app.services.indicator_service import IndicatorService
from app.schemas.market import AlphaStats, EquityCurvePoint, RecentSignal

# 模組層級快取：每日刷新一次
_cache: Optional[AlphaStats] = None
_cache_date: Optional[date] = None


def _get_stock_name(stock_id: str) -> str:
    try:
        import twstock
        info = twstock.codes.get(stock_id)
        if info:
            return info.name
    except Exception:
        pass
    return f"股票 {stock_id}"


class BacktestService:
    """全市場超賣反彈訊號回測服務（向量化運算，從 stock_prices 計算指標）"""

    BIAS_OVERSOLD = -5.0     # 前日 bias20 < -5（超賣門檻）
    BIAS_BULL = 0.0           # 當日 bias20 >= 0（回歸均線）
    VOL_RATIO_MIN = 1.5       # 量比 >= 1.5（放量確認）
    FORWARD_1D = 1
    FORWARD_10D = 10

    # 使用近 3 年資料
    HISTORY_YEARS = 3

    @staticmethod
    def run_af_choice_backtest(db: Session) -> AlphaStats:
        global _cache, _cache_date
        today = date.today()
        if _cache is not None and _cache_date == today:
            return _cache
        result = BacktestService._compute(db)
        _cache = result
        _cache_date = today
        return result

    @staticmethod
    def _compute(db: Session) -> AlphaStats:
        import datetime

        # 1. 讀取全市場近 3 年歷史價格（不過濾股票）
        cutoff = date.today() - datetime.timedelta(days=BacktestService.HISTORY_YEARS * 365)
        price_query = db.query(
            StockPrice.stock_id, StockPrice.date,
            StockPrice.open, StockPrice.high,
            StockPrice.low, StockPrice.close, StockPrice.volume,
        ).filter(
            StockPrice.date >= cutoff,
        ).statement

        raw_df = pd.read_sql(price_query, engine)
        if raw_df.empty:
            return BacktestService._empty_stats()

        raw_df['date'] = pd.to_datetime(raw_df['date']).dt.date
        raw_df = raw_df.sort_values(['stock_id', 'date']).reset_index(drop=True)

        # 3. 計算技術指標（bias20、vol_ratio）
        raw_df['ma5_vol'] = raw_df.groupby('stock_id')['volume'].transform(
            lambda x: x.rolling(window=5, min_periods=1).mean()
        )
        df = IndicatorService.attach_indicators(raw_df)

        if 'bias20' not in df.columns:
            return BacktestService._empty_stats()

        # vol_ratio = 當日量 / 5日均量（attach_indicators 不計算此欄，手動補充）
        if 'vol_ratio' not in df.columns:
            vol_ma5 = df.groupby('stock_id')['volume'].transform(
                lambda x: x.rolling(window=5, min_periods=1).mean()
            )
            df['vol_ratio'] = df['volume'] / vol_ma5.replace(0, float('nan'))

        df = df.sort_values(['stock_id', 'date']).reset_index(drop=True)

        # 4. 偵測訊號：前日 bias20 < -10 → 當日 bias20 >= 0，且量比 >= 1.5
        df['prev_bias20'] = df.groupby('stock_id')['bias20'].shift(1)

        signal_mask = (
            df['prev_bias20'].notna() &
            df['bias20'].notna() &
            df['vol_ratio'].notna() &
            (df['prev_bias20'] < BacktestService.BIAS_OVERSOLD) &
            (df['bias20'] >= BacktestService.BIAS_BULL) &
            (df['vol_ratio'] >= BacktestService.VOL_RATIO_MIN)
        )

        signals_df = df[signal_mask][['stock_id', 'date', 'close']].copy()
        signals_df = signals_df.rename(columns={'date': 'signal_date', 'close': 'signal_close'})

        if signals_df.empty:
            return BacktestService._empty_stats()

        # 5. 用 merge 取前向收盤價（嚴格防前視偏差）
        #    建立 (stock_id, date) → (rank, close) 的基準表
        price_ref = df[['stock_id', 'date', 'close']].copy().reset_index(drop=True)
        price_ref['day_rank'] = price_ref.groupby('stock_id').cumcount()

        # 取 signal_date 的 day_rank
        signals_df = signals_df.reset_index(drop=True)
        signals_df = signals_df.merge(
            price_ref[['stock_id', 'date', 'day_rank']].rename(columns={'date': 'signal_date'}),
            on=['stock_id', 'signal_date'], how='left'
        )
        signals_df = signals_df.dropna(subset=['day_rank'])
        signals_df['day_rank'] = signals_df['day_rank'].astype(int)

        # 取 +1 和 +10 交易日的收盤價
        fwd1 = price_ref[['stock_id', 'day_rank', 'close']].copy()
        fwd1['day_rank'] -= BacktestService.FORWARD_1D
        fwd1 = fwd1.rename(columns={'close': 'close_1d'})

        fwd10 = price_ref[['stock_id', 'day_rank', 'close']].copy()
        fwd10['day_rank'] -= BacktestService.FORWARD_10D
        fwd10 = fwd10.rename(columns={'close': 'close_10d'})

        signals_df = signals_df.merge(fwd1, on=['stock_id', 'day_rank'], how='left')
        signals_df = signals_df.merge(fwd10, on=['stock_id', 'day_rank'], how='left')

        # 6. 計算報酬率
        signals_df['return_1d'] = (signals_df['close_1d'] - signals_df['signal_close']) / signals_df['signal_close']
        signals_df['return_10d'] = (signals_df['close_10d'] - signals_df['signal_close']) / signals_df['signal_close']

        total_signals = len(signals_df)
        valid_1d = signals_df['return_1d'].dropna()
        valid_10d = signals_df['return_10d'].dropna()

        win_rate_1d = float((valid_1d > 0).mean()) if len(valid_1d) > 0 else 0.0
        win_rate_10d = float((valid_10d > 0).mean()) if len(valid_10d) > 0 else 0.0

        if len(valid_10d) > 0:
            wins = valid_10d[valid_10d > 0]
            losses = valid_10d[valid_10d <= 0]
            avg_win = float(wins.mean()) if len(wins) > 0 else 0.0
            avg_loss = float(losses.mean()) if len(losses) > 0 else 0.0
            expectancy = avg_win * win_rate_10d + avg_loss * (1 - win_rate_10d)
        else:
            expectancy = 0.0

        # 7. 累積報酬曲線（等權不複利：每筆固定投入 1 元，累加損益）
        curve_df = signals_df[signals_df['return_10d'].notna()].sort_values('signal_date').copy()
        equity_curve = []
        if not curve_df.empty:
            curve_df['cum_return'] = curve_df['return_10d'].cumsum()
            equity_curve = [
                EquityCurvePoint(date=str(r['signal_date']), cumulative_return=round(float(r['cum_return']), 4))
                for _, r in curve_df.iterrows()
            ]

        # 8. 近期 10 筆已結案訊號（return_10d 已有結果），另外附上最新待結案
        today_dt = date.today()
        completed = signals_df[signals_df['return_10d'].notna()].sort_values('signal_date', ascending=False).head(10)
        pending = signals_df[signals_df['return_10d'].isna()].sort_values('signal_date', ascending=False).head(3)
        recent_df = pd.concat([pending, completed]).sort_values('signal_date', ascending=False).head(10)

        recent_signals = []
        for _, row in recent_df.iterrows():
            if pd.isna(row['return_10d']):
                outcome = "pending"
            elif row['return_10d'] > 0:
                outcome = "win"
            else:
                outcome = "loss"

            recent_signals.append(RecentSignal(
                stock_id=row['stock_id'],
                stock_name=_get_stock_name(row['stock_id']),
                signal_date=str(row['signal_date']),
                return_1d=round(float(row['return_1d']) * 100, 2) if pd.notna(row['return_1d']) else None,
                return_10d=round(float(row['return_10d']) * 100, 2) if pd.notna(row['return_10d']) else None,
                outcome=outcome,
            ))

        data_date = str(max(signals_df['signal_date']))

        return AlphaStats(
            strategy_id="bias_reversal",
            strategy_name="超賣反彈（全市場）",
            win_rate_1d=round(win_rate_1d, 4),
            win_rate_10d=round(win_rate_10d, 4),
            expectancy=round(expectancy, 4),
            total_signals=total_signals,
            equity_curve=equity_curve,
            recent_signals=recent_signals,
            data_date=data_date,
        )

    @staticmethod
    def _empty_stats() -> AlphaStats:
        return AlphaStats(
            strategy_id="bias_reversal",
            strategy_name="超賣反彈（全市場）",
            win_rate_1d=0.0, win_rate_10d=0.0,
            expectancy=0.0, total_signals=0,
            equity_curve=[], recent_signals=[],
            data_date=str(date.today()),
        )

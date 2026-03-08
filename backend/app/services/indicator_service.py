import pandas as pd
import numpy as np
from typing import Optional, List, Dict, Any, Union
from datetime import datetime, timedelta

from app.logic.indicators.kd import calculate_kd
from app.services.stock_service import StockService
from app.schemas.indicator import KDValue, KDStatus

class IndicatorService:
    """
    向量化指標計算服務
    利用 Pandas 的矩陣運算能力，一次性、高效地為大量股票計算技術指標。
    """

    @staticmethod
    def calculate_ma_vec(df: pd.DataFrame, window: int, column: str = 'close') -> pd.Series:
        """向量化計算移動平均線 (MA)"""
        return df.groupby('stock_id')[column].transform(lambda x: x.rolling(window=window).mean())

    @staticmethod
    def calculate_bias_vec(df: pd.DataFrame, window: int, column: str = 'close') -> pd.Series:
        """向量化計算乖離率 (BIAS)"""
        ma = IndicatorService.calculate_ma_vec(df, window, column)
        return ((df[column] - ma) / ma) * 100

    @staticmethod
    def calculate_rsi_vec(df: pd.DataFrame, window: int = 14, column: str = 'close') -> pd.Series:
        """向量化計算 RSI (相對強弱指標)"""
        def _rsi_logic(s):
            delta = s.diff()
            up = delta.clip(lower=0)
            down = -1 * delta.clip(upper=0)
            # 使用 Wilder's Smoothing (EWM)
            ema_up = up.ewm(com=window-1, adjust=False).mean()
            ema_down = down.ewm(com=window-1, adjust=False).mean()
            rs = ema_up / ema_down
            return 100 - (100 / (1 + rs))

        return df.groupby('stock_id')[column].transform(_rsi_logic)

    @staticmethod
    def calculate_kd_vec(df: pd.DataFrame, n: int = 9, k_w: int = 3, d_w: int = 3) -> pd.DataFrame:
        """向量化計算 KD 指標"""
        # 注意：這裡預期 df 包含 'high', 'low', 'close'
        def _kd_logic(group):
            low_min = group['low'].rolling(window=n).min()
            high_max = group['high'].rolling(window=n).max()
            rsv = (group['close'] - low_min) / (high_max - low_min) * 100
            rsv = rsv.fillna(50)
            
            k = rsv.ewm(com=k_w-1, adjust=False).mean()
            d = k.ewm(com=d_w-1, adjust=False).mean()
            return pd.DataFrame({'k': k, 'd': d}, index=group.index)

        return df.groupby('stock_id', group_keys=False).apply(_kd_logic)

    @staticmethod
    def attach_indicators(df: pd.DataFrame) -> pd.DataFrame:
        """
        為包含多檔股票的原始數據一次性掛載所有常用指標。
        """
        # 確保順序正確
        df = df.sort_values(['stock_id', 'date']).copy()
        
        # 轉小寫以統一處理
        df.columns = [c.lower() for c in df.columns]
        # 處理中文列名相容性
        name_map = {'收盤': 'close', '最高': 'high', '最低': 'low', '開盤': 'open', '成交量': 'volume'}
        df = df.rename(columns={k: v for k, v in name_map.items() if k in df.columns})

        df['ma20'] = IndicatorService.calculate_ma_vec(df, 20)
        df['bias20'] = IndicatorService.calculate_bias_vec(df, 20)
        df['rsi14'] = IndicatorService.calculate_rsi_vec(df, 14)
        
        kd = IndicatorService.calculate_kd_vec(df)
        df['k'] = kd['k']
        df['d'] = kd['d']
        
        return df

    # --- 以下為向下相容的原有方法 (單檔查詢) ---

    @staticmethod
    def get_kd_indicator(stock_id: str, days: int = 30) -> List[KDValue]:
        """取得指定股票的 KD 指標數據 (單檔向後相容)"""
        df = StockService.get_kline_data(stock_id, period="3mo")
        if df is None or df.empty: return []
        
        # 確保有 date 欄位 (從 index 轉換)
        df = df.reset_index()
        # 處理 yfinance 或 db 轉換出來的 index 名稱
        if 'Date' in df.columns:
            df = df.rename(columns={'Date': 'date'})
        elif 'index' in df.columns:
            df = df.rename(columns={'index': 'date'})
            
        df['stock_id'] = stock_id
        processed = IndicatorService.attach_indicators(df)
        recent = processed.tail(days)
        
        return [
            KDValue(
                timestamp=row['date'] if isinstance(row['date'], datetime) else pd.to_datetime(row['date']),
                k=round(float(row['k']), 2),
                d=round(float(row['d']), 2),
                rsv=round(float(row.get('rsv', 0)), 2) # 若需要 RSV 需在 vec 中也回傳
            ) for _, row in recent.iterrows() if not pd.isna(row['k'])
        ]

    @staticmethod
    def get_current_kd_status(stock_id: str) -> Optional[KDStatus]:
        """取得當前的 KD 狀態與訊號 (單檔向後相容)"""
        kd_history = IndicatorService.get_kd_indicator(stock_id, days=5)
        if not kd_history or len(kd_history) < 2: return None
            
        latest, prev = kd_history[-1], kd_history[-2]
        status = "中性"
        if latest.k > 80: status = "超買 (過熱)"
        elif latest.k < 20: status = "超賣 (低估)"
            
        signal = None
        if prev.k <= prev.d and latest.k > latest.d: signal = "黃金交叉"
        elif prev.k >= prev.d and latest.k < latest.d: signal = "死亡交叉"
            
        return KDStatus(k=latest.k, d=latest.d, status=status, signal=signal)

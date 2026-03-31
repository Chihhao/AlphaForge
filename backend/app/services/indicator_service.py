import pandas as pd
import numpy as np
from typing import Optional, List, Dict, Any, Union
from datetime import datetime, timedelta

from app.services.stock_service import StockService
from app.schemas.indicator import KDValue, KDStatus

class IndicatorService:
    """
    向量化指標計算服務
    利用 Pandas 的矩陣運算能力，一次性、高效地為大量股票計算技術指標。
    """

    @staticmethod
    def calculate_ema_vec(df: pd.DataFrame, window: int, column: str = 'close') -> pd.Series:
        """向量化計算指數移動平均線 (EMA)"""
        return df.groupby('stock_id')[column].transform(lambda x: x.ewm(span=window, adjust=False).mean())

    @staticmethod
    def calculate_ma_vec(df: pd.DataFrame, window: int, column: str = 'close') -> pd.Series:
        """向量化計算簡單移動平均線 (SMA)"""
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
            # 使用 Wilder's Smoothing (EWM) - com = window - 1
            ema_up = up.ewm(com=window-1, adjust=False).mean()
            ema_down = down.ewm(com=window-1, adjust=False).mean()
            rs = ema_up / ema_down
            return 100 - (100 / (1 + rs))

        return df.groupby('stock_id')[column].transform(_rsi_logic)

    @staticmethod
    def calculate_kd_vec(df: pd.DataFrame, n: int = 9, k_w: int = 3, d_w: int = 3) -> pd.DataFrame:
        """向量化計算 KD 指標，對齊 ECF/台股標準 (1/3 權重)"""
        def _kd_logic(group):
            low_min = group['low'].rolling(window=n).min()
            high_max = group['high'].rolling(window=n).max()
            denominator = high_max - low_min
            rsv = (group['close'] - low_min) / denominator * 100
            rsv = rsv.fillna(50)
            
            # 使用 com=2 等同於 1/3 alpha (1 / (1+2))
            k = rsv.ewm(com=k_w-1, adjust=False).mean()
            # 初始值校正 (ECF 預設 50) 
            d = k.ewm(com=d_w-1, adjust=False).mean()
            return pd.DataFrame({'k': k, 'd': d, 'rsv': rsv}, index=group.index)

        return df.groupby('stock_id', group_keys=False).apply(_kd_logic)

    @staticmethod
    def calculate_macd_vec(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
        """向量化計算 MACD 指標"""
        def _macd_logic(group):
            ema_fast = group['close'].ewm(span=fast, adjust=False).mean()
            ema_slow = group['close'].ewm(span=slow, adjust=False).mean()
            dif = ema_fast - ema_slow
            dea = dif.ewm(span=signal, adjust=False).mean()
            osc = (dif - dea) * 2  # 台股習慣乘以 2
            return pd.DataFrame({'dif': dif, 'macd_dea': dea, 'macd_osc': osc}, index=group.index)

        return df.groupby('stock_id', group_keys=False).apply(_macd_logic)

    @staticmethod
    def calculate_bollinger_vec(df: pd.DataFrame, window: int = 20, num_std: int = 2) -> pd.DataFrame:
        """向量化計算布林通道"""
        def _bb_logic(group):
            ma = group['close'].rolling(window=window).mean()
            std = group['close'].rolling(window=window).std()
            upper = ma + (num_std * std)
            lower = ma - (num_std * std)
            return pd.DataFrame({'bb_upper': upper, 'bb_middle': ma, 'bb_lower': lower}, index=group.index)

        return df.groupby('stock_id', group_keys=False).apply(_bb_logic)

    @staticmethod
    def calculate_atr_vec(df: pd.DataFrame, window: int = 20) -> pd.Series:
        """向量化計算 Average True Range (ATR)"""
        df = df.sort_values(['stock_id', 'date'])
        prev_close = df.groupby('stock_id')['close'].shift(1)
        high_low = df['high'] - df['low']
        high_close = (df['high'] - prev_close).abs()
        low_close = (df['low'] - prev_close).abs()
        tr = pd.DataFrame({
            'hl': high_low, 'hc': high_close, 'lc': low_close
        }).max(axis=1)
        atr = tr.groupby(df['stock_id']).transform(lambda x: x.rolling(window).mean())
        return atr

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

        # MA
        for p in [5, 10, 20, 60]:
            df[f'ma{p}'] = IndicatorService.calculate_ma_vec(df, p)
        
        # BIAS & RSI
        df['bias20'] = IndicatorService.calculate_bias_vec(df, 20)
        df['rsi14'] = IndicatorService.calculate_rsi_vec(df, 14)
        
        # KD
        kd = IndicatorService.calculate_kd_vec(df)
        df['k'] = kd['k']
        df['d'] = kd['d']
        df['rsv'] = kd['rsv']
        
        # MACD
        macd = IndicatorService.calculate_macd_vec(df)
        df['macd_dif'] = macd['dif']
        df['macd_dea'] = macd['macd_dea']
        df['macd_osc'] = macd['macd_osc']
        
        # Bollinger
        bb = IndicatorService.calculate_bollinger_vec(df)
        df['bb_upper'] = bb['bb_upper']
        df['bb_middle'] = bb['bb_middle']
        df['bb_lower'] = bb['bb_lower']
        
        return df

    # --- 以下為向下相容的原有方法 (單檔查詢) ---

    @staticmethod
    def get_kd_indicator(stock_id: str, days: int = 30) -> List[KDValue]:
        """取得指定股票的 KD 指標數據 (單檔向後相容)"""
        # 為了計算準確，我們需要抓取更多歷史數據 (例如 3 個月)
        df = StockService.get_kline_data(stock_id, period="6mo")
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
                rsv=round(float(row['rsv']), 2) 
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

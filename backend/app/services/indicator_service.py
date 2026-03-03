import pandas as pd
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta

from app.logic.indicators.kd import calculate_kd
from app.services.stock_service import StockService
from app.schemas.indicator import KDValue, KDStatus

class IndicatorService:
    """指標計算服務"""

    @staticmethod
    def get_kd_indicator(stock_id: str, days: int = 30) -> List[KDValue]:
        """
        取得指定股票的 KD 指標數據
        """
        # 抓取 K 線數據，為了計算 KD，至少需要抓取 比目標天數更多的數據以進行平滑
        # 例如要顯示 30 天，建議抓取 60 天
        fetch_period = "3mo" # 抓取 3 個月確保數據充足
        
        df = StockService.get_kline_data(stock_id, period=fetch_period)
        if df is None or df.empty:
            return []
            
        # 將中文列名轉回英文以符合 calculate_kd 的要求
        df_en = df.rename(columns={
            '開盤': 'Open',
            '最高': 'High',
            '最低': 'Low',
            '收盤': 'Close',
            '成交量': 'Volume'
        })
        
        # 計算 KD
        result_df = calculate_kd(df_en)
        
        # 取得最近 N 天的結果
        recent_df = result_df.tail(days)
        
        kd_values = []
        for index, row in recent_df.iterrows():
            if pd.isna(row['K']) or pd.isna(row['D']):
                continue
            kd_values.append(KDValue(
                timestamp=index,
                k=round(float(row['K']), 2),
                d=round(float(row['D']), 2),
                rsv=round(float(row['RSV']), 2)
            ))
            
        return kd_values

    @staticmethod
    def get_current_kd_status(stock_id: str) -> Optional[KDStatus]:
        """
        取得當前的 KD 狀態與訊號
        """
        kd_history = IndicatorService.get_kd_indicator(stock_id, days=5)
        if not kd_history or len(kd_history) < 2:
            return None
            
        latest = kd_history[-1]
        prev = kd_history[-2]
        
        # 判定狀態
        status = "中性"
        if latest.k > 80:
            status = "超買 (過熱)"
        elif latest.k < 20:
            status = "超賣 (低估)"
            
        # 判定訊號
        signal = None
        # 黃金交叉: K線從下方往上突破 D線
        if prev.k <= prev.d and latest.k > latest.d:
            signal = "黃金交叉"
        # 死亡交叉: K線從上方往下突破 D線
        elif prev.k >= prev.d and latest.k < latest.d:
            signal = "死亡交叉"
            
        return KDStatus(
            k=latest.k,
            d=latest.d,
            status=status,
            signal=signal
        )

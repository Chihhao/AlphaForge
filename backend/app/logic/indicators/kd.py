import pandas as pd
import numpy as np
from typing import Tuple

def calculate_kd(df: pd.DataFrame, n: int = 9, k_period: int = 3, d_period: int = 3) -> pd.DataFrame:
    """
    計算 KD 指標 (Stochastic Oscillator)
    
    Args:
        df: 包含 'High', 'Low', 'Close' 欄位的 pandas DataFrame
        n: RSV 的回顧週期 (預設為 9)
        k_period: K 值的平滑權重 (預設為 3)
        d_period: D 值的平滑權重 (預設為 3)
        
    Returns:
        包含 'K', 'D' 欄位的 DataFrame
    """
    # 1. 計算 n 日內的最高與最低價
    # window = n, min_periods = n 確保足夠數據才計算
    low_n = df['Low'].rolling(window=n).min()
    high_n = df['High'].rolling(window=n).max()
    
    # 2. 計算 RSV (Raw Stochastic Value)
    # 避免分母為 0 (平盤情況)
    denominator = high_n - low_n
    rsv = (df['Close'] - low_n) / denominator * 100
    rsv = rsv.fillna(50) # 如果平盤則預設在 50
    
    # 3. 遞迴計算 K 與 D
    # 初始值通常約定為 50
    k_values = []
    d_values = []
    
    current_k = 50.0
    current_d = 50.0
    
    # 權重係數 (1/3 與 2/3)
    k_weight = 1.0 / k_period
    d_weight = 1.0 / d_period
    
    for i in range(len(df)):
        # 從第 n 個數據開始計算，之前的保留為 50 或 NaN
        if i < n - 1:
            k_values.append(np.nan)
            d_values.append(np.nan)
            continue
            
        # K = 1/3 * 今日RSV + 2/3 * 昨日K
        current_k = k_weight * rsv.iloc[i] + (1 - k_weight) * current_k
        k_values.append(current_k)
        
        # D = 1/3 * 今日K + 2/3 * 昨日D
        current_d = d_weight * current_k + (1 - d_weight) * current_d
        d_values.append(current_d)
        
    df = df.copy()
    df['RSV'] = rsv
    df['K'] = k_values
    df['D'] = d_values
    
    return df

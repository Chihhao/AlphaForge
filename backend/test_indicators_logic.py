import sys
import os
import pandas as pd
import numpy as np

# 加入專案路徑
sys.path.append(os.path.abspath(os.path.join(os.getcwd(), 'backend')))

from app.services.indicator_service import IndicatorService

def test_indicators():
    # 建立模擬數據
    data = {
        'date': pd.date_range(start='2024-01-01', periods=100),
        'stock_id': ['2330'] * 100,
        'open': np.random.uniform(500, 600, 100),
        'high': np.random.uniform(600, 650, 100),
        'low': np.random.uniform(450, 500, 100),
        'close': np.random.uniform(500, 600, 100),
        'volume': np.random.uniform(10000, 50000, 100)
    }
    df = pd.DataFrame(data)
    
    print("Testing attach_indicators...")
    processed_df = IndicatorService.attach_indicators(df)
    
    print("\nColumns in processed_df:")
    print(processed_df.columns.tolist())
    
    # 檢查最後幾筆數據
    print("\nLatest 5 rows of indicators:")
    cols_to_show = ['date', 'close', 'ma5', 'ma20', 'k', 'd', 'macd_osc', 'bb_upper']
    print(processed_df[cols_to_show].tail())
    
    # 檢查有無 NaN (排除起始點)
    nan_counts = processed_df.tail(20).isna().sum()
    print("\nNaN counts in latest 20 rows:")
    print(nan_counts[nan_counts > 0])

if __name__ == "__main__":
    test_indicators()

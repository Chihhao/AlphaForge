import sys
import os

from app.services.indicator_service import IndicatorService
from app.services.stock_service import StockService

def debug():
    df = StockService.get_kline_data("3711", period="3mo")
    print("DataFrame shape:", df.shape)
    kd_vals = IndicatorService.get_kd_indicator("3711", days=5)
    print("KD Values:", len(kd_vals))
    for kv in kd_vals:
        print(kv)

if __name__ == "__main__":
    debug()

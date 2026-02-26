import yfinance as yf
import pandas as pd
from FinMind.data import DataLoader

def main():
    print("=== 測試資料源 (Mac M1 Compatible) ===")
    
    # 1. 測試 yfinance (適合 K 線圖歷史資料)
    # 注意：台股代號在 Yahoo Finance 需加上 .TW (上市) 或 .TWO (上櫃)
    target_stock = "2330.TW"
    print(f"\n[1] yfinance - 取得 {target_stock} 近 5 日股價")
    
    try:
        stock = yf.Ticker(target_stock)
        hist = stock.history(period="5d")
        
        if not hist.empty:
            # 顯示日期、開盤、最高、最低、收盤、成交量
            print(hist[['Open', 'High', 'Low', 'Close', 'Volume']])
        else:
            print("警告: 抓取不到資料，可能是網路問題或代號錯誤")
    except Exception as e:
        print(f"yfinance 錯誤: {e}")

    # 2. 測試 FinMind DataLoader (台股歷史日K線資料)
    print(f"\n[2] FinMind - 取得 2330 歷史資料")
    
    try:
        loader = DataLoader()
        df = loader.taiwan_stock_daily(
            stock_id="2330",
            start_date="2024-01-01"
        )
        if not df.empty:
            print(df.head())
        else:
            print("FinMind 未回傳資料。")
    except Exception as e:
        print(f"FinMind 執行錯誤: {e}")

if __name__ == "__main__":
    main()
import yfinance as yf
import pandas as pd

# 抓取南亞科 1分K
stock = yf.Ticker("2408.TW")
hist = stock.history(period="1d", interval="1m", auto_adjust=False)

print(f"Total rows: {len(hist)}")
zero_vol = hist[hist['Volume'] == 0]
print(f"Rows with Volume == 0: {len(zero_vol)}")
if not zero_vol.empty:
    print("Example of Volume == 0 rows:")
    print(zero_vol[['Open', 'High', 'Low', 'Close', 'Volume']].head())

# Check for time gaps
hist['time_diff'] = hist.index.to_series().diff().dt.total_seconds()
gaps = hist[hist['time_diff'] > 60]
if not gaps.empty:
    print(f"Time gaps found (> 60s): {len(gaps)}")
    print(gaps[['time_diff']].head())

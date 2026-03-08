import yfinance as yf
import pandas as pd

stock = yf.Ticker("2408.TW")
hist = stock.history(period="5d", interval="1m", auto_adjust=False)

print(f"Total rows: {len(hist)}")
zero_vol = hist[hist['Volume'] == 0]
print(f"Rows with Volume == 0: {len(zero_vol)}")

# Check for large time gaps
hist['time_diff'] = hist.index.to_series().diff().dt.total_seconds()
# 1 minute is 60s. Anything > 3600 (1 hour) is a major gap (overnight or midday missing)
big_gaps = hist[hist['time_diff'] > 300] # Gaps > 5 mins
print(f"Gaps > 5 mins found: {len(big_gaps)}")
if not big_gaps.empty:
    print(big_gaps[['time_diff']].head(10))

# Print first 5 rows
print("First 5 rows:")
print(hist[['Open', 'High', 'Low', 'Close', 'Volume']].head())

import yfinance as yf
import pandas as pd

stock = yf.Ticker("2408.TW")
hist = stock.history(period="5d", interval="15m", auto_adjust=False)

# 看一下 hist 包含了哪些天
days = pd.to_datetime(hist.index).date
unique_days = pd.Series(days).unique()
print(f"Data contains these days: {unique_days}")

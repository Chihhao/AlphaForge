import asyncio
from datetime import date
from app.services.market_data_crawler import MarketDataCrawler

print("Testing TWSE for 2026-03-06...")
df1 = MarketDataCrawler.fetch_twse_daily_closing(date(2026, 3, 6))
print(f"TWSE returned {len(df1)} rows")
if not df1.empty:
    print(df1.head())

print("\nTesting TPEx for 2026-03-06...")
df2 = MarketDataCrawler.fetch_tpex_daily_closing(date(2026, 3, 6))
print(f"TPEx returned {len(df2)} rows")
if not df2.empty:
    print(df2.head())

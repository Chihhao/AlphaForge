import asyncio
import pandas as pd
import time
from app.services.market_data_crawler import MarketDataCrawler
from app.services.screener_service import ScreenerService
from app.db.database import SessionLocal
from app.models.stock_price import StockPrice
from sqlalchemy import func

async def test_full_market_performance():
    print("=== Phase C: 終極量化引擎性能測試 ===")
    
    # 1. 檢查資料庫狀態
    db = SessionLocal()
    latest_date = db.query(func.max(StockPrice.date)).scalar()
    count = db.query(StockPrice).filter(StockPrice.date == latest_date).count()
    print(f"最新交易日: {latest_date}, 股票檔數: {count}")
    db.close()

    # 2. 測試向量化指標計算與篩選效能
    start_time = time.time()
    print("\n[1/2] 執行全市場策略掃描 (向量化運算)...")
    strategies = ScreenerService.get_screener_results()
    end_time = time.time()
    
    duration = end_time - start_time
    print(f"✅ 掃描完成！耗時: {duration:.2f} 秒")
    
    if not strategies:
        print("⚠️ 無法取得掃描結果，請檢查資料庫是否有足夠的歷史數據進行指標計算。")
    
    for s in strategies:
        print(f" - {s.name}: 發現 {len(s.stocks)} 檔符合條件 (顯示前 3 檔: {[st.symbol for st in s.stocks[:3]]})")

    # 3. 測試自動化管線 (同步 👉 掃描)
    print("\n[2/2] 測試全自動管線 (同步 👉 掃描)...")
    # 注意：sync_daily_market_data 是同步方法
    MarketDataCrawler.sync_daily_market_data(target_date=latest_date)
    
    print("\n=== 測試結束 ===")

if __name__ == "__main__":
    asyncio.run(test_full_market_performance())

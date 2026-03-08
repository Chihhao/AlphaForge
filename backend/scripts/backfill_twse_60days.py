import os
import sys
import time
from datetime import datetime, timedelta
import pandas as pd

# 加入 backend 目錄到 sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.market_data_crawler import MarketDataCrawler
from app.services.system_logger import SystemLogger
from app.models.stock_price import StockPrice
from app.db.database import SessionLocal

def backfill_history(days: int = 60):
    """回補過去 N 個有效交易日的收盤行情"""
    print(f"🚀 開始回補過去 {days} 個交易日的行情資料...")
    print(f"⚠️ 為了防止被證交所阻擋，每次請求後會自動暫停 4 秒。請耐心等候大約 {(days * 4) // 60} 分鐘。")
    print("-" * 50)
    
    db = SessionLocal()
    
    # 從昨天開始算
    current_date = datetime.now().date() - timedelta(days=1)
    valid_days_fetched = 0
    days_checked = 0
    
    try:
        while valid_days_fetched < days and days_checked < 100:  # 最多往前推 100 天找 60 個交易日
            days_checked += 1
            
            # 跳過週末
            if current_date.weekday() in [5, 6]:
                current_date -= timedelta(days=1)
                continue
                
            date_str = current_date.strftime('%Y-%m-%d')
            
            # 智慧跳過：檢查 DB 中該日是否已經有資料 (大於 100 筆就算有)
            existing_count = db.query(StockPrice).filter(StockPrice.date == current_date).count()
            if existing_count > 100:
                print(f"⏭️  [{valid_days_fetched+1}/{days}] {date_str} DB 已有 {existing_count} 筆記錄，自動跳過...")
                valid_days_fetched += 1
                current_date -= timedelta(days=1)
                continue
            
            print(f"📥 [{valid_days_fetched+1}/{days}] 正在下載 {date_str} 資料...", end="", flush=True)
            
            try:
                # 抓取 TWSE
                twse_df = MarketDataCrawler.fetch_twse_daily_closing(current_date)
                time.sleep(2)  # 抓完上市停 2 秒
                
                # 抓取 TPEx
                tpex_df = MarketDataCrawler.fetch_tpex_daily_closing(current_date)
                time.sleep(2)  # 抓完上櫃停 2 秒
                
                total_fetched = len(twse_df) + len(tpex_df)
                
                if total_fetched == 0:
                    print(f" ⚠️ 無資料 (可能為國定假日，跳過)")
                    # 這天不算有效交易日，不增加 valid_days_fetched，但往前推一天
                    current_date -= timedelta(days=1)
                    continue
                    
                # 合併資料並準備寫入
                combined_df = pd.concat([twse_df, tpex_df], ignore_index=True)
                
                # 確保不重複插入
                existing_records = db.query(StockPrice.stock_id).filter(StockPrice.date == current_date).all()
                existing_ids = {r[0] for r in existing_records}
                
                new_records = []
                for _, row in combined_df.iterrows():
                    if row['stock_id'] not in existing_ids:
                        new_records.append(StockPrice(
                            stock_id=row['stock_id'],
                            date=current_date,
                            open=row['open'],
                            high=row['high'],
                            low=row['low'],
                            close=row['close'],
                            adj_close=row['close'],  # 預設同收盤價
                            volume=row['volume']
                        ))
                
                if new_records:
                    db.bulk_save_objects(new_records)
                    db.commit()
                    print(f" ✅ 成功寫入 {len(new_records)} 筆")
                else:
                    print(f" ⚠️ 無新資料寫入 (可能已存在)")
                
                valid_days_fetched += 1
                
            except Exception as e:
                print(f" ❌ 發生錯誤: {e}")
                # 發生錯誤時仍然睡一下，避免頻繁 retry 被鎖
                time.sleep(5)
                
            finally:
                current_date -= timedelta(days=1)
                
    except KeyboardInterrupt:
        print("\n🛑 使用者強制中斷執行。資料庫已保留之前下載的資料。")
    finally:
        db.close()
        print("-" * 50)
        print(f"🎉 歷史資料回補完成！總共補齊了 {valid_days_fetched} 個交易日的資料。")
        print("💡 現在您可以將 ScreenerService 切換回極速的『向量化計算模式』了！")

if __name__ == "__main__":
    backfill_history(60)

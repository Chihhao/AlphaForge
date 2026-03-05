import yfinance as yf
import pandas as pd
import twstock
from datetime import datetime, date, timedelta
from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.stock_price import StockPrice
from app.db.database import SessionLocal


class StockSyncService:
    """股市數據同步服務"""

    @staticmethod
    def get_all_stock_ids() -> List[str]:
        """獲取所有台股代號（包含加權指數、上市與上櫃股票）"""
        all_codes = twstock.codes
        # 只取股票類型，排除認購售權證等 (通常股票代號是 4 位或 6 位數字)
        stock_ids = [
            code for code, info in all_codes.items() 
            if info.type == '股票' and len(code) >= 2
        ]
        # 添加加權指數
        if "^TWII" not in stock_ids:
            stock_ids.insert(0, "^TWII")
        return stock_ids

    @staticmethod
    def sync_stock_data(db: Session, stock_id: str, days: int = 365) -> bool:
        """
        同步特定股票的數據到資料庫
        
        Args:
            db: 資料庫會話
            stock_id: 股票代號，如 "2330"
            days: 抓取的歷史天數
        """
        try:
            ticker_symbol = f"{stock_id}.TW" if not stock_id.startswith("^") else stock_id
            
            # 檢查資料庫中最晚的一筆資料日期
            last_date = db.query(func.max(StockPrice.date)).filter(
                StockPrice.stock_id == stock_id
            ).scalar()

            # 設定抓取的起始時間
            if last_date:
                start_date = last_date + timedelta(days=1)
                # 如果已經是最新的（今天或昨天），跳過
                if start_date >= date.today():
                    return True
                period = None # 使用 start_date
            else:
                start_date = date.today() - timedelta(days=days)
                period = f"{days}d"

            # 抓取數據
            ticker = yf.Ticker(ticker_symbol)
            if last_date:
                df = ticker.history(start=start_date.isoformat(), end=None, auto_adjust=False)
            else:
                df = ticker.history(period="max" if days > 3650 else period, auto_adjust=False)

            if df.empty and not stock_id.startswith("^"):
                # 嘗試 OTC 市場 (上櫃)
                ticker_symbol = f"{stock_id}.TWO"
                ticker = yf.Ticker(ticker_symbol)
                if last_date:
                    df = ticker.history(start=start_date.isoformat(), end=None, auto_adjust=False)
                else:
                    df = ticker.history(period="max" if days > 3650 else period, auto_adjust=False)

            if df.empty:
                return False

            # 將 DataFrame 轉為模型對象並存入
            new_prices = []
            for timestamp, row in df.iterrows():
                # 轉換為 date 對象，並排除未來日期 (yfinance 有時會有預估數據)
                current_date = timestamp.date()
                if current_date > date.today():
                    continue
                
                # 檢查是否已存在（二次確認，避免 start_date 的重疊）
                if last_date and current_date <= last_date:
                    continue

                price_entry = StockPrice(
                    stock_id=stock_id,
                    date=current_date,
                    open=float(row['Open']),
                    high=float(row['High']),
                    low=float(row['Low']),
                    close=float(row['Close']),
                    adj_close=float(row['Adj Close']) if 'Adj Close' in row else float(row['Close']),
                    volume=int(row['Volume'])
                )
                new_prices.append(price_entry)

            if new_prices:
                db.bulk_save_objects(new_prices)
                db.commit()
                print(f"Synced {len(new_prices)} rows for {stock_id}")
            
            return True
        except Exception as e:
            db.rollback()
            print(f"Error syncing {stock_id}: {e}")
            return False

    @staticmethod
    def sync_all_stocks(batch_size: int = 50):
        """同步所有股票的最新數據"""
        stock_ids = StockSyncService.get_all_stock_ids()
        print(f"Starting sync for {len(stock_ids)} stocks...")
        
        db = SessionLocal()
        try:
            success_count = 0
            for i, stock_id in enumerate(stock_ids):
                if StockSyncService.sync_stock_data(db, stock_id, days=5): # 增量更新只需幾天
                    success_count += 1
                
                if (i + 1) % batch_size == 0:
                    print(f"Progress: {i+1}/{len(stock_ids)} stocks processed.")
            
            print(f"Sync complete. Success: {success_count}/{len(stock_ids)}")
        finally:
            db.close()

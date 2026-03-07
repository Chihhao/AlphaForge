import requests
import pandas as pd
from datetime import date, datetime
from typing import Optional, List, Dict, Any
import time

from app.models.stock_price import StockPrice
from app.db.database import SessionLocal
from app.services.system_logger import SystemLogger

class MarketDataCrawler:
    """台灣股市每日收盤行情爬蟲"""
    
    # TWSE API (證交所)
    # https://www.twse.com.tw/zh/API/ENews/index.html
    TWSE_MI_INDEX_URL = "https://www.twse.com.tw/exchangeReport/MI_INDEX"
    
    # TPEx API (櫃買中心)
    TPEX_AFTER_TRADING_URL = "https://www.tpex.org.tw/web/stock/aftertrading/daily_close_quotes/stk_quote_result.php"

    @staticmethod
    def _clean_numeric(val: Any) -> float:
        """清理數字字串 (移除逗號，處理 '--' 或空值)"""
        if pd.isna(val) or val is None:
            return 0.0
        
        val_str = str(val).strip().replace(',', '')
        if val_str in ['--', '---', 'X', '']:
            return 0.0
            
        try:
            return float(val_str)
        except ValueError:
            return 0.0

    @staticmethod
    def fetch_twse_daily_closing(target_date: date) -> pd.DataFrame:
        """
        抓取上市(TWSE)每日收盤行情資料
        
        Args:
            target_date: 欲抓取的日期
        Returns:
            DataFrame 包含當日所有上市股票收盤資料
        """
        # TWSE 參數格式：YYYYMMDD
        date_str = target_date.strftime("%Y%m%d")
        
        try:
            # 參數: response=json, date=YYYYMMDD, type=ALLBUT0999 (排除權證、牛熊證等)
            params = {
                "response": "json",
                "date": date_str,
                "type": "ALLBUT0999"
            }
            
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            }
            
            response = requests.get(MarketDataCrawler.TWSE_MI_INDEX_URL, params=params, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if "tables" in data:
                # 新版結構：{"tables": [{"title": "...", "fields": [...], "data": [...]}, ...]}
                for table in data["tables"]:
                    if "fields" in table and "證券代號" in table["fields"] and "收盤價" in table["fields"]:
                        target_fields = table["fields"]
                        target_table = table["data"]
                        break
            else:
                # 舊版結構處理 (備用)
                for key in data.keys():
                    if key.startswith('fields'):
                        num = key.replace('fields', '')
                        fields = data[key]
                        if '證券代號' in fields:
                            target_fields = fields
                            target_table = data.get(f'data{num}')
                            break
                        
            if not target_table or not target_fields:
                print(f"Could not find stock table in TWSE response for {date_str}")
                return pd.DataFrame()
                
            df = pd.DataFrame(target_table, columns=target_fields)
            
            # 過濾只保留普通股 (代號為四碼純數字)
            # 移除 ETF(00開頭)、特別股等
            df = df[df['證券代號'].str.match(r'^[1-9]\d{3}$', na=False)]
            
            # 標準化欄位名稱
            result_df = pd.DataFrame()
            result_df['stock_id'] = df['證券代號']
            result_df['stock_name'] = df['證券名稱']
            
            # 清理與轉換數值
            # 留意：證交所回傳的成交股數是「股」不是「張」，而 Yahoo 大多是「股」
            result_df['volume'] = df['成交股數'].apply(MarketDataCrawler._clean_numeric)
            result_df['open'] = df['開盤價'].apply(MarketDataCrawler._clean_numeric)
            result_df['high'] = df['最高價'].apply(MarketDataCrawler._clean_numeric)
            result_df['low'] = df['最低價'].apply(MarketDataCrawler._clean_numeric)
            result_df['close'] = df['收盤價'].apply(MarketDataCrawler._clean_numeric)
            
            # 過濾掉當天沒有交易（收盤價為0）的無效資料
            result_df = result_df[result_df['close'] > 0]
            
            return result_df
            
        except Exception as e:
            print(f"Error fetching TWSE data for {date_str}: {e}")
            return pd.DataFrame()

    @staticmethod
    def fetch_tpex_daily_closing(target_date: date) -> pd.DataFrame:
        """
        抓取上櫃(TPEx)每日收盤行情資料
        
        Args:
            target_date: 欲抓取的日期
        Returns:
            DataFrame 包含當日所有上櫃股票收盤資料
        """
        # TPEx 參數格式：民國年/MM/DD (如 113/05/20)
        roc_year = target_date.year - 1911
        date_str = f"{roc_year}/{target_date.strftime('%m/%d')}"
        
        try:
            params = {
                "l": "zh-tw",
                "d": date_str
            }
            
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            }
            
            response = requests.get(MarketDataCrawler.TPEX_AFTER_TRADING_URL, params=params, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            # TPEX 新版結構：{"tables": [{"title": "上櫃股票行情", "fields": [...], "aaData": [...]}, ...]}
            target_table = None
            target_fields = None
            
            if "tables" in data:
                for table in data["tables"]:
                    if "fields" in table and "代號" in table["fields"] and "收盤" in table["fields"]:
                        target_fields = table["fields"]
                        target_table = table.get("aaData") or table.get("data")
                        break
            elif "aaData" in data:
                # 舊版結構處理 (直接在根目錄)
                target_table = data["aaData"]
            
            if not target_table:
                print(f"No trading data found for TPEx on {date_str}")
                return pd.DataFrame()
                
            # TPEx 的 aaData 是一個 list of lists
            # 我們需要建立欄位對照表以確保對應正確
            df = pd.DataFrame(target_table)
            
            # 如果有欄位名稱，嘗試精確對應
            col_map = {}
            if target_fields:
                for i, field in enumerate(target_fields):
                    col_map[field] = i
            else:
                # 預設對應 (舊版常用索引)
                col_map = {"代號": 0, "名稱": 1, "收盤": 2, "開盤": 4, "最高": 5, "最低": 6, "成交股數": 8}
            
            # 標準化欄位名稱
            result_df = pd.DataFrame()
            result_df['stock_id'] = df[col_map["代號"]]
            result_df['stock_name'] = df[col_map["名稱"]]
            
            # 過濾只保留普通股 (代號為四碼純數字)
            result_df = result_df[result_df['stock_id'].str.match(r'^[1-9]\d{3}$', na=False)]
            
            # 清理與轉換數值
            result_df['close'] = df[col_map["收盤"]].apply(MarketDataCrawler._clean_numeric)
            result_df['open'] = df[col_map["開盤"]].apply(MarketDataCrawler._clean_numeric)
            result_df['high'] = df[col_map["最高"]].apply(MarketDataCrawler._clean_numeric)
            result_df['low'] = df[col_map["最低"]].apply(MarketDataCrawler._clean_numeric)
            result_df['volume'] = df[col_map["成交股數"]].apply(MarketDataCrawler._clean_numeric)
            
            # 過濾掉開盤價為 0 的無效資料 (可能當天暫停交易)
            result_df = result_df[result_df['open'] > 0]
            
            return result_df
            
        except Exception as e:
            print(f"Error fetching TPEx data for {date_str}: {e}")
            return pd.DataFrame()

    @staticmethod
    def sync_daily_market_data(target_date: Optional[date] = None) -> Dict[str, Any]:
        """
        主副程式：下載今日 TWSE 與 TPEx 資料並更新進入 Local DB。
        
        Returns:
            Dict containing stats about the sync process
        """
        if target_date is None:
            # 考慮台股收盤時間，如果在 15:00 以前呼叫，預設抓昨天的
            now = datetime.now()
            if now.hour < 14:
                # 簡單處理，實際可依據交易行事曆
                target_date = now.date() - pd.Timedelta(days=1)
                # 跳過週末
                if target_date.weekday() == 6: # Sunday
                    target_date = target_date - pd.Timedelta(days=2)
                elif target_date.weekday() == 5: # Saturday
                    target_date = target_date - pd.Timedelta(days=1)
            else:
                target_date = now.date()

        target_date_str = target_date.strftime('%Y-%m-%d')
        SystemLogger.info(f"開始同步台股收盤行情數據...", category="crawler")
        
        # 1. Fetch data
        SystemLogger.info(f"正在從證交所抓取上市數據...", category="crawler")
        twse_df = MarketDataCrawler.fetch_twse_daily_closing(target_date)
        time.sleep(2) # 友善爬蟲，延遲 2 秒
        
        SystemLogger.info(f"正在從櫃買中心抓取上櫃數據...", category="crawler")
        tpex_df = MarketDataCrawler.fetch_tpex_daily_closing(target_date)
        
        total_fetched = len(twse_df) + len(tpex_df)
        if total_fetched == 0:
            msg = f"未找到 {target_date_str} 的資料，今日可能非交易日或資料尚未發佈。"
            SystemLogger.warning(msg, category="crawler")
            return {
                "status": "warning", 
                "message": msg,
                "inserted": 0
            }
        
        SystemLogger.info(f"資料抓取成功：上市 {len(twse_df)} 檔，上櫃 {len(tpex_df)} 檔。", category="crawler")
            
        # 2. Combine data
        combined_df = pd.concat([twse_df, tpex_df], ignore_index=True)
        
        # 3. Save to database using bulk insert
        db = SessionLocal()
        inserted_count = 0
        skipped_count = 0
        
        try:
            SystemLogger.info(f"正在將資料寫入本地資料庫...", category="crawler")
            # Check existing to avoid duplicates
            existing_records = db.query(StockPrice.stock_id).filter(StockPrice.date == target_date).all()
            existing_ids = {r[0] for r in existing_records}
            
            new_records = []
            for _, row in combined_df.iterrows():
                stock_id = str(row['stock_id'])
                
                if stock_id in existing_ids:
                    skipped_count += 1
                    continue
                    
                new_records.append(StockPrice(
                    stock_id=stock_id,
                    date=target_date,
                    open=row['open'],
                    high=row['high'],
                    low=row['low'],
                    close=row['close'],
                    adj_close=row['close'], # 目前沒有還原權息資料，先填入收盤價
                    volume=int(row['volume'])
                ))
            
            if new_records:
                # Chunk insert for large datasets
                chunk_size = 500
                for i in range(0, len(new_records), chunk_size):
                    chunk = new_records[i:i + chunk_size]
                    db.bulk_save_objects(chunk)
                    db.commit()
                    inserted_count += len(chunk)
                    
            success_msg = f"行情數據同步完成：新增 {inserted_count} 筆，跳過 {skipped_count} 筆。"
            SystemLogger.success(success_msg, category="crawler")
            print(success_msg)
            
            return {
                "status": "success",
                "date": target_date_str,
                "total_twse": len(twse_df),
                "total_tpex": len(tpex_df),
                "inserted": inserted_count,
                "skipped": skipped_count
            }
            
        except Exception as e:
            db.rollback()
            err_msg = f"資料庫同步錯誤: {str(e)}"
            SystemLogger.error(err_msg, category="crawler")
            return {"status": "error", "message": err_msg}
        finally:
            db.close()

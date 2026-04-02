import yfinance as yf
import pandas as pd
import twstock
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta, date
from sqlalchemy.orm import Session
from sqlalchemy import select, and_

from app.schemas.stock import StockQuote
from app.models.user import Stock as StockModel
from app.models.stock_price import StockPrice
from app.models.stock_fundamental import StockFundamental
from app.db.database import SessionLocal


class StockService:
    """股票數據服務"""
    
    @staticmethod
    def search_stocks(query: str, limit: int = 20) -> List[Dict[str, Any]]:
        """
        搜尋股票（簡單模擬版本，實際應該查詢數據庫）
        """
        # 模擬常見台股數據
        stocks_db = [
            {"stock_id": "2330", "stock_name": "台積電", "market": "上市"},
            {"stock_id": "2454", "stock_name": "聯發科", "market": "上市"},
            {"stock_id": "3008", "stock_name": "瑞昱", "market": "上市"},
            {"stock_id": "2308", "stock_name": "台達電", "market": "上市"},
            {"stock_id": "3034", "stock_name": "聯詠", "market": "上市"},
            {"stock_id": "5483", "stock_name": "中美晶", "market": "上市"},
            {"stock_id": "6488", "stock_name": "嘉寶科", "market": "上市"},
            {"stock_id": "2603", "stock_name": "長榮", "market": "上市"},
            {"stock_id": "2618", "stock_name": "長榮海", "market": "上市"},
            {"stock_id": "2800", "stock_name": "巨大", "market": "上市"},
            {"stock_id": "3037", "stock_name": "欣興", "market": "上市"},
            {"stock_id": "3711", "stock_name": "日月光", "market": "上市"},
        ]

        query_lower = query.lower()
        results = [
            stock for stock in stocks_db
            if query_lower in stock["stock_id"].lower() or 
            query_lower in stock["stock_name"].lower()
        ]

        if not results and query.isdigit():
            stock_info = twstock.codes.get(query)
            cn_name = stock_info.name if stock_info else f"股票 {query}"
            market = stock_info.market if stock_info else "上市/上櫃"

            results.append({
                "stock_id": query,
                "stock_name": cn_name,
                "market": market
            })

        return results[:limit]

    @staticmethod
    def get_stock_quote(stock_id: str) -> Optional[StockQuote]:
        """
        取得股票最新報價
        """
        try:
            # Yahoo Finance 數據抓取
            ticker = f"{stock_id}.TW"
            stock = yf.Ticker(ticker)
            hist = stock.history(period="5d")

            if hist.empty:
                ticker = f"{stock_id}.TWO"
                stock = yf.Ticker(ticker)
                hist = stock.history(period="5d")

            if hist.empty:
                return None

            latest = hist.iloc[-1]
            volume = int(latest.get('Volume', 0))

            if len(hist) >= 2:
                prev_close = hist.iloc[-2]['Close']
                change_percent = ((latest['Close'] - prev_close) / prev_close * 100)
            else:
                change_percent = 0.0

            twstock_info = twstock.codes.get(stock_id)
            if twstock_info:
                stock_name = twstock_info.name
            else:
                # twstock 找不到時，從 DB 補查（涵蓋興櫃、新上市等）
                try:
                    db_temp = SessionLocal()
                    fundamental = db_temp.query(StockFundamental).filter(StockFundamental.stock_id == stock_id).first()
                    db_temp.close()
                    stock_name = fundamental.stock_name if fundamental and fundamental.stock_name else f"股票 {stock_id}"
                except Exception:
                    stock_name = f"股票 {stock_id}"

            # --- 整合基本面數據 ---
            # 先取 yfinance info（判斷是否為 ETF，並抓 ETF 專屬欄位）
            try:
                info = stock.info
            except Exception:
                info = {}

            is_etf = info.get("quoteType", "").upper() == "ETF"

            db = SessionLocal()
            fundamental_data = {}
            try:
                if is_etf:
                    # ETF：從 yfinance info 填入可用欄位
                    pe = info.get("trailingPE")
                    dy = info.get("dividendYield")  # yfinance 回傳百分比值（如 1.68 代表 1.68%）
                    ta = info.get("totalAssets")
                    ff = info.get("fundFamily")
                    fundamental_data = {
                        "pe_ratio": float(pe) if pe else None,
                        "yield_rate": float(dy) if dy else None,
                        "total_assets": float(ta) if ta else None,
                        "fund_family": ff if ff else None,
                        "fundamental_updated_at": datetime.utcnow(),
                    }
                else:
                    fundamental = db.query(StockFundamental).filter(StockFundamental.stock_id == stock_id).first()
                    if fundamental:
                        fundamental_data = {
                            "pe_ratio": fundamental.pe_ratio,
                            "pb_ratio": fundamental.pb_ratio,
                            "yield_rate": fundamental.yield_rate,
                            "roe": fundamental.roe_latest,
                            "last_revenue": fundamental.last_revenue,
                            "revenue_growth_yoy": fundamental.revenue_growth_yoy,
                            "last_eps": fundamental.eps_y1,
                            "fundamental_updated_at": fundamental.updated_at
                        }
            finally:
                db.close()

            return StockQuote(
                stock_id=stock_id,
                stock_name=stock_name,
                current_price=float(latest['Close']),
                open_price=float(latest['Open']),
                high_price=float(latest['High']),
                low_price=float(latest['Low']),
                volume=volume,
                change_percent=change_percent,
                timestamp=datetime.utcnow(),
                **fundamental_data # 注入基本面欄位
            )
        except Exception as e:
            print(f"Error fetching stock quote for {stock_id}: {e}")
            return None

    @staticmethod
    def get_kline_data(
        stock_id: str,
        period: str = "1y",
        interval: str = "1d"
    ) -> Optional[pd.DataFrame]:
        """
        取得 K 線數據

        Args:
            stock_id: 股票代號
            period: 時間週期，如 "1y", "3mo", "1d"
            interval: K 線間隔，如 "1d", "1h", "5m"

        """
        db = SessionLocal()
        
        # yfinance 支援的全部歷史資料參數為 'max'
        if period == "all":
            period = "max"

        try:
            # 0. 判斷是否為高頻即時數據 (分鐘/小時線)
            # 如果是 intraday 數據，跳過本地資料庫，直接從 yfinance 抓取
            is_intraday = interval.endswith('m') or interval.endswith('h')

            # 1. 如果不是高頻數據，優先從本地資料庫獲取
            if not is_intraday:
                query = db.query(StockPrice).filter(StockPrice.stock_id == stock_id)
                
                # 根據 period 估算起始日期 (簡單處理)
                days_map = {"1d": 1, "5d": 5, "1mo": 30, "3mo": 90, "6mo": 180, "1y": 365, "2y": 730, "3y": 1095, "5y": 1825, "10y": 3650, "max": 9999}
                days = days_map.get(period, 365)
                start_date = date.today() - timedelta(days=days)
                
                db_prices = query.filter(StockPrice.date >= start_date).order_by(StockPrice.date.asc()).all()
                
                # 如果本地資料充足 (例如最後一筆資料是昨天或今天)
                if db_prices:
                    last_db_date = db_prices[-1].date
                    first_db_date = db_prices[0].date
                    
                    # 允許最多 4 天差距，以涵蓋週末與連假（例如週一盤中，最後一筆為上週五）
                    is_recent = (date.today() - last_db_date).days <= 4
                    
                    # 由於交易日大約是日曆日的 5/7，我們檢查筆數是否足夠，或第一筆資料日期是否夠早
                    expected_trading_days = int(days * 0.6)
                    is_enough_data = (len(db_prices) >= expected_trading_days) or (first_db_date <= start_date + timedelta(days=7))
                    
                    if is_recent and is_enough_data:
                        # 轉換為 DataFrame
                        data = {
                            '開盤': [p.open for p in db_prices],
                            '最高': [p.high for p in db_prices],
                            '最低': [p.low for p in db_prices],
                            '收盤': [p.close for p in db_prices],
                            '成交量': [p.volume for p in db_prices]
                        }
                        index = pd.to_datetime([p.date for p in db_prices])
                        return pd.DataFrame(data, index=index)

            # 2. 如果本地資料不足或過時，從 yfinance 抓取並更新資料庫
            ticker_symbol = f"{stock_id}.TW"
            stock = yf.Ticker(ticker_symbol)
            # 抓取 period 數據
            hist = stock.history(period=period, interval=interval, auto_adjust=False)
            
            if hist.empty:
                # 嘗試 OTC
                ticker_symbol = f"{stock_id}.TWO"
                stock = yf.Ticker(ticker_symbol)
                hist = stock.history(period=period, interval=interval, auto_adjust=False)

            if hist.empty:
                return None

            # 異步/背景存儲新數據（這裡簡單同步存儲）
            new_prices = []
            for timestamp, row in hist.iterrows():
                curr_date = timestamp.date()
                if curr_date > date.today(): continue
                
                # 檢查是否已存在
                exists = db.query(StockPrice).filter(
                    and_(StockPrice.stock_id == stock_id, StockPrice.date == curr_date)
                ).first()
                
                if not exists:
                    new_prices.append(StockPrice(
                        stock_id=stock_id,
                        date=curr_date,
                        open=float(row['Open']),
                        high=float(row['High']),
                        low=float(row['Low']),
                        close=float(row['Close']),
                        adj_close=float(row['Adj Close']) if 'Adj Close' in row else float(row['Close']),
                        volume=int(row['Volume'])
                    ))
            
            if new_prices:
                db.bulk_save_objects(new_prices)
                db.commit()

            # 重新命名列為中文回傳
            hist = hist.rename(columns={
                'Open': '開盤',
                'High': '最高',
                'Low': '最低',
                'Close': '收盤',
                'Volume': '成交量'
            })
            return hist
        except Exception as e:
            print(f"Error in get_kline_data for {stock_id}: {e}")
            return None
        finally:
            db.close()

    @staticmethod
    def calculate_ma(prices: pd.Series, period: int = 20) -> pd.Series:
        """計算移動平均線"""
        return prices.rolling(window=period).mean()

    @staticmethod
    def calculate_rsi(prices: pd.Series, period: int = 14) -> pd.Series:
        """計算 RSI 指標"""
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi

    @staticmethod
    def calculate_bollinger_bands(
        prices: pd.Series,
        period: int = 20,
        std_dev: int = 2
    ) -> Dict[str, pd.Series]:
        """計算布林通道"""
        sma = prices.rolling(window=period).mean()
        std = prices.rolling(window=period).std()

        return {
            "upper": sma + (std * std_dev),
            "middle": sma,
            "lower": sma - (std * std_dev),
        }

    @staticmethod
    def calculate_bias(prices: pd.Series, period: int = 20) -> pd.Series:
        """計算乖離率 (Bias)"""
        ma = prices.rolling(window=period).mean()
        return (prices - ma) / ma * 100

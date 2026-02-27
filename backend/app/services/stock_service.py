import yfinance as yf
import pandas as pd
import twstock
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta

from app.schemas.stock import StockQuote


class StockService:
    """股票數據服務"""

    @staticmethod
    def search_stocks(query: str, limit: int = 20) -> List[Dict[str, Any]]:
        """
        搜尋股票（簡單模擬版本，實際應該查詢數據庫）

        Args:
            query: 搜尋關鍵字（股票代號或名稱）
            limit: 最多返回結果數

        Returns:
            股票列表
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

        # 過濾搜尋結果
        query_lower = query.lower()
        results = [
            stock for stock in stocks_db
            if query_lower in stock["stock_id"].lower() or 
            query_lower in stock["stock_name"].lower()
        ]

        if not results and query.isdigit():
            # If not found in the local list but looks like a stock code, return a generic result or twstock name
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

        Args:
            stock_id: 股票代號，如 "2330"

        Returns:
            股票報價信息，或 None 如果無法取得
        """
        try:
            # Yahoo Finance 台股格式：股票代號.TW
            ticker = f"{stock_id}.TW"
            stock = yf.Ticker(ticker)
            hist = stock.history(period="1d")

            if hist.empty:
                return None

            latest = hist.iloc[-1]

            # 計算成交量和漲跌幅
            volume = int(latest.get('Volume', 0))

            # 取得前一日數據計算漲跌幅
            hist_2d = stock.history(period="2d")
            if len(hist_2d) >= 2:
                prev_close = hist_2d.iloc[-2]['Close']
                change_percent = ((latest['Close'] - prev_close) / prev_close * 100)
            else:
                change_percent = 0.0

            # 股票名稱映射
            stock_names = {
                "2330": "台積電",
                "2454": "聯發科",
                "3008": "瑞昱",
                "2308": "台達電",
            }
            
            # 從 twstock 取得中文名稱，如果沒有就用預設映射或 yfinance 英文名
            twstock_info = twstock.codes.get(stock_id)
            if twstock_info:
                stock_name = twstock_info.name
            else:
                fetched_name = stock.info.get('shortName')
                stock_name = fetched_name if fetched_name else stock_names.get(stock_id, f"股票 {stock_id}")

            return StockQuote(
                stock_id=stock_id,
                stock_name=stock_name,
                current_price=float(latest['Close']),
                open_price=float(latest['Open']),
                high_price=float(latest['High']),
                low_price=float(latest['Low']),
                volume=volume,
                change_percent=change_percent,
                timestamp=datetime.utcnow()
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

        Returns:
            K 線 DataFrame，或 None 如果無法取得
        """
        try:
            ticker = f"{stock_id}.TW"
            stock = yf.Ticker(ticker)
            hist = stock.history(period=period, interval=interval)

            if hist.empty:
                return None

            # 重新命名列為中文，只重新命名需要的欄位
            hist = hist.rename(columns={
                'Open': '開盤',
                'High': '最高',
                'Low': '最低',
                'Close': '收盤',
                'Volume': '成交量'
            })
            return hist
        except Exception as e:
            print(f"Error fetching K-line data for {stock_id}: {e}")
            return None

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

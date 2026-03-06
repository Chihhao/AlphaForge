from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
import twstock

from app.schemas.market import RankingItem, MarketRankingResponse
from app.models.stock_price import StockPrice
from app.db.database import SessionLocal

class MarketService:
    """市場概況數據服務"""

    @staticmethod
    def get_market_rankings(limit: int = 5) -> MarketRankingResponse:
        """
        取得市場排行榜（漲幅、跌幅、成交量） - 即時行情版
        """
        pool_ids = [
            "2330", "2317", "2454", "2308", "2382", "2881", "2882", "2412", "2891", "2303",
            "2886", "2884", "1216", "2002", "2885", "3231", "2603", "2892", "3045", "5871",
            "2890", "2207", "3008", "2357", "2618", "2609", "3481", "2409", "3037", "3711"
        ]
        
        try:
            import yfinance as yf
            
            # 使用批次抓取以提高效率 (Yahoo Finance 支援一次查詢多個 Ticker)
            tickers = [f"{sid}.TW" for sid in pool_ids]
            # 抓取最近 2 天的半小時線或日線數據來計算漲跌
            data = yf.download(tickers, period="2d", group_by='ticker', progress=False, threads=True)
            
            items = []
            for sid in pool_ids:
                ticker = f"{sid}.TW"
                if ticker not in data.columns.levels[0]:
                    # 嘗試 OTC
                    ticker = f"{sid}.TWO"
                    if ticker not in data.columns.levels[0]:
                        continue
                
                stock_df = data[ticker].dropna()
                if len(stock_df) < 2:
                    continue
                
                today = stock_df.iloc[-1]
                yesterday = stock_df.iloc[-2]
                
                close_price = float(today['Close'])
                prev_close = float(yesterday['Close'])
                volume = int(today['Volume'])
                
                if prev_close > 0:
                    change_percent = ((close_price - prev_close) / prev_close) * 100
                else:
                    change_percent = 0.0
                
                # 獲取中文名稱
                info = twstock.codes.get(sid)
                name = info.name if info else f"股票 {sid}"
                
                items.append(RankingItem(
                    stock_id=sid,
                    stock_name=name,
                    price=round(close_price, 2),
                    change_percent=round(change_percent, 2),
                    volume=volume
                ))
            
            if not items:
                # 如果即時抓取失敗，回退到 DB (原本的邏輯)
                return MarketService._get_rankings_from_db(pool_ids, limit)
                
            # 排序
            top_gainers = sorted(items, key=lambda x: x.change_percent, reverse=True)[:limit]
            top_losers = sorted(items, key=lambda x: x.change_percent)[:limit]
            top_volume = sorted(items, key=lambda x: x.volume, reverse=True)[:limit]
            
            return MarketRankingResponse(
                top_gainers=top_gainers,
                top_losers=top_losers,
                top_volume=top_volume
            )
            
        except Exception as e:
            print(f"Error fetching real-time rankings: {e}")
            # 發生錯誤時嘗試從資料庫讀取備援數據
            return MarketService._get_rankings_from_db(pool_ids, limit)

    @staticmethod
    def _get_rankings_from_db(pool_ids: List[str], limit: int) -> MarketRankingResponse:
        """備援邏輯：從資料庫讀取最後一次同步的數據"""
        db = SessionLocal()
        try:
            # 1. 獲取最近兩個交易日 (根據加權指數判斷市場日期)
            latest_dates = db.query(StockPrice.date).filter(
                StockPrice.stock_id == "^TWII"
            ).order_by(StockPrice.date.desc()).limit(2).all()
            
            if not latest_dates or len(latest_dates) < 2:
                return MarketRankingResponse(top_gainers=[], top_losers=[], top_volume=[])
                
            today_date = latest_dates[0][0]
            yesterday_date = latest_dates[1][0]
            
            # 2. 取得名稱映射
            names = {}
            for sid in pool_ids:
                info = twstock.codes.get(sid)
                names[sid] = info.name if info else f"股票 {sid}"
            
            # 3. 查詢標的池中這兩天的數據
            prices = db.query(StockPrice).filter(
                StockPrice.stock_id.in_(pool_ids),
                StockPrice.date.in_([today_date, yesterday_date])
            ).all()
            
            stock_data: Dict[str, Dict[str, StockPrice]] = {}
            for p in prices:
                if p.stock_id not in stock_data:
                    stock_data[p.stock_id] = {}
                stock_data[p.stock_id][str(p.date)] = p
                
            items = []
            str_today = str(today_date)
            str_ytd = str(yesterday_date)
            
            for sid in pool_ids:
                if sid in stock_data and str_today in stock_data[sid] and str_ytd in stock_data[sid]:
                    curr = stock_data[sid][str_today]
                    prev = stock_data[sid][str_ytd]
                    
                    if float(prev.close) > 0:
                        change_percent = ((float(curr.close) - float(prev.close)) / float(prev.close)) * 100
                    else:
                        change_percent = 0.0
                        
                    items.append(RankingItem(
                        stock_id=sid,
                        stock_name=names[sid],
                        price=round(float(curr.close), 2),
                        change_percent=round(float(change_percent), 2),
                        volume=int(curr.volume)
                    ))
            
            if not items:
                return MarketRankingResponse(top_gainers=[], top_losers=[], top_volume=[])
                
            # 排序
            top_gainers = sorted(items, key=lambda x: x.change_percent, reverse=True)[:limit]
            top_losers = sorted(items, key=lambda x: x.change_percent)[:limit]
            top_volume = sorted(items, key=lambda x: x.volume, reverse=True)[:limit]
            
            return MarketRankingResponse(
                top_gainers=top_gainers,
                top_losers=top_losers,
                top_volume=top_volume
            )
        except Exception as e:
            print(f"Error in DB fallback: {e}")
            return MarketRankingResponse(top_gainers=[], top_losers=[], top_volume=[])
        finally:
            db.close()

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
        取得市場排行榜（漲幅、跌幅、成交量） (優先從本地資料庫獲取)
        """
        pool_ids = [
            "2330", "2317", "2454", "2308", "2382", "2881", "2882", "2412", "2891", "2303",
            "2886", "2884", "1216", "2002", "2885", "3231", "2603", "2892", "3045", "5871",
            "2890", "2207", "3008", "2357", "2618", "2609", "3481", "2409", "3037", "3711"
        ]
        
        db = SessionLocal()
        
        try:
            # 1. 獲取最近兩個交易日 (根據加權指數)
            latest_dates = db.query(StockPrice.date).filter(
                StockPrice.stock_id == "^TWII"
            ).order_by(StockPrice.date.desc()).limit(2).all()
            
            if not latest_dates or len(latest_dates) < 2:
                raise ValueError("資料庫中交易日數據不足")
                
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
                raise ValueError("無法獲取市場排行數據")
                
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
            print(f"Error fetching market rankings (DB): {e}")
            return MarketRankingResponse(top_gainers=[], top_losers=[], top_volume=[])
        finally:
            db.close()

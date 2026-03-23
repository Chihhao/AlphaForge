from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
import twstock

from app.schemas.market import RankingItem, MarketRankingResponse
from app.models.stock_price import StockPrice
from app.db.database import SessionLocal

# 盤中快取（5 分鐘）
_rankings_cache: Optional[MarketRankingResponse] = None
_rankings_cache_time: Optional[datetime] = None
_CACHE_TTL_SECONDS = 300  # 5 分鐘


def _is_trading_hour() -> bool:
    now = datetime.now()
    return now.weekday() < 5 and 9 <= now.hour < 15


class MarketService:
    """市場概況數據服務"""

    @staticmethod
    def get_market_rankings(limit: int = 5) -> MarketRankingResponse:
        """
        取得全市場排行榜（漲幅、跌幅、成交量）

        - 盤後 / 假日：直接讀 DB 全市場數據
        - 盤中：同上，但加 5 分鐘 server-side cache
        """
        global _rankings_cache, _rankings_cache_time

        now = datetime.now()

        # 盤中：先確認快取是否有效
        if _is_trading_hour():
            if (
                _rankings_cache is not None
                and _rankings_cache_time is not None
                and (now - _rankings_cache_time).total_seconds() < _CACHE_TTL_SECONDS
            ):
                return _rankings_cache

        result = MarketService._get_rankings_from_db(limit)

        if _is_trading_hour():
            _rankings_cache = result
            _rankings_cache_time = now

        return result

    @staticmethod
    def _get_rankings_from_db(limit: int) -> MarketRankingResponse:
        """從資料庫讀取全市場最後兩個交易日數據"""
        db = SessionLocal()
        try:
            # 最近兩個有資料的交易日（排除加權指數本身）
            latest_dates = db.query(StockPrice.date).filter(
                StockPrice.stock_id == "^TWII"
            ).order_by(StockPrice.date.desc()).limit(2).all()

            if not latest_dates or len(latest_dates) < 2:
                return MarketRankingResponse(top_gainers=[], top_losers=[], top_volume=[])

            today_date = latest_dates[0][0]
            yesterday_date = latest_dates[1][0]

            # 一次撈全市場兩天的收盤價
            prices = db.query(StockPrice).filter(
                StockPrice.date.in_([today_date, yesterday_date])
            ).all()

            stock_data: Dict[str, Dict] = {}
            for p in prices:
                sid = p.stock_id
                if sid.startswith("^"):
                    continue  # 排除指數
                if sid not in stock_data:
                    stock_data[sid] = {}
                stock_data[sid][str(p.date)] = p

            str_today = str(today_date)
            str_ytd = str(yesterday_date)

            items = []
            for sid, days in stock_data.items():
                if str_today not in days or str_ytd not in days:
                    continue
                curr = days[str_today]
                prev = days[str_ytd]
                prev_close = float(prev.close)
                if prev_close <= 0:
                    continue

                change_percent = (float(curr.close) - prev_close) / prev_close * 100

                info = twstock.codes.get(sid)
                name = info.name if info else sid

                items.append(RankingItem(
                    stock_id=sid,
                    stock_name=name,
                    price=round(float(curr.close), 2),
                    change_percent=round(change_percent, 2),
                    volume=int(curr.volume),
                ))

            if not items:
                return MarketRankingResponse(top_gainers=[], top_losers=[], top_volume=[])

            return MarketRankingResponse(
                top_gainers=sorted(items, key=lambda x: x.change_percent, reverse=True)[:limit],
                top_losers=sorted(items, key=lambda x: x.change_percent)[:limit],
                top_volume=sorted(items, key=lambda x: x.volume, reverse=True)[:limit],
            )
        except Exception as e:
            print(f"Error in DB rankings: {e}")
            return MarketRankingResponse(top_gainers=[], top_losers=[], top_volume=[])
        finally:
            db.close()

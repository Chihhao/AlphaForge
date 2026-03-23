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
        取得市場排行榜（漲幅、跌幅、成交量）

        - 盤後 / 假日：直接讀 DB（穩定正確）
        - 盤中：yfinance + 5 分鐘 server-side cache
        """
        global _rankings_cache, _rankings_cache_time

        pool_ids = [
            "2330", "2317", "2454", "2308", "2382", "2881", "2882", "2412", "2891", "2303",
            "2886", "2884", "1216", "2002", "2885", "3231", "2603", "2892", "3045", "5871",
            "2890", "2207", "3008", "2357", "2618", "2609", "3481", "2409", "3037", "3711"
        ]

        # 盤後直接讀 DB
        if not _is_trading_hour():
            return MarketService._get_rankings_from_db(pool_ids, limit)

        # 盤中：先確認快取是否有效
        now = datetime.now()
        if (
            _rankings_cache is not None
            and _rankings_cache_time is not None
            and (now - _rankings_cache_time).total_seconds() < _CACHE_TTL_SECONDS
        ):
            return _rankings_cache

        # 快取過期，重新從 yfinance 抓取
        try:
            import yfinance as yf

            tickers = [f"{sid}.TW" for sid in pool_ids]
            # 用 5d 日線確保今天和昨天都能取到
            data = yf.download(tickers, period="5d", group_by="ticker", progress=False, threads=True)

            today_date = now.date()
            items = []

            for sid in pool_ids:
                ticker = f"{sid}.TW"
                if ticker not in data.columns.levels[0]:
                    ticker = f"{sid}.TWO"
                    if ticker not in data.columns.levels[0]:
                        continue

                stock_df = data[ticker].dropna()
                if len(stock_df) < 2:
                    continue

                # 確保最後一根確實是今天
                last_date = stock_df.index[-1].date()
                if last_date != today_date:
                    continue

                today_row = stock_df.iloc[-1]
                prev_row = stock_df.iloc[-2]

                close_price = float(today_row["Close"])
                prev_close = float(prev_row["Close"])
                volume = int(today_row["Volume"])

                change_percent = ((close_price - prev_close) / prev_close * 100) if prev_close > 0 else 0.0

                info = twstock.codes.get(sid)
                name = info.name if info else f"股票 {sid}"

                items.append(RankingItem(
                    stock_id=sid,
                    stock_name=name,
                    price=round(close_price, 2),
                    change_percent=round(change_percent, 2),
                    volume=volume,
                ))

            if not items:
                return MarketService._get_rankings_from_db(pool_ids, limit)

            result = MarketRankingResponse(
                top_gainers=sorted(items, key=lambda x: x.change_percent, reverse=True)[:limit],
                top_losers=sorted(items, key=lambda x: x.change_percent)[:limit],
                top_volume=sorted(items, key=lambda x: x.volume, reverse=True)[:limit],
            )

            _rankings_cache = result
            _rankings_cache_time = now
            return result

        except Exception as e:
            print(f"Error fetching real-time rankings: {e}")
            return MarketService._get_rankings_from_db(pool_ids, limit)

    @staticmethod
    def _get_rankings_from_db(pool_ids: List[str], limit: int) -> MarketRankingResponse:
        """從資料庫讀取最後兩個交易日數據"""
        db = SessionLocal()
        try:
            latest_dates = db.query(StockPrice.date).filter(
                StockPrice.stock_id == "^TWII"
            ).order_by(StockPrice.date.desc()).limit(2).all()

            if not latest_dates or len(latest_dates) < 2:
                return MarketRankingResponse(top_gainers=[], top_losers=[], top_volume=[])

            today_date = latest_dates[0][0]
            yesterday_date = latest_dates[1][0]

            names = {}
            for sid in pool_ids:
                info = twstock.codes.get(sid)
                names[sid] = info.name if info else f"股票 {sid}"

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

                    change_percent = (
                        ((float(curr.close) - float(prev.close)) / float(prev.close)) * 100
                        if float(prev.close) > 0 else 0.0
                    )

                    items.append(RankingItem(
                        stock_id=sid,
                        stock_name=names[sid],
                        price=round(float(curr.close), 2),
                        change_percent=round(float(change_percent), 2),
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

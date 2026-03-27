from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
import pandas as pd
import twstock

from app.schemas.market import (
    RankingItem, MarketRankingResponse,
    SectorStrengthItem, SectorStrengthResponse,
    SectorStockItem, SectorStocksResponse,
)
from app.models.stock_price import StockPrice
from app.models.stock_fundamental import StockFundamental
from app.models.stock_feature import StockFeature
from app.models.user import Stock
from app.db.database import SessionLocal

# 盤中快取（5 分鐘）
_rankings_cache: Optional[MarketRankingResponse] = None
_rankings_cache_time: Optional[datetime] = None
_CACHE_TTL_SECONDS = 300  # 5 分鐘

# 產業強弱快取（sector_rs 為每日指標，5 分鐘防止重複查詢）
_sector_cache: Optional[SectorStrengthResponse] = None
_sector_cache_time: Optional[datetime] = None

# 產業個股快取（以產業名稱為 key）
_sector_stocks_cache: Dict[str, "SectorStocksResponse"] = {}
_sector_stocks_cache_time: Dict[str, datetime] = {}


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
            # 最近兩個有資料的交易日（用個股數據偵測，避免依賴 ^TWII 同步）
            from sqlalchemy import func, distinct
            latest_dates = db.query(StockPrice.date).filter(
                ~StockPrice.stock_id.startswith("^")
            ).group_by(StockPrice.date).having(
                func.count(distinct(StockPrice.stock_id)) > 100
            ).order_by(StockPrice.date.desc()).limit(2).all()

            if not latest_dates or len(latest_dates) < 2:
                return MarketRankingResponse(top_gainers=[], top_losers=[], top_volume=[])

            today_date = latest_dates[0][0]
            yesterday_date = latest_dates[1][0]

            # 批次撈 stock_fundamentals 名稱（補 twstock 沒有的股票）
            fund_names: Dict[str, str] = {
                r.stock_id: r.stock_name
                for r in db.query(StockFundamental.stock_id, StockFundamental.stock_name).all()
                if r.stock_name
            }

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

                # 名稱查詢：twstock → fundamentals DB → 代號
                tw_info = twstock.codes.get(sid)
                name = tw_info.name if tw_info else fund_names.get(sid, sid)

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
                data_date=str(today_date),
            )
        except Exception as e:
            print(f"Error in DB rankings: {e}")
            return MarketRankingResponse(top_gainers=[], top_losers=[], top_volume=[])
        finally:
            db.close()

    @staticmethod
    def get_sector_strength(top_n: int = 5) -> SectorStrengthResponse:
        """取得各產業 sector_rs 強弱排行（前 N 強 / 後 N 弱）

        sector_rs 為每日指標，採用 5 分鐘快取防止重複查詢，
        不跟隨 _is_trading_hour() 模式（盤中不會更新，快取可更激進）。
        """
        global _sector_cache, _sector_cache_time

        now = datetime.now()
        if (
            _sector_cache is not None
            and _sector_cache_time is not None
            and (now - _sector_cache_time).total_seconds() < _CACHE_TTL_SECONDS
        ):
            return _sector_cache

        result = MarketService._compute_sector_strength(top_n)
        _sector_cache = result
        _sector_cache_time = now
        return result

    @staticmethod
    def _compute_sector_strength(top_n: int = 5) -> SectorStrengthResponse:
        """按各產業的 20 日報酬中位數排行（正確方法）。

        注意：不能用 sector_rs 來排名，因為 sector_rs = ret20 - 產業中位數，
        同產業內的 sector_rs 中位數恆為 0（數學上必然）。
        正確做法：直接從 stock_prices 計算近 20 個交易日漲幅，再按產業聚合。
        """
        from sqlalchemy import func
        from datetime import date as date_type
        import logging
        logger = logging.getLogger(__name__)
        db = SessionLocal()
        try:
            # 最近一個有效交易日（個股數 > 100）
            latest_dates = (
                db.query(StockPrice.date)
                .filter(~StockPrice.stock_id.startswith("^"))
                .group_by(StockPrice.date)
                .having(func.count(StockPrice.stock_id) > 100)
                .order_by(StockPrice.date.desc())
                .limit(25)
                .all()
            )
            if len(latest_dates) < 21:
                return SectorStrengthResponse(date=None, top=[], bottom=[])

            target_date = latest_dates[0][0]
            date_20d_ago = latest_dates[20][0]   # 第 21 筆 = 20 個交易日前

            # 抓這兩個日期的全市場收盤價
            prices = (
                db.query(StockPrice.stock_id, StockPrice.date, StockPrice.close)
                .filter(
                    StockPrice.date.in_([target_date, date_20d_ago]),
                    ~StockPrice.stock_id.startswith("^"),
                )
                .all()
            )

            if not prices:
                return SectorStrengthResponse(date=target_date.isoformat(), top=[], bottom=[])

            price_df = pd.DataFrame(prices, columns=['stock_id', 'date', 'close'])
            price_dict = price_df.set_index(['stock_id', 'date'])['close'].to_dict()

            # 取得產業對照表（Stock 定義於 app.models.user，歷史遺留）
            industry_map = {
                r.stock_id: r.industry
                for r in db.query(Stock.stock_id, Stock.industry).filter(Stock.industry.isnot(None)).all()
            }

            # 計算每股 20 日報酬率
            records = []
            for sid, industry in industry_map.items():
                curr = price_dict.get((sid, target_date))
                prev = price_dict.get((sid, date_20d_ago))
                if curr is not None and prev is not None and prev > 0:
                    ret20 = (float(curr) - float(prev)) / float(prev) * 100
                    records.append({'stock_id': sid, 'industry': industry, 'ret20': ret20})

            if not records:
                return SectorStrengthResponse(date=target_date.isoformat(), top=[], bottom=[])

            df = pd.DataFrame(records)
            agg = (
                df.groupby('industry')['ret20']
                .agg(median_rs='median', stock_count='count')
                .reset_index()
            )
            # 過濾股票數 < 3 的產業
            agg = agg[agg['stock_count'] >= 3].sort_values('median_rs', ascending=False)

            top_rows = agg.head(top_n)
            bottom_rows = agg.tail(top_n).sort_values('median_rs', ascending=True)

            top = [
                SectorStrengthItem(
                    industry=r['industry'],
                    median_rs=round(float(r['median_rs']), 2),
                    stock_count=int(r['stock_count']),
                )
                for _, r in top_rows.iterrows()
            ]
            bottom = [
                SectorStrengthItem(
                    industry=r['industry'],
                    median_rs=round(float(r['median_rs']), 2),
                    stock_count=int(r['stock_count']),
                )
                for _, r in bottom_rows.iterrows()
            ]

            return SectorStrengthResponse(
                date=target_date.isoformat(),
                top=top,
                bottom=bottom,
            )
        except Exception as e:
            logger.error(f"[MarketService] sector_strength error: {e}")
            return SectorStrengthResponse(date=None, top=[], bottom=[])
        finally:
            db.close()

    @staticmethod
    def get_sector_stocks(industry: str, top: int = 10) -> SectorStocksResponse:
        """取得指定產業的 Top N 個股（按 20 日漲幅降序），附 5 分鐘快取。"""
        global _sector_stocks_cache, _sector_stocks_cache_time
        now = datetime.now()
        cache_key = f"{industry}:{top}"
        if (
            cache_key in _sector_stocks_cache
            and cache_key in _sector_stocks_cache_time
            and (now - _sector_stocks_cache_time[cache_key]).total_seconds() < _CACHE_TTL_SECONDS
        ):
            return _sector_stocks_cache[cache_key]

        result = MarketService._compute_sector_stocks(industry, top)
        _sector_stocks_cache[cache_key] = result
        _sector_stocks_cache_time[cache_key] = now
        return result

    @staticmethod
    def _compute_sector_stocks(industry: str, top: int = 10) -> SectorStocksResponse:
        """查詢指定產業的個股 20 日報酬，回傳 Top N。"""
        from sqlalchemy import func
        import logging
        logger = logging.getLogger(__name__)
        db = SessionLocal()
        try:
            # 最近 21 個有效交易日
            latest_dates = (
                db.query(StockPrice.date)
                .filter(~StockPrice.stock_id.startswith("^"))
                .group_by(StockPrice.date)
                .having(func.count(StockPrice.stock_id) > 100)
                .order_by(StockPrice.date.desc())
                .limit(25)
                .all()
            )
            if len(latest_dates) < 21:
                return SectorStocksResponse(industry=industry, date=None, stocks=[])

            target_date = latest_dates[0][0]
            date_20d_ago = latest_dates[20][0]

            # 取得指定產業的個股清單與名稱
            stocks_in_industry = (
                db.query(Stock.stock_id, Stock.stock_name, Stock.industry)
                .filter(Stock.industry == industry)
                .all()
            )
            if not stocks_in_industry:
                return SectorStocksResponse(
                    industry=industry, date=target_date.isoformat(), stocks=[]
                )

            stock_ids = [r.stock_id for r in stocks_in_industry]
            name_map = {r.stock_id: r.stock_name for r in stocks_in_industry}

            # 取兩日收盤價
            prices = (
                db.query(StockPrice.stock_id, StockPrice.date, StockPrice.close)
                .filter(
                    StockPrice.date.in_([target_date, date_20d_ago]),
                    StockPrice.stock_id.in_(stock_ids),
                )
                .all()
            )

            if not prices:
                return SectorStocksResponse(industry=industry, date=target_date.isoformat(), stocks=[])

            price_df = pd.DataFrame(prices, columns=['stock_id', 'date', 'close'])
            pivot = price_df.pivot(index='stock_id', columns='date', values='close')

            # 只取有兩日資料的股票
            if target_date not in pivot.columns or date_20d_ago not in pivot.columns:
                return SectorStocksResponse(industry=industry, date=target_date.isoformat(), stocks=[])

            pivot = pivot[[date_20d_ago, target_date]].dropna()
            pivot = pivot[pivot[date_20d_ago] > 0]
            pivot['ret20'] = ((pivot[target_date] - pivot[date_20d_ago]) / pivot[date_20d_ago] * 100).round(2)
            pivot = pivot.sort_values('ret20', ascending=False).head(top)

            stocks = [
                SectorStockItem(
                    stock_id=sid,
                    name=name_map.get(sid, sid),
                    ret20=float(row['ret20']),
                )
                for sid, row in pivot.iterrows()
            ]
            return SectorStocksResponse(
                industry=industry,
                date=target_date.isoformat(),
                stocks=stocks,
            )
        except Exception as e:
            logger.error(f"[MarketService] sector_stocks error: {e}")
            return SectorStocksResponse(industry=industry, date=None, stocks=[])
        finally:
            db.close()

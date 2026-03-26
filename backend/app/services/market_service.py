from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
import pandas as pd
import twstock

from app.schemas.market import RankingItem, MarketRankingResponse, SectorStrengthItem, SectorStrengthResponse
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
        from sqlalchemy import func
        import logging
        logger = logging.getLogger(__name__)
        db = SessionLocal()
        try:
            # 最近一個有效交易日（個股數 > 100，且有 sector_rs 資料）
            latest = (
                db.query(StockFeature.date)
                .filter(StockFeature.sector_rs.isnot(None))
                .group_by(StockFeature.date)
                .having(func.count(StockFeature.stock_id) > 100)
                .order_by(StockFeature.date.desc())
                .first()
            )
            if not latest:
                return SectorStrengthResponse(date=None, top=[], bottom=[])

            target_date = latest[0]

            # 取得當日特徵 + 產業（join stocks 表）
            # 注意：Stock 定義於 app.models.user（歷史遺留，與 User 同檔案）
            rows = (
                db.query(StockFeature.stock_id, StockFeature.sector_rs, Stock.industry)
                .join(Stock, Stock.stock_id == StockFeature.stock_id)
                .filter(
                    StockFeature.date == target_date,
                    StockFeature.sector_rs.isnot(None),
                    Stock.industry.isnot(None),
                )
                .all()
            )

            if not rows:
                return SectorStrengthResponse(date=target_date.isoformat(), top=[], bottom=[])

            # 按產業分組計算中位數
            df = pd.DataFrame(rows, columns=['stock_id', 'sector_rs', 'industry'])
            agg = (
                df.groupby('industry')['sector_rs']
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

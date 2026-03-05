"""
大盤指數概況服務

學習重點：
- 加權指數 (TAIEX, ^TWII) 是台股所有上市股票按市值加權計算的指數
- 成交量反映市場參與的活躍程度，量比 > 1 代表今天比平均更活躍
- 上漲/下跌家數的比例可以判斷整體市場是偏多還是偏空
"""
from datetime import datetime, date, timedelta
from sqlalchemy import func

from app.schemas.market import MarketSummary
from app.models.stock_price import StockPrice
from app.db.database import SessionLocal


class MarketSummaryService:
    """大盤指數概況數據服務"""

    # 台股代表性股票池
    STOCK_POOL = [
        "2330", "2317", "2454", "2308", "2382", "2881", "2882", "2412", "2891", "2303",
        "2886", "2884", "1216", "2002", "2885", "3231", "2603", "2892", "3045", "5871",
        "2890", "2207", "3008", "2357", "2618", "2609", "3481", "2409", "3037", "3711"
    ]

    @staticmethod
    def get_market_summary() -> MarketSummary:
        """取得今日大盤指數概況 (優先從本地資料庫獲取)"""
        pool = MarketSummaryService.STOCK_POOL
        db = SessionLocal()
        
        try:
            # 1. 獲取加權指數最新兩天數據
            taiex_prices = db.query(StockPrice).filter(
                StockPrice.stock_id == "^TWII"
            ).order_by(StockPrice.date.desc()).limit(15).all() # 拿多一點算均量
            
            if not taiex_prices or len(taiex_prices) < 2:
                # 如果資料庫沒資料，回退到 yfinance (但通常應該由同步任務處理)
                raise ValueError("資料庫中無加權指數數據")

            # 轉成依日期升序
            taiex_prices = sorted(taiex_prices, key=lambda x: x.date)
            
            today_idx = taiex_prices[-1]
            yesterday_idx = taiex_prices[-2]
            
            taiex_price = round(today_idx.close, 2)
            prev_close = yesterday_idx.close
            taiex_change = round(taiex_price - prev_close, 2)
            taiex_change_percent = round((taiex_change / prev_close) * 100, 2)
            
            # 2. 統計股票池數據
            valid_dates = [p.date for p in taiex_prices]
            today_date = valid_dates[-1]
            yesterday_date = valid_dates[-2]
            
            advances = 0
            declines = 0
            unchanged = 0
            limit_up = 0
            limit_down = 0
            today_total_amount = 0
            
            # 批量查詢當天與昨天的成分股數據
            pool_data = db.query(StockPrice).filter(
                StockPrice.stock_id.in_(pool),
                StockPrice.date.in_([today_date, yesterday_date])
            ).all()
            
            # 按 stock_id 分群
            stock_map = {}
            for p in pool_data:
                if p.stock_id not in stock_map:
                    stock_map[p.stock_id] = {}
                stock_map[p.stock_id][p.date] = p
                
            for sid in pool:
                if sid in stock_map and today_date in stock_map[sid] and yesterday_date in stock_map[sid]:
                    curr = stock_map[sid][today_date]
                    prev = stock_map[sid][yesterday_date]
                    
                    change = ((curr.close - prev.close) / prev.close) * 100
                    if change >= 9.5:
                        limit_up += 1; advances += 1
                    elif change <= -9.5:
                        limit_down += 1; declines += 1
                    elif change > 0.01: advances += 1
                    elif change < -0.01: declines += 1
                    else: unchanged += 1
                    
                    today_total_amount += (curr.volume * curr.close)
            
            # 3. 計算 5 日均量 (這裡用加權指數本生的成交量欄位，或者成分股加總)
            # 加權指數的 volume 通常是成交金額或股數，視 yf 回傳而定
            # 這裡我們沿用之前的邏輯：成分股成交金額加總
            past_daily_amounts = []
            for d in valid_dates[-6:-1]:
                d_amount = 0
                historical_data = db.query(StockPrice).filter(
                    StockPrice.stock_id.in_(pool),
                    StockPrice.date == d
                ).all()
                for h in historical_data:
                    d_amount += (h.volume * h.close)
                if d_amount > 0:
                    past_daily_amounts.append(d_amount)
            
            avg_amount_5d = sum(past_daily_amounts) / len(past_daily_amounts) if past_daily_amounts else today_total_amount
            volume_ratio = round(today_total_amount / avg_amount_5d, 2) if avg_amount_5d > 0 else 1.0
            
            # 漲跌比與情緒
            ad_ratio = round(advances / declines, 2) if declines > 0 else float(advances)
            sentiment = "bullish" if taiex_change_percent > 0.5 and ad_ratio > 1.2 else ("bearish" if taiex_change_percent < -0.5 and ad_ratio < 0.8 else "neutral")
            vol_status = "high" if volume_ratio > 1.3 else ("low" if volume_ratio < 0.7 else "normal")
            
            return MarketSummary(
                taiex_price=taiex_price,
                taiex_change=taiex_change,
                taiex_change_percent=taiex_change_percent,
                taiex_volume=int(today_total_amount),
                avg_volume_5d=int(avg_amount_5d),
                volume_ratio=volume_ratio,
                advances=advances,
                declines=declines,
                unchanged=unchanged,
                limit_up=limit_up,
                limit_down=limit_down,
                advance_decline_ratio=ad_ratio,
                market_sentiment=sentiment,
                volume_status=vol_status,
                data_date=today_date.strftime("%Y-%m-%d"),
            )
            
        except Exception as e:
            print(f"Error in market summary (DB): {e}")
            # 如果失敗，嘗試簡單回退或返回空數據
            return MarketSummary(
                taiex_price=0, taiex_change=0, taiex_change_percent=0,
                taiex_volume=0, avg_volume_5d=1, volume_ratio=0,
                advances=0, declines=0, unchanged=0, limit_up=0, limit_down=0,
                advance_decline_ratio=0, market_sentiment="neutral",
                volume_status="normal", data_date=date.today().isoformat()
            )
        finally:
            db.close()

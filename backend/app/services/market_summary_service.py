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
from app.services.index_service import IndexService
import yfinance as yf
import pandas as pd
import numpy as np
import requests


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
        pool = IndexService.get_0050_constituents()
        db = SessionLocal()
        
        try:
            # 1. 獲取加權指數基礎數據 (從 DB)
            taiex_prices_db = db.query(StockPrice).filter(
                StockPrice.stock_id == "^TWII"
            ).order_by(StockPrice.date.desc()).limit(15).all()
            
            if not taiex_prices_db:
                raise ValueError("資料庫中無加權指數數據")

            taiex_prices_db = sorted(taiex_prices_db, key=lambda x: x.date)
            latest_db = taiex_prices_db[-1]
            
            # --- 即時回退邏輯 ---
            now = datetime.now()
            # 台灣時間平日 09:00 - 14:30 (含收盤後清算時間)
            is_trading_hour = (now.weekday() < 5) and (9 <= now.hour < 15)
            is_live = False
            last_updated = now.strftime("%H:%M:%S")
            
            taiex_price = round(latest_db.close, 2)
            prev_close = taiex_prices_db[-2].close if len(taiex_prices_db) >= 2 else taiex_price
            data_date = latest_db.date
            
            # 如果是交易時間，或者 DB 資料是舊的 (還沒同步到今天)
            if is_trading_hour or latest_db.date < now.date():
                try:
                    # 優先嘗試 TWSE API (最準確且即時)
                    twse_url = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=tse_t00.tw"
                    twse_headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"}
                    twse_resp = requests.get(twse_url, headers=twse_headers, timeout=3)
                    
                    twse_success = False
                    if twse_resp.status_code == 200:
                        twse_data = twse_resp.json()
                        if "msgArray" in twse_data and len(twse_data["msgArray"]) > 0:
                            item = twse_data["msgArray"][0]
                            # z 為當前價, y 為昨收, o 為開盤價
                            z_price = item.get("z") or item.get("o")
                            y_price = item.get("y")
                            if z_price and z_price != "-":
                                taiex_price = round(float(z_price), 2)
                                if y_price and y_price != "-":
                                    prev_close = float(y_price)
                                
                                # 使用交易所提供的報價時間
                                if item.get("t"):
                                    last_updated = item.get("t")
                                else:
                                    last_updated = now.strftime("%H:%M:%S")
                                
                                data_date = now.date()
                                if is_trading_hour:
                                    is_live = True
                                twse_success = True
                    
                    if not twse_success:
                        # 如果 TWSE 失敗，回退到 yfinance
                        ticker = yf.Ticker("^TWII")
                        live_hist = ticker.history(period="2d")
                        if not live_hist.empty:
                            live_price = live_hist.iloc[-1]['Close']
                            # 如果 yf 抓到的資料是今天的 (或是交易時間內且跟 DB 不同)
                            is_yf_today = live_hist.index[-1].date() == now.date()
                            
                            if is_yf_today or (is_trading_hour and abs(live_price - latest_db.close) > 0.01):
                                taiex_price = round(live_price, 2)
                                if len(live_hist) >= 2:
                                    prev_close = live_hist.iloc[-2]['Close']
                                elif latest_db.date < now.date():
                                    prev_close = latest_db.close
                                
                                # 使用 yf 的最新時間
                                last_updated = now.strftime("%H:%M:%S") # yf 沒有秒級 quote time，用目前時間
                                data_date = now.date()
                                if is_trading_hour:
                                    is_live = True
                except Exception as yfe:
                    print(f"[MarketSummaryService] index live fallback failed: {yfe}")
            
            # --- 額外修正：如果在交易時間內，不論 index 是否變動，都應嘗試開啟 is_live 以更新成分股 ---
            if is_trading_hour:
                is_live = True
            
            taiex_change = round(taiex_price - prev_close, 2)
            taiex_change_percent = round((taiex_change / prev_close) * 100, 2) if prev_close > 0 else 0
            
            # 2. 統計股票池數據 (廣度統計)
            valid_dates = [p.date for p in taiex_prices_db]
            today_date = latest_db.date
            yesterday_date = taiex_prices_db[-2].date if len(taiex_prices_db) >= 2 else today_date
            
            advances = 0
            declines = 0
            unchanged = 0
            limit_up = 0
            limit_down = 0
            today_total_amount = 0
            
            # 先從資料庫獲取基底數據 (昨日與今日已存數據)
            pool_data = db.query(StockPrice).filter(
                StockPrice.stock_id.in_(pool),
                StockPrice.date.in_([today_date, yesterday_date])
            ).all()
            
            stock_map = {}
            for p in pool_data:
                if p.stock_id not in stock_map:
                    stock_map[p.stock_id] = {}
                stock_map[p.stock_id][p.date] = p
            
            # --- 如果是即時模式，主動抓取 50 檔成分股的即時漲跌 ---
            live_prices = {}
            if is_live:
                try:
                    # 批量抓取 Yahoo Finance 快照 (50 檔)
                    tickers_str = " ".join([f"{s}.TW" for s in pool])
                    live_batch = yf.download(tickers_str, period="1d", interval="1m", progress=False, threads=True)
                    
                    if not live_batch.empty:
                        # 處理 YF 回傳的 MultiIndex 結構
                        closes = live_batch['Close']
                        if isinstance(closes, pd.Series): # 只有一檔時
                            live_prices[pool[0]] = closes.iloc[-1]
                        else:
                            for sid in pool:
                                symbol = f"{sid}.TW"
                                if symbol in closes.columns:
                                    val = closes[symbol].dropna()
                                    if not val.empty:
                                        live_prices[sid] = val.iloc[-1]
                except Exception as e:
                    print(f"[MarketSummaryService] Batch live fetch failed: {e}")

            for sid in pool:
                if sid in stock_map:
                    # 決定當前價格與基準價格
                    prev = stock_map[sid].get(yesterday_date) or stock_map[sid].get(today_date)
                    if not prev: continue
                    
                    curr_price = stock_map[sid][today_date].close if today_date in stock_map[sid] else prev.close
                    
                    # 如果有即時報價，覆蓋它
                    if is_live and sid in live_prices:
                        curr_price = live_prices[sid]
                    
                    change_pct = ((curr_price - prev.close) / prev.close) * 100 if prev.close > 0 else 0
                    
                    if change_pct >= 9.5:
                        limit_up += 1; advances += 1
                    elif change_pct <= -9.5:
                        limit_down += 1; declines += 1
                    elif change_pct > 0.1: advances += 1
                    elif change_pct < -0.1: declines += 1
                    else: unchanged += 1
                    
                    today_total_amount += (curr_price * (stock_map[sid][today_date].volume if today_date in stock_map[sid] else 1000))
            
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
                data_date=data_date.strftime("%Y-%m-%d"),
                is_live=is_live,
                last_updated=last_updated
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

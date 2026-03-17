from typing import List, Optional
from datetime import date
import twstock
import pandas as pd

from app.schemas.screener import StrategyResult, ScreenerStock
from app.services.indicator_service import IndicatorService
from app.services.fundamental_service import FundamentalService
from app.models.stock_fundamental import StockFundamental
from app.models.stock_price import StockPrice
from app.models.screener_cache import ScreenerCache
from app.db.database import SessionLocal, engine
import json
import yfinance as yf
from datetime import datetime, date, timedelta
import requests


# 模組層級快取：掃描一次就存住，直到手動清除
_screener_cache: Optional[List[StrategyResult]] = None
_screener_cache_date: Optional[date] = None


class ScreenerService:
    """選股雷達服務 (向量化高速版)"""

    @staticmethod
    def invalidate_cache():
        """清除快取（在每日同步完成後呼叫）"""
        global _screener_cache, _screener_cache_date
        _screener_cache = None
        _screener_cache_date = date.today() # 設為今天以觸發下次重新同步
        
        # 同步清除資料庫中的今日快取
        db = SessionLocal()
        try:
            db.query(ScreenerCache).filter(
                ScreenerCache.cache_date == date.today()
            ).delete()
            db.commit()
            print(f"[ScreenerService] Memory and DB cache cleared for {date.today()}.")
        except Exception as e:
            print(f"[ScreenerService] Failed to clear DB cache: {e}")
            db.rollback()
        finally:
            db.close()

    @staticmethod
    def get_stock_name(stock_id: str) -> str:
        """嘗試獲取股票名稱"""
        info = twstock.codes.get(stock_id)
        if info:
            return info.name

        fallback = {
            "2330": "台積電", "2317": "鴻海", "2454": "聯發科",
            "2382": "廣達", "2308": "台達電"
        }
        return fallback.get(stock_id, f"股票 {stock_id}")

    @staticmethod
    def _apply_live_prices(results: List[StrategyResult]) -> None:
        """在盤中交易時間，更新 results 中每支股票的即時報價（就地修改）。"""
        now = datetime.now()
        is_trading_hour = (now.weekday() < 5) and (9 <= now.hour < 15)

        # 追蹤哪些 symbol 已被 TWSE 成功更新，避免 yfinance fallback 重複覆蓋
        updated_symbols: set = set()

        if is_trading_hour:
            try:
                all_symbols = []
                for res in results:
                    if res.stocks:
                        all_symbols.extend([s.symbol for s in res.stocks])

                if all_symbols:
                    chunk_size = 35
                    live_map = {}
                    for i in range(0, len(all_symbols), chunk_size):
                        batch = all_symbols[i:i + chunk_size]
                        ex_chs = []
                        for s in batch:
                            is_otc = s.startswith(("6", "5", "8", "4"))
                            prefix = "otc" if is_otc else "tse"
                            clean_s = s.replace(".TW", "").replace(".TWO", "")
                            ex_chs.append(f"{prefix}_{clean_s}.tw")

                        url = f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch={'|'.join(ex_chs)}"
                        headers = {"User-Agent": "Mozilla/5.0"}
                        resp = requests.get(url, headers=headers, timeout=5)
                        if resp.status_code == 200:
                            data = resp.json()
                            if "msgArray" in data:
                                for item in data["msgArray"]:
                                    sid = item.get("c")
                                    z_price = item.get("z")  # 只取即時成交價，不 fallback 到開盤價
                                    y_price = item.get("y")
                                    if z_price and z_price != "-":
                                        curr = float(z_price)
                                        prev = float(y_price) if y_price and y_price != "-" else curr
                                        live_map[sid] = {
                                            "price": curr,
                                            "change": round((curr - prev) / prev * 100, 2) if prev > 0 else 0
                                        }

                    for res in results:
                        if not res.stocks: continue
                        for s in res.stocks:
                            if s.symbol in live_map:
                                s.price = live_map[s.symbol]["price"]
                                s.change = live_map[s.symbol]["change"]
                                updated_symbols.add(s.symbol)
                        # 只有當 strategy 內所有 stocks 都被更新，才標記 is_live
                        if res.stocks and all(s.symbol in updated_symbols for s in res.stocks):
                            res.is_live = True
            except Exception as te:
                print(f"[ScreenerService] TWSE Batch update failed: {te}")

        # yfinance fallback：補充 TWSE 未能更新的 stocks
        for res in results:
            if not res.stocks:
                continue
            stocks_to_update = [s for s in res.stocks if s.symbol not in updated_symbols]
            if not stocks_to_update:
                res.is_live = True
                continue
            try:
                symbol_map = {}
                for s in stocks_to_update:
                    symbol_map[f"{s.symbol}.TW"] = s
                    symbol_map[f"{s.symbol}.TWO"] = s

                tickers_list = list(symbol_map.keys())
                live_data = yf.download(tickers_list, period="2d", interval="1d", progress=False, threads=True)

                if not live_data.empty and 'Close' in live_data:
                    closes = live_data['Close']
                    for s in stocks_to_update:
                        target_keys = [f"{s.symbol}.TW", f"{s.symbol}.TWO"]
                        for k in target_keys:
                            col_data = closes[k] if hasattr(closes, 'columns') and k in closes.columns else (closes if isinstance(closes, pd.Series) and closes.name == k else None)
                            if col_data is not None:
                                s_data = col_data.dropna()
                                if len(s_data) >= 2:
                                    prev_close = float(s_data.iloc[-2])
                                    curr_price = float(s_data.iloc[-1])
                                    s.price = round(curr_price, 2)
                                    s.change = round(((curr_price - prev_close) / prev_close * 100), 2)
                                    break
                                elif len(s_data) == 1:
                                    s.price = round(float(s_data.iloc[-1]), 2)
                                    break
                res.is_live = True
            except Exception as ye:
                print(f"[ScreenerService] yf 批量同步報價異常: {ye}")

    @staticmethod
    def get_screener_results() -> List[StrategyResult]:
        """
        全市場向量化極速掃描。
        依賴本地 SQLite 的歷史資料進行 Pandas 運算。
        """
        global _screener_cache, _screener_cache_date
        today = date.today()

        if _screener_cache is not None and _screener_cache_date == today:
            print("[ScreenerService] Memory cache hit. Applying live prices...")
            ScreenerService._apply_live_prices(_screener_cache)
            return _screener_cache

        # 1. 檢查資料庫持久化快取
        db = SessionLocal()
        try:
            db_cache = db.query(ScreenerCache).filter(
                ScreenerCache.strategy_id == "af_choice",
                ScreenerCache.cache_date == today
            ).first()
            
            if db_cache:
                print(f"[ScreenerService] Cache hit from DB for {today}. Applying live updates if needed...")
                cached_data = json.loads(db_cache.results_json)
                results = [StrategyResult(**res) for res in cached_data]
                
                ScreenerService._apply_live_prices(results)
                
                display_date = db_cache.cache_date
                if hasattr(display_date, 'strftime'):
                    display_date = display_date.strftime("%Y-%m-%d")
                else:
                    display_date = str(display_date)[:10]

                if results and results[0].stocks:
                    fund_dates = db.query(StockFundamental.updated_at).filter(
                        StockFundamental.stock_id.in_([s.symbol for s in results[0].stocks])
                    ).all()
                    if fund_dates:
                        actual_dates = [d[0] for d in fund_dates if d[0]]
                        if actual_dates:
                            display_date = max(actual_dates).strftime("%Y-%m-%d")
                
                for res in results:
                    res.data_date = str(display_date)

                _screener_cache = results
                _screener_cache_date = today
                return results
        except Exception as ce:
            print(f"[ScreenerService] DB cache check failed: {ce}")
        finally:
            db.close()

        print("[ScreenerService] Cache miss, starting vectorized scan...")
        
        # 策略參數
        bias_oversold_threshold = -10.0
        bias_bull_threshold = 0.0
        vol_multiplier = 1.5

        import time
        t0 = time.time()
        
        # 1. 取得全市場所有股票資料
        db = SessionLocal()
        try:
            import datetime
            cutoff_date = today - datetime.timedelta(days=90)
            
            query = db.query(
                StockPrice.stock_id, StockPrice.date, 
                StockPrice.open, StockPrice.high, 
                StockPrice.low, StockPrice.close, StockPrice.volume
            ).filter(StockPrice.date >= cutoff_date).statement
            
            raw_df = pd.read_sql(query, engine)
            af_choice_fundamentals = FundamentalService.get_af_choice_stocks(db)
            
        except Exception as e:
            print(f"Error fetching fundamental data: {e}")
            return [
                StrategyResult(
                    id="af_choice",
                    name="AF 精選",
                    description="目前無法取得基本面資料，請稍後再試。",
                    tag="價值成長股",
                    stocks=[]
                )
            ]
        finally:
            db.close()
            
        if raw_df.empty and not af_choice_fundamentals:
            return [
                StrategyResult(id="af_choice", name="AF 精選", description="...", tag="價值成長股", stocks=[])
            ]

        latest_df = pd.DataFrame()
        if not raw_df.empty:
            raw_df = raw_df.sort_values(['stock_id', 'date'])
            raw_df['ma5_vol'] = raw_df.groupby('stock_id')['volume'].transform(lambda x: x.rolling(window=5).mean())
            df = IndicatorService.attach_indicators(raw_df)
            
            if not df.empty:
                df['prev_close'] = df.groupby('stock_id')['close'].shift(1)
                df['change_percent'] = ((df['close'] - df['prev_close']) / df['prev_close']) * 100
                latest_df = df.groupby('stock_id').tail(1).copy()
                latest_df = latest_df.reset_index(drop=True)

        results_s3 = []
        for f in af_choice_fundamentals:
            price, change, bias = 0.0, 0.0, 0.0
            if not latest_df.empty:
                match = latest_df[latest_df['stock_id'] == f.stock_id]
                if not match.empty:
                    price = round(float(match.iloc[0]['close']), 2)
                    change = round(float(match.iloc[0]['change_percent']), 2)
                    bias = round(float(match.iloc[0]['bias20']), 2) if pd.notna(match.iloc[0]['bias20']) else 0.0
            
            results_s3.append(ScreenerStock(
                symbol=f.stock_id,
                name=ScreenerService.get_stock_name(f.stock_id),
                price=price,
                change=change,
                bias20=bias,
                yield_rate=f.yield_rate,
                roe=f.roe_latest,
                pb=f.pb_ratio,
                volume_avg_5d=f.volume_avg_5d
            ))

        print(f"[ScreenerService] Scan complete in {time.time() - t0:.2f}s")

        results = [
            StrategyResult(
                id="af_choice",
                name="AF 精選",
                description="兼顧價值防禦 (高息、合理估值) 與營運爆發力 (高 ROE、連續獲利與營收雙成長) 的嚴選績優股。",
                tag="價值成長股",
                stocks=results_s3
            )
        ]

        actual_screening_date = today
        if af_choice_fundamentals:
            relevant_dates = [f.updated_at for f in af_choice_fundamentals if f.updated_at]
            if relevant_dates:
                 actual_screening_date = max(relevant_dates)
        
        display_date_str = actual_screening_date.strftime("%Y-%m-%d") if hasattr(actual_screening_date, 'strftime') else str(actual_screening_date)[:10]

        for res in results:
            res.data_date = display_date_str

        _screener_cache = results
        _screener_cache_date = today

        db = SessionLocal()
        try:
            db.query(ScreenerCache).filter(
                ScreenerCache.strategy_id == "af_choice",
                ScreenerCache.cache_date == today
            ).delete()
            
            new_cache = ScreenerCache(
                strategy_id="af_choice",
                cache_date=today,
                results_json=json.dumps([res.model_dump() for res in results])
            )
            db.add(new_cache)
            db.commit()
            print(f"[ScreenerService] Results persisted to DB for {today}.")
        except Exception as se:
            print(f"[ScreenerService] Failed to persist cache: {se}")
            db.rollback()
        finally:
            db.close()
        
        return results

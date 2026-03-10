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
from app.db.database import SessionLocal
import json
import yfinance as yf
from datetime import datetime, date, timedelta


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
        _screener_cache_date = None
        print("[ScreenerService] Cache invalidated.")

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
    def get_screener_results() -> List[StrategyResult]:
        """
        全市場向量化極速掃描。
        依賴本地 SQLite 的歷史資料進行 Pandas 運算。
        """
        global _screener_cache, _screener_cache_date
        today = date.today()

        if _screener_cache is not None and _screener_cache_date == today:
            print("[ScreenerService] Returning memory cached results.")
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
                
                # --- 強制同步最準確的報價與漲跌幅 ---
                # 為了與個股頁面 100% 一致，且維持首頁速度，採用的批次抓取 2 日數據進行計算
                for res in results:
                    if not res.stocks: continue
                    try:
                        # 準備所有代號 (包含 .TW 與 .TWO)
                        symbol_map = {}
                        for s in res.stocks:
                            tw_sym = f"{s.symbol}.TW"
                            two_sym = f"{s.symbol}.TWO"
                            symbol_map[tw_sym] = s
                            symbol_map[two_sym] = s
                            
                        tickers_list = list(symbol_map.keys())
                        # 抓取 2 日數據以計算與昨日收盤的漲跌幅
                        live_data = yf.download(tickers_list, period="2d", interval="1d", progress=False, threads=True)
                        
                        if not live_data.empty and 'Close' in live_data:
                            closes = live_data['Close']
                            
                            for s in res.stocks:
                                target_keys = [f"{s.symbol}.TW", f"{s.symbol}.TWO"]
                                for k in target_keys:
                                    if k in closes.columns:
                                        s_data = closes[k].dropna()
                                        if len(s_data) >= 2:
                                            # 有兩日資料：計算漲跌
                                            prev_close = float(s_data.iloc[-2])
                                            curr_price = float(s_data.iloc[-1])
                                            s.price = round(curr_price, 2)
                                            s.change = round(((curr_price - prev_close) / prev_close * 100), 2)
                                            break
                                        elif len(s_data) == 1:
                                            # 僅有一日資料 (可能是新上線或 yf 數據缺失)
                                            s.price = round(float(s_data.iloc[-1]), 2)
                                            # 漲跌幅維持原樣或設為 0
                                            break
                        res.is_live = True
                    except Exception as ye:
                        print(f"[ScreenerService] 批量同步報價異常: {ye}")
                
                # 取得這批資料中實際的更新日期 (通常是前一交易日)
                display_date = db_cache.cache_date
                if hasattr(display_date, 'strftime'):
                    display_date = display_date.strftime("%Y-%m-%d")
                else:
                    display_date = str(display_date)[:10]

                if results and results[0].stocks:
                    # 嘗試從資料庫中獲取這批股票的實際基本面更新日
                    fund_dates = db.query(StockFundamental.updated_at).filter(
                        StockFundamental.stock_id.in_([s.symbol for s in results[0].stocks])
                    ).all()
                    if fund_dates:
                        # 找出這批股票中的最新更新日期
                        actual_dates = [d[0] for d in fund_dates if d[0]]
                        if actual_dates:
                            display_date = max(actual_dates).strftime("%Y-%m-%d")
                
                for res in results:
                    res.data_date = str(display_date)

                # 更新記憶體快取避免一直查表
                _screener_cache = results
                _screener_cache_date = today
                return results
        except Exception as ce:
            print(f"[ScreenerService] DB cache check failed: {ce}")
        finally:
            db.close()

        print("[ScreenerService] Cache miss, starting vectorized scan (this may take a few seconds)...")
        
        # 策略參數
        bias_oversold_threshold = -10.0
        bias_bull_threshold = 0.0
        vol_multiplier = 1.5

        import time
        t0 = time.time()
        
        # 1. 取得全市場所有股票資料 (近 60 天)
        db = SessionLocal()
        try:
            import datetime
            cutoff_date = today - datetime.timedelta(days=90) # 寬鬆抓 90 日曆天以涵蓋 60 交易日
            
            # 使用 pd.read_sql
            query = db.query(
                StockPrice.stock_id, StockPrice.date, 
                StockPrice.open, StockPrice.high, 
                StockPrice.low, StockPrice.close, StockPrice.volume
            ).filter(StockPrice.date >= cutoff_date).statement
            
            raw_df = pd.read_sql(query, db.bind)
            
            # --- 獲取大師精選結果 (基本面策略) ---
            af_choice_fundamentals = FundamentalService.get_af_choice_stocks(db)
            
        except Exception as e:
            print(f"Error fetching fundamental data: {e}")
            return [
                StrategyResult(
                    id="af_choice",
                    name="AF 精選價值成長股",
                    description="目前無法取得基本面資料，請稍後再試。",
                    tag="基本面優選",
                    stocks=[]
                )
            ]
        finally:
            db.close()
            
        if raw_df.empty and not af_choice_fundamentals:
            return [
                StrategyResult(id="af_choice", name="AF 精選價值成長股", description="...", tag="基本面優選", stocks=[])
            ]

        # 封裝結果工具
        def _to_screener_stocks(res_df):
            return [
                ScreenerStock(
                    symbol=row['stock_id'],
                    name=ScreenerService.get_stock_name(row['stock_id']),
                    price=round(float(row['close']), 2),
                    change=round(float(row['change_percent']), 2),
                    bias20=round(float(row['bias20']), 2) if pd.notna(row['bias20']) else 0.0
                )
                for _, row in res_df.iterrows()
            ]

        # --- 技術面計算 (供 AF 精選獲取最新價格與指標) ---
        latest_df = pd.DataFrame()
        if not raw_df.empty:
            # 計算 5 日均量
            raw_df = raw_df.sort_values(['stock_id', 'date'])
            raw_df['ma5_vol'] = raw_df.groupby('stock_id')['volume'].transform(lambda x: x.rolling(window=5).mean())
            
            # 附加其他指標 (向量化)
            df = IndicatorService.attach_indicators(raw_df)
            
            if not df.empty:
                df['prev_close'] = df.groupby('stock_id')['close'].shift(1)
                df['change_percent'] = ((df['close'] - df['prev_close']) / df['prev_close']) * 100
                latest_df = df.groupby('stock_id').tail(1).copy()
                latest_df = latest_df.reset_index(drop=True)

        # --- 策略: AF 精選 (轉換 Fundamental 模型為 ScreenerStock) ---
        results_s3 = []
        for f in af_choice_fundamentals:
            # 獲取最新價格
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
                pb=f.pb_ratio
            ))

        print(f"[ScreenerService] Scan complete in {time.time() - t0:.2f}s")

        results = [
            StrategyResult(
                id="af_choice",
                name="AF 精選價值成長股",
                description="兼顧價值防禦 (高息、合理估值) 與營運爆發力 (高 ROE、連續獲利與營收雙成長) 的嚴選績優股。",
                tag="基本面優選",
                stocks=results_s3
            )
        ]

        # 找出這組結果所使用的基本面實際更新日期
        actual_screening_date = today
        if af_choice_fundamentals:
            relevant_dates = [f.updated_at for f in af_choice_fundamentals if f.updated_at]
            if relevant_dates:
                 actual_screening_date = max(relevant_dates)
        
        display_date_str = actual_screening_date.strftime("%Y-%m-%d") if hasattr(actual_screening_date, 'strftime') else str(actual_screening_date)[:10]

        for res in results:
            res.data_date = display_date_str

        # 儲存到記憶體
        _screener_cache = results
        _screener_cache_date = today

        # 儲存到資料庫永久快取 (非同步概念，不影響回傳速度，但這裡為了穩定先同步寫入)
        db = SessionLocal()
        try:
            # 清除舊的今日快取 (如果有的話)
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

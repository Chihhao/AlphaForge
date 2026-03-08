from typing import List, Optional
from datetime import date
import twstock
import pandas as pd

from app.schemas.screener import StrategyResult, ScreenerStock
from app.services.indicator_service import IndicatorService
from app.models.stock_price import StockPrice
from app.db.database import SessionLocal


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
            print("[ScreenerService] Returning cached results.")
            return _screener_cache

        print("[ScreenerService] Cache miss, starting vectorized scan...")
        
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
        except Exception as e:
            print(f"Error loading data from DB: {e}")
            raw_df = pd.DataFrame()
        finally:
            db.close()
            
        if raw_df.empty:
            return [
                StrategyResult(id="s1", name="乖離率過低 (跌深反彈)", description="...", tag="全市場掃描", stocks=[]),
                StrategyResult(id="s2", name="乖離率轉正 (強勢動能)", description="...", tag="全市場掃描", stocks=[])
            ]

        # 計算 5 日均量
        raw_df = raw_df.sort_values(['stock_id', 'date'])
        raw_df['ma5_vol'] = raw_df.groupby('stock_id')['volume'].transform(lambda x: x.rolling(window=5).mean())
        
        # 附加其他指標 (向量化)
        df = IndicatorService.attach_indicators(raw_df)
        
        if df.empty:
            return [
                StrategyResult(id="s1", name="乖離率過低 (跌深反彈)", description="...", tag="全市場掃描", stocks=[]),
                StrategyResult(id="s2", name="乖離率轉正 (強勢動能)", description="...", tag="全市場掃描", stocks=[])
            ]

        # 先在原本包含所有歷史天的 df 算出漲跌幅，確保對齊
        df['prev_close'] = df.groupby('stock_id')['close'].shift(1)
        df['change_percent'] = ((df['close'] - df['prev_close']) / df['prev_close']) * 100
        
        # 然後再篩選出最後一個交易日的數據 (注意：必須針對每檔股票各自取最新一日)
        latest_df = df.groupby('stock_id').tail(1).copy()
        latest_df = latest_df.reset_index(drop=True)

        # --- 策略 1: 跌深反彈 (s1) ---
        s1_mask = latest_df['bias20'] < bias_oversold_threshold
        s1_df = latest_df[s1_mask].sort_values('bias20', ascending=True).head(10)

        # --- 策略 2: 強勢動能 (s2) ---
        s2_mask = (
            (latest_df['bias20'] > bias_bull_threshold) &
            (latest_df['volume'] > (latest_df['ma5_vol'] * vol_multiplier)) &
            (latest_df['change_percent'] > 0)
        )
        s2_df = latest_df[s2_mask].sort_values('change_percent', ascending=False).head(10)

        # 封裝結果
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

        results_s1 = _to_screener_stocks(s1_df)
        results_s2 = _to_screener_stocks(s2_df)

        print(f"[ScreenerService] Vectorized scan complete in {time.time() - t0:.2f}s")

        results = [
            StrategyResult(
                id="s1",
                name="乖離率過低 (跌深反彈)",
                description="20 日乖離率 < -10%：全市場掃描發現超跌標的，尋找潛在反彈機會。",
                tag="全市場掃描",
                stocks=results_s1
            ),
            StrategyResult(
                id="s2",
                name="乖離率轉正 (強勢動能)",
                description="20 日乖離率 > 0% 且量增：股價重回月線且動能爆發，主力表態預兆。",
                tag="全市場掃描",
                stocks=results_s2
            )
        ]

        # 儲存快取
        _screener_cache = results
        _screener_cache_date = today
        
        return results

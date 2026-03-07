from typing import List
from concurrent.futures import ThreadPoolExecutor, as_completed
import twstock
import pandas as pd

from app.schemas.screener import StrategyResult, ScreenerStock
from app.services.stock_service import StockService
from app.models.stock_price import StockPrice
from app.db.database import SessionLocal

# 預設的台股 50 檔熱門權值股名單（做為預選池 MVP）
POPULAR_STOCKS = [
    # 半導體 / 電子代工
    "2330", "2317", "2454", "2382", "2308", "3008", "3034", "3037", "3711", "2379",
    "2395", "2357", "3231", "2353", "2356", "2408", "3481", "2409", "2344", "5483",
    "6488", "2303", "2324", "2383", "3293", "4938", "6239", "8299", "3443", "3661",
    # 金融保險
    "2881", "2882", "2891", "2886", "2884", "2892", "2885", "2890", "2887", "2880",
    # 傳產 / 航運 / 重電
    "2603", "2609", "2615", "1101", "1301", "1303", "2002", "2105", "1504", "1519"
]

class ScreenerService:
    """選股雷達服務"""
    
    @staticmethod
    def get_stock_name(stock_id: str) -> str:
        """嘗試獲取股票名稱"""
        info = twstock.codes.get(stock_id)
        if info:
            return info.name
        
        # 簡易備用 mapping
        fallback = {
            "2330": "台積電", "2317": "鴻海", "2454": "聯發科", 
            "2382": "廣達", "2308": "台達電"
        }
        return fallback.get(stock_id, f"股票 {stock_id}")

    @staticmethod
    def get_screener_results() -> List[StrategyResult]:
        """
        掃描全市場股票池，並依據策略條件過濾出符合的股票。
        邏輯：
        1. 找出資料庫中最新的交易日期。
        2. 抓取該日期內所有的股票代號。
        3. 計算指標並過濾。
        """
        db = SessionLocal()
        try:
            # 1. 找出最新交易日期
            latest_date_row = db.query(StockPrice.date).order_by(StockPrice.date.desc()).first()
            
            if not latest_date_row:
                # 如果資料庫沒資料，回退到預設權值股名單
                target_stocks = POPULAR_STOCKS
            else:
                latest_date = latest_date_row[0]
                # 2. 找出該日期內所有股票
                target_stocks_res = db.query(StockPrice.stock_id).filter(StockPrice.date == latest_date).all()
                target_stocks = [r[0] for r in target_stocks_res]
                
                # 如果資料太少，可能是同步異常，回退到權值股
                if len(target_stocks) < 100:
                    target_stocks = list(set(target_stocks + POPULAR_STOCKS))
        except Exception as e:
            print(f"Error fetching target stocks from DB: {e}")
            target_stocks = POPULAR_STOCKS
        finally:
            db.close()
            
        results_s1: List[ScreenerStock] = []
        results_s2: List[ScreenerStock] = []
        
        def process_stock(stock_id: str):
            # 抓取近 3 個月的日 K 線（足夠計算月線與周均量）
            kline = StockService.get_kline_data(stock_id, period="3mo", interval="1d")
            if kline is None or kline.empty or len(kline) < 25:
                return None
            
            # 取得收盤價序列與成交量
            closes = kline['收盤']
            volumes = kline['成交量']
            
            # 計算指標
            bias20_series = StockService.calculate_bias(closes, 20)
            ma5_vol_series = volumes.rolling(window=5).mean()
            
            # 取得最新與前一日的數值
            latest_close = closes.iloc[-1]
            prev_close = closes.iloc[-2]
            latest_vol = volumes.iloc[-1]
            
            latest_bias20 = bias20_series.iloc[-1]
            latest_ma5_vol = ma5_vol_series.iloc[-1]
            
            if pd.isna(latest_bias20):
                return None
                
            # 計算漲跌幅
            change_percent = ((latest_close - prev_close) / prev_close) * 100
            
            stock_data = ScreenerStock(
                symbol=stock_id,
                name=ScreenerService.get_stock_name(stock_id),
                price=round(float(latest_close), 2),
                change=round(float(change_percent), 2),
                bias20=round(float(latest_bias20), 2)
            )
            
            # 評估策略條件
            is_s1_match = latest_bias20 < -10.0
            
            # 由於我們沒有所有股票的即時成交量（Yahoo有時Volume資料晚一拍或為0），這裡加上一個基礎檢查
            # 放寬動能條件：乖離率 > 0 且 大於月線 且 成交量放大（>5日均量 1.5 倍）且 當日上漲
            is_s2_match = (
                latest_bias20 > 0.0 and 
                latest_vol > (latest_ma5_vol * 1.5) and 
                change_percent > 0
            )

            return stock_data, is_s1_match, is_s2_match

        # 使用執行緒池加速資料抓取
        with ThreadPoolExecutor(max_workers=10) as executor:
            future_to_stock = {executor.submit(process_stock, sid): sid for sid in POPULAR_STOCKS}
            for future in as_completed(future_to_stock):
                stock_id = future_to_stock[future]
                try:
                    res = future.result()
                    if res is None:
                        continue
                        
                    stock_data, is_s1_match, is_s2_match = res
                    
                    if is_s1_match:
                        results_s1.append(stock_data)
                    
                    if is_s2_match:
                        results_s2.append(stock_data)
                        
                except Exception as exc:
                    print(f'{stock_id} generated an exception: {exc}')

        # 排序股票（策略 1 找越跌越深的，策略 2 找漲越多/量越大的）
        results_s1.sort(key=lambda x: x.bias20)
        results_s2.sort(key=lambda x: x.change, reverse=True)
        
        # 組裝成最終的回傳結果
        strategies = [
            StrategyResult(
                id="s1",
                name="乖離率過低 (跌深反彈)",
                description="20 日乖離率 < -10%：股價短期跌破月線太多，偏離均值，尋找跌深超賣的潛在反彈標的。",
                tag="逆勢策略",
                stocks=results_s1[:10]  # 最多回傳前 10 檔
            ),
            StrategyResult(
                id="s2",
                name="乖離率轉正 (強勢動能)",
                description="20 日乖離率 > 0% 且伴隨成交量放大：股價剛站上月線，代表均線以上的賣壓化解，主力準備表態。",
                tag="順勢動能",
                stocks=results_s2[:10]  # 最多回傳前 10 檔
            )
        ]
        
        return strategies

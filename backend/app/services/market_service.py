import yfinance as yf
import pandas as pd
import twstock
from typing import List, Dict, Any

from app.schemas.market import RankingItem, MarketRankingResponse

class MarketService:
    """市場概況數據服務"""

    @staticmethod
    def get_market_rankings(limit: int = 5) -> MarketRankingResponse:
        """
        取得市場排行榜（漲幅、跌幅、成交量）
        針對學習目標，這裏抓取台股代表性權值股與熱門股作為母體池
        
        Args:
            limit: 返回的排行數量
            
        Returns:
            MarketRankingResponse 包含 top_gainers, top_losers, top_volume
        """
        # 台股熱門與權值股代表池 (約 30 檔)
        pool_ids = [
            "2330", "2317", "2454", "2308", "2382", "2881", "2882", "2412", "2891", "2303",
            "2886", "2884", "1216", "2002", "2885", "3231", "2603", "2892", "3045", "5871",
            "2890", "2207", "3008", "2357", "2618", "2609", "3481", "2409", "3037", "3711"
        ]
        
        # 取得名稱映射
        names = {}
        for sid in pool_ids:
            info = twstock.codes.get(sid)
            names[sid] = info.name if info else f"股票 {sid}"
            
        tickers = " ".join([f"{sid}.TW" for sid in pool_ids])
        
        try:
            # 使用 yfinance 批次下載價格與成交量數據 (過去兩天數據以計算漲跌幅)
            data = yf.download(tickers, period="5d", actions=False, progress=False)
            items = []
            
            if not data.empty and 'Close' in data.columns and 'Volume' in data.columns:
                close_data = data['Close']
                volume_data = data['Volume']
                
                for sid in pool_ids:
                    ticker = f"{sid}.TW"
                    # 確認該股票數據存在
                    if ticker in close_data.columns:
                        ticker_close = close_data[ticker].dropna()
                        ticker_vol = volume_data[ticker].dropna()
                        
                        if len(ticker_close) >= 2:
                            prev_close = float(ticker_close.iloc[-2])
                            current_close = float(ticker_close.iloc[-1])
                            volume = int(ticker_vol.iloc[-1])
                            
                            if prev_close > 0:
                                change_percent = ((current_close - prev_close) / prev_close) * 100
                            else:
                                change_percent = 0.0
                                
                            items.append(RankingItem(
                                stock_id=sid,
                                stock_name=names[sid],
                                price=round(current_close, 2),
                                change_percent=round(change_percent, 2),
                                volume=volume
                            ))
                            
            if not items:
                raise ValueError("無法獲取市場數據")
                
            # 排序
            top_gainers = sorted(items, key=lambda x: x.change_percent, reverse=True)[:limit]
            top_losers = sorted(items, key=lambda x: x.change_percent)[:limit]
            top_volume = sorted(items, key=lambda x: x.volume, reverse=True)[:limit]
            
            return MarketRankingResponse(
                top_gainers=top_gainers,
                top_losers=top_losers,
                top_volume=top_volume
            )
            
        except Exception as e:
            print(f"Error fetching market rankings: {e}")
            # 若發生錯誤返回空列表
            return MarketRankingResponse(
                top_gainers=[],
                top_losers=[],
                top_volume=[]
            )

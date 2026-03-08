import os
import sys
import time
import yfinance as yf
import pandas as pd
from datetime import datetime

# 設定執行路徑
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app.db.database import SessionLocal
from app.models.stock_fundamental import StockFundamental
from app.models.stock_eps import StockQuarterlyEPS
from app.models.stock_revenue import StockMonthlyRevenue

def calculate_growth_metrics(revenue_series):
    """
    計算營收連續成長與加速度
    revenue_series: dict, key為年份(int), value為年營收
    例如: {2024: 100, 2023: 90, 2022: 80, 2021: 70}
    """
    years = sorted(revenue_series.keys(), reverse=True)
    if len(years) < 4:
        return 0, 0
    
    y1, y2, y3, y4 = years[0], years[1], years[2], years[3]
    rev1, rev2, rev3, rev4 = revenue_series[y1], revenue_series[y2], revenue_series[y3], revenue_series[y4]
    
    # 計算年增率
    gr12 = (rev1 - rev2) / rev2 * 100 if rev2 > 0 else 0 # 最新一年成長率
    gr23 = (rev2 - rev3) / rev3 * 100 if rev3 > 0 else 0
    gr34 = (rev3 - rev4) / rev4 * 100 if rev4 > 0 else 0
    
    # 6. 連續 2 年營收成長率大於 5%
    is_growth_2yr = 1 if (gr12 > 5.0 and gr23 > 5.0) else 0
    
    # 7. 營收成長率大於近 4 年平均 (其實是過去三次的年增率平均)
    avg_growth = (gr12 + gr23 + gr34) / 3.0
    is_accelerated = 1 if gr12 > avg_growth else 0
    
    return is_growth_2yr, is_accelerated

def backfill():
    db = SessionLocal()
    try:
        # 只撈取符合前 4 個過濾條件的股票，節省時間
        candidates = db.query(StockFundamental).filter(
            StockFundamental.yield_rate >= 5.0,
            StockFundamental.last_revenue >= 1.0,
            StockFundamental.roe_latest >= 10.0,
            StockFundamental.pb_ratio <= 3.0,
            StockFundamental.pb_ratio > 0
        ).all()
        
        total = len(candidates)
        print(f"找到 {total} 檔符合基礎條件的股票，開始回填 yfinance 歷史資料...")
        
        updated_count = 0
        
        for i, stock in enumerate(candidates, 1):
            print(f"[{i}/{total}] 處理 {stock.stock_id} {stock.stock_name} ...")
            ticker_str = f"{stock.stock_id}.TW"
            ticker = yf.Ticker(ticker_str)
            df = ticker.financials
            
            if df.empty:
                ticker_str = f"{stock.stock_id}.TWO"
                ticker = yf.Ticker(ticker_str)
                df = ticker.financials
            
            if df.empty:
                print(f"  找不到 {stock.stock_id} 的財務數據")
                continue
                
            need_update = False
            
            # --- 處理 EPS ---
            if 'Basic EPS' in df.index:
                eps_series = df.loc['Basic EPS'].dropna()
                # yfinance index is usually datetime
                years = sorted([int(str(d)[:4]) for d in eps_series.index], reverse=True)
                
                # 填入 eps_y1 ~ eps_y4
                for idx, y in enumerate(years[:4]):
                    val = eps_series.loc[eps_series.index.year == y].iloc[0]
                    if idx == 0: stock.eps_y1 = float(val)
                    elif idx == 1: stock.eps_y2 = float(val)
                    elif idx == 2: stock.eps_y3 = float(val)
                    elif idx == 3: stock.eps_y4 = float(val)
                    need_update = True
            
            # --- 處理 營收 ---
            if 'Total Revenue' in df.index:
                rev_series = df.loc['Total Revenue'].dropna()
                years = sorted([int(str(d)[:4]) for d in rev_series.index], reverse=True)
                
                rev_dict = {}
                for y in years[:4]:
                    val = rev_series.loc[rev_series.index.year == y].iloc[0]
                    rev_dict[y] = float(val)
                
                if len(rev_dict) >= 4:
                    is_growth_2yr, is_accelerated = calculate_growth_metrics(rev_dict)
                    stock.is_growth_2yr = is_growth_2yr
                    stock.is_accelerated = is_accelerated
                    need_update = True
                    
            if need_update:
                updated_count += 1
                
        db.commit()
        print(f"回填完成！共更新 {updated_count} 筆資料。")
        
    finally:
        db.close()

if __name__ == "__main__":
    backfill()

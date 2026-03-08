import requests
import pandas as pd
from datetime import datetime, date, timedelta
from sqlalchemy.orm import Session
from app.models.stock_fundamental import StockFundamental
from app.models.stock_revenue import StockMonthlyRevenue
from app.models.stock_eps import StockQuarterlyEPS
from app.db.database import SessionLocal


class FundamentalService:
    """基本面數據服務：負責爬取與儲存殖利率、ROE、EPS 等篩選因子"""

    @staticmethod
    def sync_twse_valuation(db: Session, target_date: str = None):
        """同步證交所的本益比、殖利率與淨值比快照"""
        if target_date is None:
            target_date = datetime.now().strftime('%Y%m%d')
        
        print(f"[FundamentalService] Syncing TWSE valuation for {target_date}...")
        url = f"https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU_d?date={target_date}&selectType=ALL&response=json"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Referer': 'https://www.twse.com.tw/zh/page/trading/indices/bwibbu-day.html'
        }
        
        try:
            response = requests.get(url, headers=headers, timeout=15)
            if response.status_code != 200:
                return {"status": "error", "message": f"TWSE API returned {response.status_code}"}
            
            data = response.json()
            if data.get('stat') != 'OK':
                return {"status": "error", "message": f"Data not ready or wrong date: {data.get('stat')}"}
            
            rows = data.get('data', [])
            count = 0
            
            for row in rows:
                stock_id = row[0]
                stock_name = row[1]
                
                # 欄位映射依據今日測試: 3:殖利率, 5:本益比, 6:股價淨值比
                def _clean(val):
                    if val in ['-', 'N/A', '']: return 0.0
                    try: return float(str(val).replace(',', ''))
                    except: return 0.0

                yield_rate = _clean(row[3])
                pe_ratio = _clean(row[5])
                pb_ratio = _clean(row[6])
                
                # 更新或建立
                fundamental = db.query(StockFundamental).filter(StockFundamental.stock_id == stock_id).first()
                if not fundamental:
                    fundamental = StockFundamental(stock_id=stock_id, stock_name=stock_name)
                    db.add(fundamental)
                
                fundamental.yield_rate = yield_rate
                fundamental.pe_ratio = pe_ratio
                fundamental.pb_ratio = pb_ratio
                
                # 計算 ROE (ROE = PB / PE * 100)
                if pe_ratio > 0:
                    fundamental.roe_latest = round((pb_ratio / pe_ratio) * 100, 2)

                fundamental.updated_at = datetime.strptime(target_date, '%Y%m%d').date()
                count += 1
            
            db.commit()
            print(f"[FundamentalService] Successfully updated {count} stocks.")
            return {"status": "success", "count": count}
            
        except Exception as e:
            print(f"[FundamentalService] Error syncing TWSE: {e}")
            return {"status": "error", "message": str(e)}

    @staticmethod
    def sync_mops_revenue(db: Session, year: int = None, month: int = None):
        """同步月營收 (改用 TWSE OpenAPI)"""
        url = "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"
        try:
            print(f"[FundamentalService] Syncing Revenue and Backup to History...")
            headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
            response = requests.get(url, headers=headers, timeout=15)
            if response.status_code != 200:
                return {"status": "error", "message": f"OpenAPI error: {response.status_code}"}
            
            data = response.json()
            count = 0
            
            # 如果未傳入年月，預設為前一個月 (因為營收是次月 10 號前公布)
            if not year or not month:
                today = date.today()
                first = today.replace(day=1)
                last_month = first - timedelta(days=1)
                year = year or last_month.year
                month = month or last_month.month

            for item in data:
                stock_id = item.get('公司代號')
                try:
                    rev_raw = item.get('營業收入-當月營收', '0')
                    rev_val = float(str(rev_raw).replace(',', '')) / 100000.0 # 仟元 -> 億
                    
                    yoy_raw = item.get('營業收入-去年同月增減(%)', '0')
                    yoy_val = float(str(yoy_raw).replace(',', ''))
                    
                    mom_raw = item.get('營業收入-上月增減(%)', '0')
                    mom_val = float(str(mom_raw).replace(',', ''))
                except:
                    continue

                # 1. 更新基本面快照 (Screener 用)
                fundamental = db.query(StockFundamental).filter(StockFundamental.stock_id == stock_id).first()
                if fundamental:
                    fundamental.last_revenue = round(rev_val, 2)
                    fundamental.revenue_growth_yoy = round(yoy_val, 2)
                
                # 2. 存入歷史表 (趨勢圖用)
                rev_history = db.query(StockMonthlyRevenue).filter(
                    StockMonthlyRevenue.stock_id == stock_id,
                    StockMonthlyRevenue.year == year,
                    StockMonthlyRevenue.month == month
                ).first()
                
                if not rev_history:
                    rev_history = StockMonthlyRevenue(
                        stock_id=stock_id,
                        year=year,
                        month=month
                    )
                    db.add(rev_history)
                
                rev_history.revenue = round(rev_val, 2)
                rev_history.revenue_yoy = round(yoy_val, 2)
                rev_history.revenue_mom = round(mom_val, 2)
                rev_history.updated_at = date.today()
                
                count += 1
            
            db.commit()
            return {"status": "success", "count": count}
        except Exception as e:
            print(f"[FundamentalService] Error syncing revenue: {e}")
            return {"status": "error", "message": str(e)}

    @staticmethod
    def sync_mops_performance(db: Session, year: int = None, quarter: int = None):
        """同步 EPS 資料並備份至歷史表"""
        sources = [
            "https://openapi.twse.com.tw/v1/opendata/t187ap06_L_ci",  # 上市
            "https://openapi.twse.com.tw/v1/opendata/t187ap06_O_ci",  # 上櫃
        ]
        
        # 預設為當前季度
        if not year or not quarter:
            today = date.today()
            year = year or today.year
            quarter = quarter or ((today.month - 1) // 3 + 1)

        headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        total_count = 0
        
        for url in sources:
            try:
                response = requests.get(url, headers=headers, timeout=15)
                data = response.json()
                
                for item in data:
                    stock_id = item.get('公司代號')
                    val = (item.get('基本每股盈餘（元）') or 
                           item.get('基本每股盈餘(元)') or 
                           item.get('每股盈餘（元）') or 
                           item.get('每股盈餘(元)') or '0')
                    try:
                        eps = float(str(val).replace(',', ''))
                    except:
                        eps = 0.0
                    
                    # 1. 更新快照
                    fundamental = db.query(StockFundamental).filter(StockFundamental.stock_id == stock_id).first()
                    if fundamental:
                        fundamental.eps_y1 = eps
                    
                    # 2. 存入歷史表
                    eps_history = db.query(StockQuarterlyEPS).filter(
                        StockQuarterlyEPS.stock_id == stock_id,
                        StockQuarterlyEPS.year == year,
                        StockQuarterlyEPS.quarter == quarter
                    ).first()
                    
                    if not eps_history:
                        eps_history = StockQuarterlyEPS(
                            stock_id=stock_id,
                            year=year,
                            quarter=quarter
                        )
                        db.add(eps_history)
                    
                    eps_history.eps = eps
                    eps_history.updated_at = date.today()
                    total_count += 1
                
                db.commit()
            except Exception as e:
                print(f"[FundamentalService] Error syncing performance from {url}: {e}")
                
        return {"status": "success", "count": total_count}

    @staticmethod
    def get_af_choice_stocks(db: Session):
        """實作 AF 精選 (原大師精選 7 法)"""
        results = db.query(StockFundamental).filter(
            # 1. 殖利率大於 5%
            StockFundamental.yield_rate >= 5.0,
            # 2. 月營收大於 1 億
            StockFundamental.last_revenue >= 1.0, 
            # 3. ROE 大於 10%
            StockFundamental.roe_latest >= 10.0,
            # 4. 股價淨值比小於 3 倍 (且大於 0 排除異常)
            StockFundamental.pb_ratio <= 3.0,
            StockFundamental.pb_ratio > 0,
            # 5. EPS 連續 4 年大於 2 元 (包含今年/去年/前年/大前年/四年前)
            StockFundamental.eps_y1 > 2.0,
            StockFundamental.eps_y2 > 2.0,
            StockFundamental.eps_y3 > 2.0,
            StockFundamental.eps_y4 > 2.0,
            
            # 6. 連續 2 年營收成長率大於 5% (預計算欄位 `is_growth_2yr` == 1)
            StockFundamental.is_growth_2yr == 1,
            
            # 7. 營收成長率大於近 4 年平均 (預計算欄位 `is_accelerated` == 1)
            StockFundamental.is_accelerated == 1
        ).order_by(StockFundamental.yield_rate.desc()).limit(15).all()
        
        return results

    @staticmethod
    def backfill_history(db: Session):
        """使用 yfinance 回填符合基礎條件股票的歷史財務數據 (營收與 EPS)"""
        import yfinance as yf
        
        # 只撈取符合前 4 個過濾條件的股票，節省時間
        candidates = db.query(StockFundamental).filter(
            StockFundamental.yield_rate >= 5.0,
            StockFundamental.last_revenue >= 1.0,
            StockFundamental.roe_latest >= 10.0,
            StockFundamental.pb_ratio <= 3.0,
            StockFundamental.pb_ratio > 0
        ).all()
        
        updated_count = 0
        
        def calc_growth(rev_series):
            years = sorted(rev_series.keys(), reverse=True)
            if len(years) < 4: return 0, 0
            y1, y2, y3, y4 = years[0], years[1], years[2], years[3]
            r1, r2, r3, r4 = rev_series[y1], rev_series[y2], rev_series[y3], rev_series[y4]
            gr12 = (r1 - r2) / r2 * 100 if r2 > 0 else 0
            gr23 = (r2 - r3) / r3 * 100 if r3 > 0 else 0
            gr34 = (r3 - r4) / r4 * 100 if r4 > 0 else 0
            
            is_growth = 1 if (gr12 > 5.0 and gr23 > 5.0) else 0
            avg_gr = (gr12 + gr23 + gr34) / 3.0
            is_accel = 1 if gr12 > avg_gr else 0
            return is_growth, is_accel

        for stock in candidates:
            # 簡化爬取，使用 .TW
            ticker = yf.Ticker(f"{stock.stock_id}.TW")
            df = ticker.financials
            if df.empty:
                ticker = yf.Ticker(f"{stock.stock_id}.TWO")
                df = ticker.financials
            
            if df.empty:
                continue
                
            need_update = False
            
            # EPS
            if 'Basic EPS' in df.index:
                eps_series = df.loc['Basic EPS'].dropna()
                years = sorted([int(str(d)[:4]) for d in eps_series.index], reverse=True)
                for idx, y in enumerate(years[:4]):
                    val = float(eps_series.loc[eps_series.index.year == y].iloc[0])
                    if idx == 0: stock.eps_y1 = val
                    elif idx == 1: stock.eps_y2 = val
                    elif idx == 2: stock.eps_y3 = val
                    elif idx == 3: stock.eps_y4 = val
                    need_update = True
                    
            # 營收
            if 'Total Revenue' in df.index:
                rev_series = df.loc['Total Revenue'].dropna()
                years = sorted([int(str(d)[:4]) for d in rev_series.index], reverse=True)
                rev_dict = {y: float(rev_series.loc[rev_series.index.year == y].iloc[0]) for y in years[:4]}
                
                if len(rev_dict) >= 4:
                    i_gr, i_ac = calc_growth(rev_dict)
                    stock.is_growth_2yr = i_gr
                    stock.is_accelerated = i_ac
                    need_update = True
                    
            if need_update:
                updated_count += 1
                
        db.commit()
        return {"status": "success", "count": updated_count}


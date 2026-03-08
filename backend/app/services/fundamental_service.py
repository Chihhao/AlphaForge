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
            StockFundamental.yield_rate >= 5.0,
            StockFundamental.last_revenue >= 1.0,  # 1億
            StockFundamental.pb_ratio <= 3.0,
            StockFundamental.pb_ratio > 0,
            StockFundamental.eps_y1 > 2.0,
            StockFundamental.roe_latest >= 10.0
        ).order_by(StockFundamental.yield_rate.desc()).limit(15).all()
        
        return results

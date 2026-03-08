import requests
import pandas as pd
from datetime import datetime, date
from sqlalchemy.orm import Session
from app.models.stock_fundamental import StockFundamental
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
        """同步月營收 (改用 TWSE OpenAPI, 僅限上市)"""
        # 註: OpenAPI 通常只提供最新一期
        url = "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"
        try:
            print(f"[FundamentalService] Syncing Revenue from TWSE OpenAPI...")
            headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
            response = requests.get(url, headers=headers, timeout=15)
            if response.status_code != 200:
                return {"status": "error", "message": f"OpenAPI error: {response.status_code}"}
            
            data = response.json()
            count = 0
            for item in data:
                stock_id = item.get('公司代號')
                # 欄位: 營業收入-當月營收, 營業收入-上月增減(%), 營業收入-去年同月增減(%)
                try:
                    rev_raw = item.get('營業收入-當月營收', '0')
                    rev_val = float(str(rev_raw).replace(',', '')) / 100000.0 # 仟元 -> 億
                    
                    yoy_raw = item.get('營業收入-去年同月增減(%)', '0')
                    yoy_val = float(str(yoy_raw).replace(',', ''))
                except:
                    continue

                fundamental = db.query(StockFundamental).filter(StockFundamental.stock_id == stock_id).first()
                if fundamental:
                    fundamental.last_revenue = round(rev_val, 2)
                    fundamental.revenue_growth_yoy = round(yoy_val, 2)
                    count += 1
            
            db.commit()
            print(f"[FundamentalService] Updated revenue for {count} stocks.")
            return {"status": "success", "count": count}
        except Exception as e:
            print(f"[FundamentalService] Error syncing revenue: {e}")
            return {"status": "error", "message": str(e)}

    @staticmethod
    def sync_mops_performance(db: Session):
        """同步 OpenAPI 獲利能力資料 (上市、上櫃、公發)"""
        sources = [
            "https://openapi.twse.com.tw/v1/opendata/t187ap06_L_ci",  # 上市
            "https://openapi.twse.com.tw/v1/opendata/t187ap06_O_ci",  # 上櫃
            "https://openapi.twse.com.tw/v1/opendata/t187ap06_P_ci",  # 公發
        ]
        
        headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        total_count = 0
        
        for url in sources:
            try:
                print(f"[FundamentalService] Syncing Performance from {url.split('/')[-1]}...")
                response = requests.get(url, headers=headers, timeout=15)
                data = response.json()
                
                count = 0
                for item in data:
                    stock_id = item.get('公司代號')
                    # 嘗試全形和半形括號
                    val = (item.get('基本每股盈餘（元）') or 
                           item.get('基本每股盈餘(元)') or 
                           item.get('每股盈餘（元）') or 
                           item.get('每股盈餘(元)') or '0')
                    try:
                        eps = float(str(val).replace(',', ''))
                    except:
                        eps = 0.0
                    
                    fundamental = db.query(StockFundamental).filter(StockFundamental.stock_id == stock_id).first()
                    if fundamental:
                        fundamental.eps_y1 = eps
                        count += 1
                
                db.commit()
                print(f"  - Updated {count} stocks from this source.")
                total_count += count
            except Exception as e:
                print(f"  - Error syncing {url}: {e}")
                
        print(f"[FundamentalService] total updated EPS: {total_count}")
        return {"status": "success", "count": total_count}

    @staticmethod
    def get_master_choice_stocks(db: Session):
        """實作大師精選 7 法 (初步整合)"""
        # [Diagnostic]
        total = db.query(StockFundamental).count()
        y_count = db.query(StockFundamental).filter(StockFundamental.yield_rate >= 5.0).count()
        r_count = db.query(StockFundamental).filter(StockFundamental.last_revenue >= 1.0).count()
        pb_count = db.query(StockFundamental).filter(StockFundamental.pb_ratio <= 3.0, StockFundamental.pb_ratio > 0).count()
        eps_count = db.query(StockFundamental).filter(StockFundamental.eps_y1 > 2.0).count()
        roe_count = db.query(StockFundamental).filter(StockFundamental.roe_latest >= 10.0).count()
        print(f"[Diagnostic] 總數: {total}, 殖利率>5%: {y_count}, 營收>1億: {r_count}, PB<3: {pb_count}, EPS>2: {eps_count}, ROE>10%: {roe_count}")
        
        results = db.query(StockFundamental).filter(
            StockFundamental.yield_rate >= 5.0,
            StockFundamental.last_revenue >= 1.0,  # 1億
            StockFundamental.pb_ratio <= 3.0,
            StockFundamental.pb_ratio > 0,
            StockFundamental.eps_y1 > 2.0,
            StockFundamental.roe_latest >= 10.0
        ).order_by(StockFundamental.yield_rate.desc()).limit(15).all()
        
        return results

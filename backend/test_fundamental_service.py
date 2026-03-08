import sys
import os
from sqlalchemy.orm import Session

# 加入專案路徑
sys.path.append(os.path.abspath(os.path.join(os.getcwd(), 'backend')))

from app.db.database import SessionLocal, Base, engine
from app.services.fundamental_service import FundamentalService
from app.models.stock_fundamental import StockFundamental

def test_fundamental_sync():
    # 建立表
    Base.metadata.create_all(bind=engine)
    
    db = SessionLocal()
    try:
        # 1. 同步估值資料 (2026-03-06)
        print("\n[Step 1] 同步證交所估值快照...")
        res_v = FundamentalService.sync_twse_valuation(db, "20260306")
        print(f"結果: {res_v}")
        
        # 2. 同步月營收 (民國 113/02)
        print("\n[Step 2] 同步 MOPS 月營收彙總表 (113/02)...")
        res_r = FundamentalService.sync_mops_revenue(db, year=113, month=2)
        print(f"結果: {res_r}")
        
        # 3. 同步獲利指標 (EPS)
        print("\n[Step 3] 同步 OpenAPI 獲利能力資料...")
        res_p = FundamentalService.sync_mops_performance(db)
        print(f"結果: {res_p}")
        
        # 4. 驗證「大師精選 7 法」整合篩選
        print("\n--- [Step 4] 驗證大師精選條件 (7 法初步整合版) ---")
        # 條件: 殖利率>5%, 營收>1億, P/B<3, EPS>2
        master_stocks = FundamentalService.get_master_choice_stocks(db)
        print(f"符合標的總數: {len(master_stocks)}")
        
        for i, s in enumerate(master_stocks):
            print(f"{i+1}. {s.stock_name}({s.stock_id})")
            print(f"   [條件] 殖利率: {s.yield_rate}%, 營收: {s.last_revenue}億, P/B: {s.pb_ratio}, 去年EPS: {s.eps_y1}")
            
    finally:
        db.close()

if __name__ == "__main__":
    test_fundamental_sync()

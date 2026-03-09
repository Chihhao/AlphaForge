from app.db.database import SessionLocal
from app.models.stock_fundamental import StockFundamental
from app.models.stock_revenue import StockRevenue
from app.models.stock_eps import StockEps
from sqlalchemy import select

db = SessionLocal()
f = db.query(StockFundamental).filter(StockFundamental.stock_id == '6189').first()
print('--- 基本面 (Fundamental) ---')
if f:
    print(f"stock_id: {f.stock_id}")
    print(f"yield_rate: {f.yield_rate}")
    print(f"roe_latest: {f.roe_latest}")
    print(f"pb_ratio: {f.pb_ratio}")
else:
    print("No fundamental data found!")

print('\n--- 營收 (Revenue) ---')
revs = db.query(StockRevenue).filter(StockRevenue.stock_id == '6189').order_by(StockRevenue.year.desc(), StockRevenue.month.desc()).limit(12).all()
for r in revs:
    print(f"{r.year}-{r.month}: {r.revenue} ({r.yoy_growth}%)")

print('\n--- 每股盈餘 (EPS) ---')
epss = db.query(StockEps).filter(StockEps.stock_id == '6189').order_by(StockEps.year.desc(), StockEps.quarter.desc()).all()
for e in epss:
    print(f"{e.year} Q{e.quarter}: {e.eps}")

db.close()

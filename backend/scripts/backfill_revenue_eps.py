"""
回補歷史月營收（36 個月）與季 EPS（12 季）
資料來源：FinMind Open API

用法：
  cd backend
  ./.venv/bin/python scripts/backfill_revenue_eps.py
"""
import os, sys, time, requests
from datetime import date, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app.db.database import SessionLocal
from app.models.stock_revenue import StockMonthlyRevenue
from app.models.stock_eps import StockQuarterlyEPS
from app.models.stock_fundamental import StockFundamental

FINMIND_URL = 'https://api.finmindtrade.com/api/v4/data'


def get_all_stock_ids(db):
    """取得資料庫中所有有基本面資料的股票代號"""
    stocks = db.query(StockFundamental.stock_id).all()
    return [s[0] for s in stocks]


def backfill_revenue(db, stock_ids, start_date='2023-01-01'):
    """從 FinMind 回補月營收"""
    total = len(stock_ids)
    total_inserted = 0

    for i, sid in enumerate(stock_ids, 1):
        try:
            resp = requests.get(FINMIND_URL, params={
                'dataset': 'TaiwanStockMonthRevenue',
                'data_id': sid,
                'start_date': start_date,
            }, timeout=15)
            data = resp.json()
            if data.get('status') != 200 or not data.get('data'):
                continue

            count = 0
            for row in data['data']:
                year = row.get('revenue_year')
                month = row.get('revenue_month')
                rev = row.get('revenue')
                if not year or not month or rev is None:
                    continue

                rev_val = rev / 1e8  # 元 → 億

                # 計算 YoY：找去年同月
                prev_year_rows = [r for r in data['data']
                                  if r.get('revenue_year') == year - 1
                                  and r.get('revenue_month') == month]
                yoy = None
                if prev_year_rows and prev_year_rows[0].get('revenue', 0) > 0:
                    yoy = round((rev / prev_year_rows[0]['revenue'] - 1) * 100, 2)

                rec = db.query(StockMonthlyRevenue).filter(
                    StockMonthlyRevenue.stock_id == sid,
                    StockMonthlyRevenue.year == year,
                    StockMonthlyRevenue.month == month,
                ).first()

                if not rec:
                    rec = StockMonthlyRevenue(stock_id=sid, year=year, month=month)
                    db.add(rec)

                rec.revenue = round(rev_val, 2)
                rec.revenue_yoy = yoy
                rec.updated_at = date.today()
                count += 1

            db.commit()
            total_inserted += count
            if count > 0:
                print(f"  [{i}/{total}] {sid}: {count} 筆月營收")
        except Exception as e:
            print(f"  [{i}/{total}] {sid}: 錯誤 {e}")
            continue

        # FinMind 免費 API 有限速，每 0.5 秒一次
        if i % 5 == 0:
            time.sleep(1)

    return total_inserted


def backfill_eps(db, stock_ids, start_date='2023-01-01'):
    """從 FinMind 回補季 EPS"""
    total = len(stock_ids)
    total_inserted = 0

    for i, sid in enumerate(stock_ids, 1):
        try:
            resp = requests.get(FINMIND_URL, params={
                'dataset': 'TaiwanStockFinancialStatements',
                'data_id': sid,
                'start_date': start_date,
            }, timeout=15)
            data = resp.json()
            if data.get('status') != 200 or not data.get('data'):
                continue

            eps_rows = [r for r in data['data'] if r.get('type') == 'EPS']
            count = 0
            for row in eps_rows:
                d = row.get('date', '')
                val = row.get('value')
                if not d or val is None:
                    continue

                # date format: "2023-03-31"
                parts = d.split('-')
                year = int(parts[0])
                month = int(parts[1])
                quarter = (month - 1) // 3 + 1

                rec = db.query(StockQuarterlyEPS).filter(
                    StockQuarterlyEPS.stock_id == sid,
                    StockQuarterlyEPS.year == year,
                    StockQuarterlyEPS.quarter == quarter,
                ).first()

                if not rec:
                    rec = StockQuarterlyEPS(stock_id=sid, year=year, quarter=quarter)
                    db.add(rec)

                rec.eps = float(val)
                rec.updated_at = date.today()
                count += 1

            db.commit()
            total_inserted += count
            if count > 0:
                print(f"  [{i}/{total}] {sid}: {count} 筆季 EPS")
        except Exception as e:
            print(f"  [{i}/{total}] {sid}: 錯誤 {e}")
            continue

        if i % 5 == 0:
            time.sleep(1)

    return total_inserted


if __name__ == '__main__':
    db = SessionLocal()
    try:
        stock_ids = get_all_stock_ids(db)
        print(f"共 {len(stock_ids)} 檔股票\n")

        print("=== 回補歷史月營收 ===")
        rev_count = backfill_revenue(db, stock_ids)
        print(f"月營收共寫入 {rev_count} 筆\n")

        print("=== 回補歷史季 EPS ===")
        eps_count = backfill_eps(db, stock_ids)
        print(f"季 EPS 共寫入 {eps_count} 筆\n")

        print("✅ 完成！")
    finally:
        db.close()

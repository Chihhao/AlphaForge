"""
同步上市/上櫃股票名稱到 stock_fundamentals
資料來源：TWSE + TPEx 官方 API
只新增不存在的記錄，不覆蓋已有的基本面數據
"""
import os, sys, time, requests
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.db.database import SessionLocal
from app.models.stock_fundamental import StockFundamental

HEADERS = {"User-Agent": "Mozilla/5.0"}

def fetch_twse():
    """上市股票清單"""
    url = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
    r = requests.get(url, headers=HEADERS, timeout=10)
    r.raise_for_status()
    return [(row["Code"], row["Name"]) for row in r.json() if row.get("Code") and row.get("Name")]

def fetch_tpex():
    """上櫃股票清單"""
    url = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes"
    r = requests.get(url, headers=HEADERS, timeout=10)
    r.raise_for_status()
    return [(row["SecuritiesCompanyCode"], row["CompanyName"]) for row in r.json()
            if row.get("SecuritiesCompanyCode") and row.get("CompanyName")]

def main():
    db = SessionLocal()
    try:
        print("抓取上市清單...")
        twse = fetch_twse()
        print(f"  上市：{len(twse)} 檔")

        time.sleep(1)

        print("抓取上櫃清單...")
        tpex = fetch_tpex()
        print(f"  上櫃：{len(tpex)} 檔")

        all_stocks = twse + tpex
        print(f"\n合計 {len(all_stocks)} 檔，開始寫入...")

        added = updated = skipped = 0
        for stock_id, stock_name in all_stocks:
            stock_id = stock_id.strip()
            stock_name = stock_name.strip()
            if not stock_id or not stock_name:
                continue

            existing = db.query(StockFundamental).filter(
                StockFundamental.stock_id == stock_id
            ).first()

            if existing:
                if not existing.stock_name:
                    existing.stock_name = stock_name
                    updated += 1
                else:
                    skipped += 1
            else:
                db.add(StockFundamental(stock_id=stock_id, stock_name=stock_name))
                added += 1

        db.commit()
        print(f"完成：新增 {added} 筆 / 補名稱 {updated} 筆 / 跳過 {skipped} 筆")

        # 驗證 7728
        f = db.query(StockFundamental).filter(StockFundamental.stock_id == "7728").first()
        print(f"\n7728 = {f.stock_name if f else '仍未找到（可能是 TDR 或特殊類型）'}")

    finally:
        db.close()

if __name__ == "__main__":
    main()

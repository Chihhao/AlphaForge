"""
回補歷史月營收（36 個月）與季 EPS（12 季）
資料來源：FinMind Open API（免費版每小時約 600 次請求上限）

用法：
  cd backend
  ./.venv/bin/python scripts/backfill_revenue_eps.py          # 全量回補（自動等待重試直到跑完）
  ./.venv/bin/python scripts/backfill_revenue_eps.py 2330     # 只補指定股票
  ./.venv/bin/python scripts/backfill_revenue_eps.py --resume  # 從上次斷點繼續

NAS 執行：
  docker exec alphaforge-backend python scripts/backfill_revenue_eps.py

遇到 FinMind 限速會自動等待 1 小時後繼續，直到全部跑完。
"""
import os, sys, time, json, requests
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app.db.database import SessionLocal
from app.models.stock_revenue import StockMonthlyRevenue
from app.models.stock_eps import StockQuarterlyEPS
from app.models.stock_fundamental import StockFundamental

FINMIND_URL = 'https://api.finmindtrade.com/api/v4/data'
PROGRESS_FILE = os.path.join(os.path.dirname(__file__), '.backfill_revenue_eps_progress.json')
REQUEST_INTERVAL = 0.6  # 秒，每次請求間隔
RATE_LIMIT_WAIT = 3660  # 秒，遇到限速等待時間（1 小時 + 1 分鐘 buffer）


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def load_progress():
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    return {'completed_ids': []}


def save_progress(progress):
    with open(PROGRESS_FILE, 'w') as f:
        json.dump(progress, f)


def get_all_stock_ids(db):
    stocks = db.query(StockFundamental.stock_id).all()
    return sorted([s[0] for s in stocks])


def finmind_get(params):
    """呼叫 FinMind API，遇到 402 回傳 None 表示限速"""
    resp = requests.get(FINMIND_URL, params=params, timeout=15)
    data = resp.json()
    if data.get('status') == 402:
        return None
    return data


def backfill_one_stock(db, sid):
    """對單檔股票回補月營收與季 EPS（2 次 API 呼叫）
    回傳 (rev_count, eps_count)，若遇到限速回傳 None"""

    # ── 月營收 ──
    time.sleep(REQUEST_INTERVAL)
    data = finmind_get({
        'dataset': 'TaiwanStockMonthRevenue',
        'data_id': sid,
        'start_date': '2022-01-01',  # 多抓 1 年用於算 YoY
    })
    if data is None:
        return None

    rows = data.get('data', [])
    rev_lookup = {}
    for row in rows:
        y, m, r = row.get('revenue_year'), row.get('revenue_month'), row.get('revenue')
        if y and m and r is not None:
            rev_lookup[(y, m)] = r

    rev_count = 0
    for row in rows:
        year = row.get('revenue_year')
        month = row.get('revenue_month')
        rev = row.get('revenue')
        if not year or not month or rev is None or year < 2023:
            continue

        rev_val = rev / 1e8
        prev_rev = rev_lookup.get((year - 1, month))
        yoy = round((rev / prev_rev - 1) * 100, 2) if prev_rev and prev_rev > 0 else None

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
        rev_count += 1

    # ── 季 EPS ──
    time.sleep(REQUEST_INTERVAL)
    data = finmind_get({
        'dataset': 'TaiwanStockFinancialStatements',
        'data_id': sid,
        'start_date': '2023-01-01',
    })
    if data is None:
        # 營收已處理，先 commit 再回報限速
        db.commit()
        return None

    eps_rows = [r for r in data.get('data', []) if r.get('type') == 'EPS']
    eps_count = 0
    for row in eps_rows:
        d = row.get('date', '')
        val = row.get('value')
        if not d or val is None:
            continue
        parts = d.split('-')
        year, month = int(parts[0]), int(parts[1])
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
        eps_count += 1

    db.commit()
    return rev_count, eps_count


if __name__ == '__main__':
    db = SessionLocal()
    try:
        # 解析參數
        args = sys.argv[1:]
        resume = '--resume' in args
        specific_ids = [a for a in args if a != '--resume' and a.isdigit()]

        if specific_ids:
            stock_ids = specific_ids
            log(f"指定股票: {stock_ids}")
        else:
            stock_ids = get_all_stock_ids(db)
            log(f"共 {len(stock_ids)} 檔股票")

        progress = load_progress() if resume else {'completed_ids': []}
        completed = set(progress.get('completed_ids', []))

        if completed:
            log(f"從斷點繼續，已完成 {len(completed)} 檔")

        remaining = [s for s in stock_ids if s not in completed]
        total = len(remaining)
        log(f"待處理 {total} 檔")

        i = 0
        while i < len(remaining):
            sid = remaining[i]
            try:
                result = backfill_one_stock(db, sid)

                if result is None:
                    # 遇到限速，儲存進度並等待
                    save_progress({'completed_ids': list(completed)})
                    resume_time = (datetime.now() + timedelta(seconds=RATE_LIMIT_WAIT)).strftime('%H:%M:%S')
                    log(f"⏳ FinMind 限速，已完成 {len(completed)}/{len(stock_ids)} 檔。等待至 {resume_time} 自動繼續...")
                    time.sleep(RATE_LIMIT_WAIT)
                    log("⏰ 等待結束，繼續回補")
                    continue  # 重試同一檔股票

                rev_c, eps_c = result
                completed.add(sid)
                i += 1
                if rev_c > 0 or eps_c > 0:
                    log(f"  [{len(completed)}/{len(stock_ids)}] {sid}: 營收 {rev_c} 筆, EPS {eps_c} 筆")

                # 每 50 檔存一次進度
                if len(completed) % 50 == 0:
                    save_progress({'completed_ids': list(completed)})

            except Exception as e:
                log(f"  [{i+1}/{total}] {sid}: 錯誤 {e}")
                completed.add(sid)  # 跳過有問題的股票
                i += 1
                continue

        # 全部完成
        if os.path.exists(PROGRESS_FILE):
            os.remove(PROGRESS_FILE)
        log(f"✅ 全部完成！共 {len(completed)} 檔")

    finally:
        db.close()

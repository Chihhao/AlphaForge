"""
回補歷史 PCR（Put/Call Ratio）— 透過 FinMind TaiwanOptionDaily
================================================================
資料來源：FinMind TaiwanOptionDaily (data_id=TXO)
計算方式：篩選一般盤(position) → Put OI 加總 / Call OI 加總

用法：
  cd backend
  ./.venv/bin/python scripts/backfill_pcr_finmind.py              # 回補近 180 天
  ./.venv/bin/python scripts/backfill_pcr_finmind.py --days 365   # 回補近 1 年
  ./.venv/bin/python scripts/backfill_pcr_finmind.py --start-date 2025-01-01  # 指定起始日

NAS 執行：
  docker exec alphaforge-backend python scripts/backfill_pcr_finmind.py

FinMind 免費版每小時 600 次請求，每次查詢一個月的資料（約 12~15 次 API 呼叫 / 年）。
遇到限速會自動等待 1 小時後繼續。
"""
import os, sys, time, requests
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app.db.database import SessionLocal, Base, engine
from app.models.market_pcr import MarketPCR

FINMIND_URL = 'https://api.finmindtrade.com/api/v4/data'
REQUEST_INTERVAL = 0.6
RATE_LIMIT_WAIT = 3660  # 1 小時 + buffer
CHUNK_DAYS = 30  # 每次查詢 30 天


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def finmind_get(params):
    """呼叫 FinMind API，遇到 402 回傳 None 表示限速"""
    resp = requests.get(FINMIND_URL, params=params, timeout=30)
    data = resp.json()
    if data.get('status') == 402:
        return None
    return data


def calc_pcr_from_rows(rows):
    """從 TaiwanOptionDaily 資料計算每日 PCR。
    回傳 {date_str: {'put_oi': int, 'call_oi': int, 'pcr': float}}
    """
    from collections import defaultdict
    daily = defaultdict(lambda: {'put_oi': 0, 'call_oi': 0})

    for row in rows:
        # 只取一般盤 TXO 資料
        if row.get('trading_session') != 'position':
            continue
        if row.get('option_id', row.get('data_id', '')) != 'TXO':
            continue

        d = row.get('date', '')
        oi = row.get('open_interest', 0) or 0
        cp = row.get('call_put', '').lower()

        if cp == 'call':
            daily[d]['call_oi'] += oi
        elif cp == 'put':
            daily[d]['put_oi'] += oi

    result = {}
    for d, v in daily.items():
        if v['call_oi'] > 0:
            v['pcr'] = round(v['put_oi'] / v['call_oi'], 4)
            result[d] = v

    return result


def main():
    import argparse
    parser = argparse.ArgumentParser(description="AlphaForge PCR 回補（FinMind）")
    parser.add_argument("--days", type=int, default=180, help="往前回補天數（預設 180）")
    parser.add_argument("--start-date", type=str, help="開始日期 YYYY-MM-DD")
    parser.add_argument("--end-date", type=str, help="結束日期 YYYY-MM-DD（預設今日）")
    args = parser.parse_args()

    Base.metadata.create_all(bind=engine)

    end_d = date.fromisoformat(args.end_date) if args.end_date else date.today()
    start_d = date.fromisoformat(args.start_date) if args.start_date else end_d - timedelta(days=args.days)

    log("=" * 55)
    log("  AlphaForge PCR 回補（FinMind TaiwanOptionDaily）")
    log(f"  範圍: {start_d} ~ {end_d}")
    log("=" * 55)

    db = SessionLocal()
    total_written = 0
    total_skipped = 0

    try:
        # 先查詢已有的日期，避免重複寫入
        existing_dates = set(
            r[0] for r in db.query(MarketPCR.date).filter(
                MarketPCR.date >= start_d,
                MarketPCR.date <= end_d,
            ).all()
        )
        if existing_dates:
            log(f"  資料庫已有 {len(existing_dates)} 筆 PCR，將跳過")

        # 分段查詢（每次 30 天）
        chunk_start = start_d
        while chunk_start <= end_d:
            chunk_end = min(chunk_start + timedelta(days=CHUNK_DAYS - 1), end_d)
            log(f"查詢 {chunk_start} ~ {chunk_end} ...")

            time.sleep(REQUEST_INTERVAL)
            data = finmind_get({
                'dataset': 'TaiwanOptionDaily',
                'data_id': 'TXO',
                'start_date': chunk_start.isoformat(),
                'end_date': chunk_end.isoformat(),
            })

            if data is None:
                log(f"⚠ 遇到 FinMind 限速，等待 {RATE_LIMIT_WAIT // 60} 分鐘後繼續...")
                time.sleep(RATE_LIMIT_WAIT)
                continue  # 重試同一段

            rows = data.get('data', [])
            if not rows:
                log(f"  此區間無資料")
                chunk_start = chunk_end + timedelta(days=1)
                continue

            daily_pcr = calc_pcr_from_rows(rows)
            written = 0
            skipped = 0

            for date_str, v in sorted(daily_pcr.items()):
                d = date.fromisoformat(date_str)
                if d in existing_dates:
                    skipped += 1
                    continue

                db.add(MarketPCR(
                    date=d,
                    put_oi=v['put_oi'],
                    call_oi=v['call_oi'],
                    pcr=v['pcr'],
                ))
                existing_dates.add(d)
                written += 1

            if written:
                db.commit()

            total_written += written
            total_skipped += skipped
            log(f"  寫入 {written} 筆，跳過 {skipped} 筆")

            chunk_start = chunk_end + timedelta(days=1)

    except KeyboardInterrupt:
        log("使用者中斷，已寫入的資料保留。")
    except Exception as e:
        log(f"回補失敗: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        db.close()

    log("=" * 55)
    log(f"  回補完成：寫入 {total_written} 筆 / 跳過 {total_skipped} 筆")
    log("=" * 55)


if __name__ == "__main__":
    main()

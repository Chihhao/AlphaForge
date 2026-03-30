"""
回補歷史 VIX（CBOE 恐慌指數）
==============================
資料來源：Yahoo Finance (^VIX)

用法：
  cd backend
  ./.venv/bin/python scripts/backfill_vix.py              # 回補近 180 天
  ./.venv/bin/python scripts/backfill_vix.py --days 365    # 回補近 1 年

NAS 執行：
  docker exec alphaforge-backend python scripts/backfill_vix.py
"""
import os, sys, argparse
from datetime import date, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.db.database import SessionLocal, Base, engine
from app.models.market_vix import MarketVIX
from app.services.vix_crawler import fetch_vix


def log(msg):
    from datetime import datetime
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def main():
    parser = argparse.ArgumentParser(description="AlphaForge VIX 回補腳本")
    parser.add_argument("--days", type=int, default=180, help="往前回補天數（預設 180）")
    parser.add_argument("--start-date", type=str, help="開始日期 YYYY-MM-DD")
    parser.add_argument("--end-date", type=str, help="結束日期 YYYY-MM-DD（預設今日）")
    args = parser.parse_args()

    Base.metadata.create_all(bind=engine)

    end_d = date.fromisoformat(args.end_date) if args.end_date else date.today()
    start_d = date.fromisoformat(args.start_date) if args.start_date else end_d - timedelta(days=args.days)

    log("=" * 55)
    log("  AlphaForge VIX 回補（Yahoo Finance）")
    log(f"  範圍: {start_d} ~ {end_d}")
    log("=" * 55)

    db = SessionLocal()
    try:
        existing = set(
            r[0] for r in db.query(MarketVIX.date).filter(
                MarketVIX.date >= start_d,
                MarketVIX.date <= end_d,
            ).all()
        )
        if existing:
            log(f"  資料庫已有 {len(existing)} 筆 VIX，將跳過")

        rows = fetch_vix(start_d, end_d)
        log(f"  Yahoo Finance 回傳 {len(rows)} 筆")

        written = 0
        for r in rows:
            if r["date"] in existing:
                continue
            db.add(MarketVIX(
                date=r["date"],
                open=r["open"],
                high=r["high"],
                low=r["low"],
                close=r["close"],
            ))
            written += 1

        if written:
            db.commit()

        log("=" * 55)
        log(f"  回補完成：寫入 {written} 筆 / 跳過 {len(existing)} 筆")
        log("=" * 55)

    except Exception as e:
        log(f"回補失敗: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()

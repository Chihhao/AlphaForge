"""
AlphaForge 歷史價格回補腳本 (FinMind API)
=========================================
使用 FinMind REST API 從 TWSE/TPEx 官方來源批量回補全市場歷史價格。

用法:
    ./.venv/bin/python3 scripts/backfill_prices.py [--years 3] [--batch-size 50] [--dry-run]

說明:
    - 預設回補 3 年的歷史價格
    - 每批次抓取 50 支股票（每支一次 API call），批次間延遲 6 秒避免速率限制
    - FinMind 免費版限制：每小時 600 次 API 請求
    - 預估全市場 (~1950 支) 回補時間：約 3-4 小時
"""
import argparse
import requests
import pandas as pd
import time
import sys
from datetime import date, timedelta

# 設定 path 以存取 app 模組
sys.path.insert(0, '.')

# --- 內建 log 機制（避免管線 buffering 問題）---
_log_file = None

def log(msg):
    """同時輸出到 stdout 與 log 檔"""
    print(msg, flush=True)
    if _log_file:
        _log_file.write(msg + "\n")
        _log_file.flush()

from app.db.database import SessionLocal
from app.models.stock_price import StockPrice
from sqlalchemy import func


FINMIND_API_URL = "https://api.finmindtrade.com/api/v4/data"


def get_all_stock_ids(db):
    """從現有資料庫取得所有已知的股票代號"""
    ids = db.query(StockPrice.stock_id).distinct().all()
    return sorted([r[0] for r in ids])


def get_existing_date_range(db, stock_id):
    """查詢某支股票目前資料庫中已有的日期範圍"""
    result = db.query(
        func.min(StockPrice.date),
        func.max(StockPrice.date),
        func.count(StockPrice.id)
    ).filter(StockPrice.stock_id == stock_id).first()
    return result[0], result[1], result[2]


def fetch_finmind(stock_id, start_date, end_date, token=None):
    """呼叫 FinMind API 取得單支股票的歷史價格"""
    params = {
        "dataset": "TaiwanStockPrice",
        "data_id": stock_id,
        "start_date": start_date,
        "end_date": end_date,
    }
    if token:
        params["token"] = token

    try:
        resp = requests.get(FINMIND_API_URL, params=params, timeout=30)
        data = resp.json()

        if data.get("status") != 200:
            msg = data.get("msg", "Unknown error")
            # 檢查是否遇到速率限制
            if "request limit" in str(msg).lower() or data.get("status") == 402:
                return None, "RATE_LIMIT"
            return None, msg

        df = pd.DataFrame(data["data"])
        if df.empty:
            return df, None

        # 欄位映射: FinMind -> StockPrice
        result = pd.DataFrame({
            "stock_id": df["stock_id"],
            "date": pd.to_datetime(df["date"]).dt.date,
            "open": df["open"].astype(float),
            "high": df["max"].astype(float),
            "low": df["min"].astype(float),
            "close": df["close"].astype(float),
            "adj_close": df["close"].astype(float),  # 原始價格，未調整
            "volume": df["Trading_Volume"].astype(int),
        })

        # 過濾無效資料（收盤價為 0）
        result = result[result["close"] > 0]

        return result, None

    except requests.exceptions.Timeout:
        return None, "TIMEOUT"
    except Exception as e:
        return None, str(e)


def backfill_stock(db, stock_id, start_date, end_date, dry_run=False):
    """回補單支股票的歷史價格，跳過已存在的日期"""
    df, err = fetch_finmind(stock_id, str(start_date), str(end_date))

    if err == "RATE_LIMIT":
        return -1, 0  # 回傳 -1 表示需要等待

    if err:
        return 0, 0  # 跳過錯誤的股票

    if df is None or df.empty:
        return 0, 0

    # 確認哪些日期已存在以避免重複
    existing_dates = set()
    existing = db.query(StockPrice.date).filter(
        StockPrice.stock_id == stock_id,
        StockPrice.date >= start_date,
        StockPrice.date <= end_date
    ).all()
    existing_dates = {r[0] for r in existing}

    # 濾除已存在的日期
    new_records = df[~df["date"].isin(existing_dates)]

    if new_records.empty:
        return 0, len(df)

    if dry_run:
        return len(new_records), len(existing_dates)

    # 批量寫入
    objects = [
        StockPrice(
            stock_id=row["stock_id"],
            date=row["date"],
            open=row["open"],
            high=row["high"],
            low=row["low"],
            close=row["close"],
            adj_close=row["adj_close"],
            volume=row["volume"]
        )
        for _, row in new_records.iterrows()
    ]

    from app.models.stock_price import bulk_upsert_stock_prices
    chunk_size = 500
    for i in range(0, len(objects), chunk_size):
        bulk_upsert_stock_prices(db, objects[i:i + chunk_size])

    db.commit()
    return len(new_records), len(existing_dates)


def main():
    parser = argparse.ArgumentParser(description="AlphaForge 歷史價格回補腳本")
    parser.add_argument("--years", type=int, default=3, help="回補年數 (預設 3)")
    parser.add_argument("--batch-size", type=int, default=50, help="每批次處理的股票數 (預設 50)")
    parser.add_argument("--delay", type=float, default=0.5, help="每支股票間的延遲秒數 (預設 0.5)")
    parser.add_argument("--dry-run", action="store_true", help="只統計不寫入")
    parser.add_argument("--token", type=str, default=None, help="FinMind API token (可提高速率限制)")
    parser.add_argument("--stock-ids", type=str, default=None, help="指定股票代號 (逗號分隔，如 2330,2317,2454)")
    parser.add_argument("--log-file", type=str, default="scripts/backfill_progress.log", help="Log 檔案路徑")
    args = parser.parse_args()

    # 設定 log 檔
    global _log_file
    _log_file = open(args.log_file, "w", encoding="utf-8")

    end_date = date.today()
    start_date = end_date - timedelta(days=args.years * 365)

    log("=" * 60)
    log("AlphaForge 歷史價格回補腳本 (FinMind API)")
    log("=" * 60)
    log(f"  回補範圍: {start_date} ~ {end_date} ({args.years} 年)")
    log(f"  模式: {'乾跑 (不寫入)' if args.dry_run else '正式寫入'}")
    log("")

    db = SessionLocal()

    try:
        # 取得要回補的股票清單
        if args.stock_ids:
            stock_ids = args.stock_ids.split(",")
            log(f"  指定股票: {len(stock_ids)} 支")
        else:
            stock_ids = get_all_stock_ids(db)
            log(f"  全市場股票: {len(stock_ids)} 支")

        log(f"  每支延遲: {args.delay} 秒")
        log(f"  預估時間: {len(stock_ids) * args.delay / 60:.1f} 分鐘 (不含速率限制等待)")
        log("")

        total_inserted = 0
        total_skipped = 0
        errors = []
        rate_limit_waits = 0

        for i, sid in enumerate(stock_ids):
            # 進度顯示
            progress = f"[{i + 1}/{len(stock_ids)}]"

            inserted, skipped = backfill_stock(
                db, sid, start_date, end_date, dry_run=args.dry_run
            )

            # 處理速率限制（FinMind 免費版每小時 600 次）
            if inserted == -1:
                rate_limit_waits += 1
                for retry in range(3):
                    wait_time = 600  # 等待 10 分鐘（FinMind 限制是每小時重置）
                    log(f"  {progress} ⚠️  速率限制！等待 {wait_time // 60} 分鐘後重試 (第 {retry + 1}/3 次)...")
                    time.sleep(wait_time)
                    inserted, skipped = backfill_stock(
                        db, sid, start_date, end_date, dry_run=args.dry_run
                    )
                    if inserted != -1:
                        break
                if inserted == -1:
                    log(f"  {progress} ❌ {sid}: 仍被限流，跳過")
                    errors.append(sid)
                    continue

            total_inserted += max(inserted, 0)
            total_skipped += skipped

            if inserted > 0:
                log(f"  {progress} ✅ {sid}: 新增 {inserted} 筆，已有 {skipped} 筆")
            elif inserted == 0 and skipped > 0:
                log(f"  {progress} ⏭️  {sid}: 資料已齊全 ({skipped} 筆)")
            else:
                log(f"  {progress} ⚠️  {sid}: 無資料 (可能已下市)")

            time.sleep(args.delay)

            # 每 100 支印一次摘要
            if (i + 1) % 100 == 0:
                log(f"\n  --- 進度報告: {i + 1}/{len(stock_ids)} | 已新增 {total_inserted} 筆 | 限流 {rate_limit_waits} 次 ---\n")

    except KeyboardInterrupt:
        log(f"\n\n⚠️  使用者中斷！已處理到第 {i + 1} 支。")
    finally:
        db.close()

    log("")
    log("=" * 60)
    log("回補完成")
    log("=" * 60)
    log(f"  新增紀錄: {total_inserted} 筆")
    log(f"  跳過紀錄: {total_skipped} 筆")
    log(f"  速率限制等待: {rate_limit_waits} 次")
    if errors:
        log(f"  失敗股票: {', '.join(errors)}")
    
    if _log_file:
        _log_file.close()


if __name__ == "__main__":
    main()

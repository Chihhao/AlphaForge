"""
借券賣出 + 當沖比率歷史回補腳本
================================
用法:
    python scripts/backfill_sbl_daytrade.py [--days 730] [--start-date YYYY-MM-DD]

資料來源：
  - 借券：TWSE TWT93U（上市），TPEx（上櫃）
  - 當沖：TWSE TWTB4U（上市），TPEx（上櫃）
"""
import argparse
import logging
import os
import re
import sys
import time
from datetime import date, timedelta
from typing import Optional

import pandas as pd
import requests
from sqlalchemy import delete

sys.path.insert(0, os.getcwd())

from app.db.database import SessionLocal, Base, engine
from app.models.stock_sbl_data import StockSBLData
from app.models.stock_day_trading import StockDayTrading

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

_HEADERS = {"User-Agent": "Mozilla/5.0 (AlphaForge backfill)"}


def _clean_num(val) -> Optional[int]:
    """清理數字字串：移除逗號、空白，轉 int"""
    if val is None:
        return None
    s = str(val).strip().replace(",", "").replace("--", "")
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# TWSE 借券 (TWT93U)
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_twse_sbl(target_date: date) -> pd.DataFrame:
    """
    TWSE TWT93U: 融券+借券賣出每日餘額
    欄位: 代號, 名稱,
          融券[前日餘額, 賣出, 買進, 現券, 今日餘額, 限額],
          借券[前日餘額, 當日賣出, 當日還券, 調整, 當日餘額, 可限額],
          備註
    注意：TWT93U 單位是「股」，需除以 1000 轉換為「張」
    """
    date_str = target_date.strftime("%Y%m%d")
    url = "https://www.twse.com.tw/exchangeReport/TWT93U"
    params = {"response": "json", "date": date_str}

    try:
        resp = requests.get(url, params=params, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning(f"  SBL 請求失敗 {date_str}: {e}")
        return pd.DataFrame()

    rows = data.get("data", [])
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    # 過濾 4 碼普通股
    df = df[df[0].astype(str).str.strip().str.match(r"^[1-9]\d{3}$", na=False)].copy()
    if df.empty:
        return pd.DataFrame()

    result = pd.DataFrame()
    result["stock_id"] = df[0].astype(str).str.strip()
    # 借券賣出區段（index 8~12），單位：股 → 張
    result["sbl_sell_today"] = df[9].apply(_clean_num)   # 當日借券賣出
    result["sbl_buy_today"] = df[10].apply(_clean_num)   # 當日借券還券
    result["sbl_sell_balance"] = df[12].apply(_clean_num)  # 借券賣出餘額

    # 股→張
    for col in ["sbl_sell_today", "sbl_buy_today", "sbl_sell_balance"]:
        result[col] = result[col].apply(lambda x: x // 1000 if x is not None else None)

    return result.reset_index(drop=True)


# ═══════════════════════════════════════════════════════════════════════════════
# TPEx 借券
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_tpex_sbl(target_date: date) -> pd.DataFrame:
    """上櫃借券賣出"""
    roc_year = target_date.year - 1911
    date_str = f"{roc_year}/{target_date.strftime('%m/%d')}"
    url = "https://www.tpex.org.tw/web/stock/margin_trading/margin_sbl/margin_sbl_result.php"
    params = {"l": "zh-tw", "d": date_str, "o": "json"}

    try:
        resp = requests.get(url, params=params, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning(f"  TPEx SBL 請求失敗 {date_str}: {e}")
        return pd.DataFrame()

    rows = data.get("aaData", [])
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df = df[df[0].astype(str).str.strip().str.match(r"^[1-9]\d{3}$", na=False)].copy()
    if df.empty:
        return pd.DataFrame()

    result = pd.DataFrame()
    result["stock_id"] = df[0].astype(str).str.strip()
    # TPEx 借券欄位位置可能不同，先嘗試常見結構
    # 通常: 代號, 名稱, 前日餘額, 賣出, 還券, 調整, 今日餘額, ...
    result["sbl_sell_today"] = df[3].apply(_clean_num) if len(df.columns) > 3 else None
    result["sbl_buy_today"] = df[4].apply(_clean_num) if len(df.columns) > 4 else None
    result["sbl_sell_balance"] = df[6].apply(_clean_num) if len(df.columns) > 6 else None

    return result.reset_index(drop=True)


# ═══════════════════════════════════════════════════════════════════════════════
# TWSE 當沖 (TWTB4U)
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_twse_daytrade(target_date: date) -> pd.DataFrame:
    """
    TWSE TWTB4U: 當日沖銷交易
    tables[1] 欄位: 證券代號, 證券名稱, 暫停註記, 當日沖銷交易成交股數,
                    當日沖銷交易買進成交金額, 當日沖銷交易賣出成交金額
    """
    date_str = target_date.strftime("%Y%m%d")
    url = "https://www.twse.com.tw/exchangeReport/TWTB4U"
    params = {"response": "json", "date": date_str, "selectType": "ALL"}

    try:
        resp = requests.get(url, params=params, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning(f"  當沖請求失敗 {date_str}: {e}")
        return pd.DataFrame()

    # 找到有「證券代號」的 table
    rows = None
    for t in data.get("tables", []):
        fields = t.get("fields", [])
        if fields and "證券代號" in fields:
            rows = t.get("data", [])
            break

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df = df[df[0].astype(str).str.strip().str.match(r"^[1-9]\d{3}$", na=False)].copy()
    if df.empty:
        return pd.DataFrame()

    result = pd.DataFrame()
    result["stock_id"] = df[0].astype(str).str.strip()
    result["day_trade_volume"] = df[3].apply(_clean_num)  # 當沖成交股數

    return result.reset_index(drop=True)


# ═══════════════════════════════════════════════════════════════════════════════
# TPEx 當沖
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_tpex_daytrade(target_date: date) -> pd.DataFrame:
    """上櫃當沖"""
    roc_year = target_date.year - 1911
    date_str = f"{roc_year}/{target_date.strftime('%m/%d')}"
    url = "https://www.tpex.org.tw/web/stock/aftertrading/daily_trading_info/st43_result.php"
    params = {"l": "zh-tw", "d": date_str, "o": "json"}

    try:
        resp = requests.get(url, params=params, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning(f"  TPEx 當沖請求失敗 {date_str}: {e}")
        return pd.DataFrame()

    rows = data.get("aaData", [])
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df = df[df[0].astype(str).str.strip().str.match(r"^[1-9]\d{3}$", na=False)].copy()
    if df.empty:
        return pd.DataFrame()

    result = pd.DataFrame()
    result["stock_id"] = df[0].astype(str).str.strip()
    # TPEx 當沖：通常 [3] 是當沖成交股數
    result["day_trade_volume"] = df[3].apply(_clean_num) if len(df.columns) > 3 else None

    return result.reset_index(drop=True)


# ═══════════════════════════════════════════════════════════════════════════════
# 寫入 DB
# ═══════════════════════════════════════════════════════════════════════════════

def save_sbl(db, target_date: date, df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    # 刪除已有的
    db.execute(
        delete(StockSBLData).where(
            StockSBLData.date == target_date,
            StockSBLData.stock_id.in_(df["stock_id"].tolist()),
        )
    )
    records = []
    for _, row in df.iterrows():
        records.append(StockSBLData(
            stock_id=row["stock_id"],
            date=target_date,
            sbl_sell_balance=row.get("sbl_sell_balance"),
            sbl_sell_today=row.get("sbl_sell_today"),
            sbl_buy_today=row.get("sbl_buy_today"),
        ))
    db.bulk_save_objects(records)
    db.commit()
    return len(records)


def save_daytrade(db, target_date: date, df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    db.execute(
        delete(StockDayTrading).where(
            StockDayTrading.date == target_date,
            StockDayTrading.stock_id.in_(df["stock_id"].tolist()),
        )
    )
    records = []
    for _, row in df.iterrows():
        records.append(StockDayTrading(
            stock_id=row["stock_id"],
            date=target_date,
            day_trade_buy_volume=row.get("day_trade_volume"),
            day_trade_sell_volume=row.get("day_trade_volume"),
        ))
    db.bulk_save_objects(records)
    db.commit()
    return len(records)


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="借券賣出 + 當沖比率回補")
    parser.add_argument("--days", type=int, default=730, help="往前回補天數（預設 730 = 2年）")
    parser.add_argument("--start-date", type=str, help="開始日期 YYYY-MM-DD")
    parser.add_argument("--end-date", type=str, help="結束日期 YYYY-MM-DD")
    parser.add_argument("--sbl-only", action="store_true", help="只回補借券")
    parser.add_argument("--daytrade-only", action="store_true", help="只回補當沖")
    args = parser.parse_args()

    Base.metadata.create_all(bind=engine)

    end_d = date.fromisoformat(args.end_date) if args.end_date else date.today()
    start_d = date.fromisoformat(args.start_date) if args.start_date else end_d - timedelta(days=args.days)

    do_sbl = not args.daytrade_only
    do_dt = not args.sbl_only

    logger.info("=" * 55)
    logger.info("  借券賣出 + 當沖比率回補")
    logger.info(f"  範圍: {start_d} ~ {end_d}")
    logger.info(f"  借券: {'✓' if do_sbl else '✗'}  當沖: {'✓' if do_dt else '✗'}")
    logger.info("=" * 55)

    total_sbl = 0
    total_dt = 0
    current = start_d

    while current <= end_d:
        if current.weekday() >= 5:
            current += timedelta(days=1)
            continue

        db = SessionLocal()
        try:
            sbl_n = 0
            dt_n = 0

            if do_sbl:
                sbl_twse = fetch_twse_sbl(current)
                sbl_tpex = fetch_tpex_sbl(current)
                sbl_all = pd.concat([sbl_twse, sbl_tpex], ignore_index=True) if not sbl_tpex.empty else sbl_twse
                sbl_n = save_sbl(db, current, sbl_all)
                total_sbl += sbl_n

            time.sleep(2)  # API 友善

            if do_dt:
                dt_twse = fetch_twse_daytrade(current)
                dt_tpex = fetch_tpex_daytrade(current)
                dt_all = pd.concat([dt_twse, dt_tpex], ignore_index=True) if not dt_tpex.empty else dt_twse
                dt_n = save_daytrade(db, current, dt_all)
                total_dt += dt_n

            if sbl_n > 0 or dt_n > 0:
                logger.info(f"  {current}  SBL={sbl_n:>4d}  DayTrade={dt_n:>4d}")
            else:
                logger.info(f"  {current}  無資料（非交易日）")

        except Exception as e:
            logger.error(f"  {current} 錯誤: {e}")
        finally:
            db.close()

        time.sleep(3)  # TWSE 限制 3req/5sec
        current += timedelta(days=1)

    logger.info("=" * 55)
    logger.info(f"  完成！SBL={total_sbl:,} 筆, DayTrade={total_dt:,} 筆")
    logger.info("=" * 55)


if __name__ == "__main__":
    main()

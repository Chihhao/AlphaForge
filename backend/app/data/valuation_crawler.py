"""TWSE 個股日本益比/殖利率/股價淨值比 crawler。

TWSE 公開 API: https://www.twse.com.tw/exchangeReport/BWIBBU_d?response=json&date=YYYYMMDD
- 每日一份, 上市股 ~1000-1100 檔 (上櫃另有 TPEx endpoint, 第二階段擴)
- '-' 表示無資料 (虧損公司 PE = '-')
- date 用西元 YYYYMMDD; 假日無資料 (stat='OK' 但 data 空, 或 stat 含「無資料」)

純資料 fetch + parse, 不負責 DB 寫入 (caller 自己 upsert)。
"""
from __future__ import annotations

import time
from datetime import date as date_type, timedelta

import httpx


TWSE_BWIBBU_URL = "https://www.twse.com.tw/exchangeReport/BWIBBU_d"


def _safe_float(s: str) -> float | None:
    s = str(s).strip().replace(",", "")
    if s in ("", "-", "N/A"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _safe_int(s: str) -> int | None:
    s = str(s).strip()
    if s in ("", "-", "N/A"):
        return None
    try:
        return int(s)
    except ValueError:
        return None


def fetch_valuation_daily(d: date_type, _transport: httpx.BaseTransport | None = None) -> list[dict]:
    """Fetch 一天 TWSE 個股本益比/殖利率/股價淨值比。

    Return: [{"stock_id": "1101", "date": d, "close": 24.55, "yield_rate": 3.26,
              "pe_ratio": None, "pb_ratio": 0.78, "dividend_year": 114,
              "report_period": "115/1"}, ...]
    假日 / 無資料 → []。
    """
    date_str = d.strftime("%Y%m%d")
    with httpx.Client(timeout=30.0, transport=_transport) as client:
        r = client.get(TWSE_BWIBBU_URL, params={"response": "json", "date": date_str})
    r.raise_for_status()
    body = r.json()
    if body.get("stat") != "OK":
        return []
    rows_raw = body.get("data", [])
    if not rows_raw:
        return []
    out = []
    for row in rows_raw:
        # fields: [證券代號, 證券名稱, 收盤價, 殖利率(%), 股利年度, 本益比, 股價淨值比, 財報年/季]
        if len(row) < 8:
            continue
        out.append({
            "stock_id": str(row[0]).strip(),
            "date": d,
            "close": _safe_float(row[2]),
            "yield_rate": _safe_float(row[3]),
            "dividend_year": _safe_int(row[4]),
            "pe_ratio": _safe_float(row[5]),
            "pb_ratio": _safe_float(row[6]),
            "report_period": str(row[7]).strip() if row[7] else None,
        })
    return out


def backfill_valuation(
    start: date_type,
    end: date_type,
    *,
    upsert_callback,
    sleep_sec: float = 1.0,
) -> dict:
    """Daily loop fetch + 餵給 upsert_callback。

    Args:
        start, end: 日期區間 (inclusive)
        upsert_callback: function(rows: list[dict]) -> None, caller 負責寫 DB
        sleep_sec: TWSE rate limit, 預設 1 秒/天

    Return: {"days_processed": N, "days_with_data": M, "rows_total": K}
    """
    days_processed = 0
    days_with_data = 0
    rows_total = 0
    d = start
    while d <= end:
        days_processed += 1
        # 跳過週六日
        if d.weekday() < 5:
            try:
                rows = fetch_valuation_daily(d)
            except Exception as e:
                print(f"  {d}: error {type(e).__name__}: {e}")
                rows = []
            if rows:
                days_with_data += 1
                rows_total += len(rows)
                upsert_callback(rows)
            time.sleep(sleep_sec)
        d += timedelta(days=1)
    return {
        "days_processed": days_processed,
        "days_with_data": days_with_data,
        "rows_total": rows_total,
    }

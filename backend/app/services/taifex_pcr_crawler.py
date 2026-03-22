"""
TAIFEX 選擇權 Put/Call Ratio 爬蟲

資料來源：TAIFEX 台灣期貨交易所
  https://www.taifex.com.tw/cht/3/callsAndPutsDate

PCR = 台指選擇權 Put 未平倉口數 / Call 未平倉口數
高 PCR（>1.5）= 市場偏空 / 恐慌；低 PCR（<0.8）= 市場偏多 / 過熱
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_TAIFEX_URL = "https://www.taifex.com.tw/cht/3/callsAndPutsDate"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; AlphaForge/1.0)",
    "Referer": "https://www.taifex.com.tw/",
}


def fetch_taifex_pcr(target_date: date) -> Optional[dict]:
    """抓取指定日期的台指選擇權 PCR。

    回傳 dict: {'date': date, 'put_oi': int, 'call_oi': int, 'pcr': float}
    抓取失敗或無資料時回傳 None。

    注意：TAIFEX 只提供近期資料，過舊的日期可能回傳空白。
    """
    date_str = target_date.strftime("%Y/%m/%d")
    try:
        resp = requests.post(
            _TAIFEX_URL,
            data={
                "queryStartDate": date_str,
                "queryEndDate": date_str,
            },
            headers=_HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        resp.encoding = "utf-8"
    except Exception as e:
        logger.warning(f"[PCR] 抓取 {date_str} 失敗: {e}")
        return None

    return _parse_pcr(resp.text, target_date)


def _parse_pcr(html: str, target_date: date) -> Optional[dict]:
    """解析 TAIFEX HTML 表格，抽取台指選擇權的 Put/Call OI。

    TAIFEX 回傳的 HTML 包含多個商品的 OI 表格。
    我們只取「台指選擇權」（TXO）的 PUT 和 CALL 合計口數。
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        logger.error("[PCR] 需要安裝 beautifulsoup4：pip install beautifulsoup4")
        return None

    try:
        soup = BeautifulSoup(html, "html.parser")
        tables = soup.find_all("table", class_="table_f")

        put_oi = 0
        call_oi = 0

        for table in tables:
            rows = table.find_all("tr")
            for row in rows:
                cells = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
                if not cells:
                    continue
                # 尋找包含 "臺指選擇權" 或 "TXO" 的行
                row_text = " ".join(cells)
                if "臺指選擇權" not in row_text and "TXO" not in row_text:
                    continue
                # 解析：CALL 合計 OI 和 PUT 合計 OI
                # 典型欄位順序：商品名稱, CALL/PUT, 到期月, OI...
                for i, cell in enumerate(cells):
                    cell_clean = cell.replace(",", "")
                    if "CALL" in cell.upper() and i + 1 < len(cells):
                        try:
                            val = int(cells[i + 1].replace(",", ""))
                            call_oi += val
                        except (ValueError, IndexError):
                            pass
                    elif "PUT" in cell.upper() and i + 1 < len(cells):
                        try:
                            val = int(cells[i + 1].replace(",", ""))
                            put_oi += val
                        except (ValueError, IndexError):
                            pass

        if call_oi == 0:
            logger.info(f"[PCR] {target_date}: 無法解析 CALL OI（非交易日或資料格式變更）")
            return None

        pcr = round(put_oi / call_oi, 4) if call_oi > 0 else None
        logger.info(f"[PCR] {target_date}: PUT={put_oi:,} CALL={call_oi:,} PCR={pcr}")
        return {
            "date": target_date,
            "put_oi": put_oi,
            "call_oi": call_oi,
            "pcr": pcr,
        }
    except Exception as e:
        logger.warning(f"[PCR] 解析 {target_date} 失敗: {e}")
        return None


def sync_pcr(db, days_back: int = 5) -> int:
    """同步最近 days_back 個交易日的 PCR 資料。

    冪等：已存在的日期跳過。
    回傳成功寫入筆數。
    """
    from app.models.market_pcr import MarketPCR

    today = date.today()
    written = 0

    for delta in range(days_back):
        target = today - timedelta(days=delta)
        if target.weekday() >= 5:  # 跳過週末
            continue

        # 已存在則跳過
        exists = db.query(MarketPCR).filter(MarketPCR.date == target).first()
        if exists:
            continue

        result = fetch_taifex_pcr(target)
        if result is None:
            continue

        db.add(MarketPCR(
            date=result["date"],
            put_oi=result["put_oi"],
            call_oi=result["call_oi"],
            pcr=result["pcr"],
        ))
        written += 1

    if written:
        db.commit()
        logger.info(f"[PCR] 寫入 {written} 筆 PCR 資料")
    return written

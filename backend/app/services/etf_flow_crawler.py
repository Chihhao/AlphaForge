"""
ETF 申贖張數爬蟲

資料來源：TWSE ETF 申購買回清單
  https://www.twse.com.tw/fund/TWT38U?response=json&date=YYYYMMDD&stockNo=0050

ETF 淨申購 = 申購張數 - 贖回張數
  正值 = 機構買超 ETF = 資金淨流入
  負值 = 機構賣超 ETF = 資金淨流出

追蹤標的：0050（元大台灣50，最具代表性的大盤 ETF）
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

import requests

logger = logging.getLogger(__name__)

ETF_TARGETS = ["0050"]  # 可擴充至 00878, 006208

_TWSE_ETF_URL = "https://www.twse.com.tw/fund/TWT38U"
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; AlphaForge/1.0)"}


def fetch_etf_flow(etf_id: str, target_date: date) -> Optional[dict]:
    """抓取指定 ETF 在指定日期的申贖資料。

    回傳 dict: {'date': date, 'etf_id': str, 'creation': int, 'redemption': int, 'net_flow': int}
    失敗或無資料時回傳 None。
    """
    date_str = target_date.strftime("%Y%m%d")
    try:
        resp = requests.get(
            _TWSE_ETF_URL,
            params={"response": "json", "date": date_str, "stockNo": etf_id},
            headers=_HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning(f"[ETFFlow] 抓取 {etf_id} {date_str} 失敗: {e}")
        return None

    return _parse_etf_flow(data, etf_id, target_date)


def _parse_etf_flow(data: dict, etf_id: str, target_date: date) -> Optional[dict]:
    """解析 TWSE ETF 申贖 JSON。

    TWSE JSON 格式：
    {
      "stat": "OK",
      "data": [
        ["日期", "申購受益單位數", "買回受益單位數", ...]
      ]
    }
    """
    try:
        if data.get("stat") != "OK":
            return None

        rows = data.get("data", [])
        if not rows:
            return None

        # 找目標日期的資料（日期格式為民國年 e.g. "114/03/22"）
        target_roc = f"{target_date.year - 1911}/{target_date.month:02d}/{target_date.day:02d}"

        for row in rows:
            if not row or row[0] != target_roc:
                continue

            # 欄位：日期, 申購受益單位數, 買回受益單位數, ...
            # 受益單位數 / 1000 ≈ 張數（ETF 一單位 = 1000 股，1 張 = 1000 股）
            creation_units  = int(str(row[1]).replace(",", "")) if len(row) > 1 else 0
            redemption_units = int(str(row[2]).replace(",", "")) if len(row) > 2 else 0

            # 轉換為張（1 張 = 1000 受益單位）
            creation   = creation_units   // 1000
            redemption = redemption_units // 1000
            net_flow   = creation - redemption

            logger.info(f"[ETFFlow] {etf_id} {target_date}: 申購={creation:,} 贖回={redemption:,} 淨流入={net_flow:,} 張")
            return {
                "date": target_date,
                "etf_id": etf_id,
                "creation": creation,
                "redemption": redemption,
                "net_flow": net_flow,
            }

        logger.info(f"[ETFFlow] {etf_id} {target_date}: 無資料（非交易日或尚未公布）")
        return None

    except Exception as e:
        logger.warning(f"[ETFFlow] 解析 {etf_id} {target_date} 失敗: {e}")
        return None


def sync_etf_flows(db, days_back: int = 5) -> int:
    """同步最近 days_back 個交易日的 ETF 申贖資料。

    冪等：已存在的跳過。
    回傳成功寫入筆數。
    """
    from app.models.etf_flow import ETFFlow

    today = date.today()
    written = 0

    for etf_id in ETF_TARGETS:
        for delta in range(days_back):
            target = today - timedelta(days=delta)
            if target.weekday() >= 5:
                continue

            exists = (
                db.query(ETFFlow)
                .filter(ETFFlow.etf_id == etf_id, ETFFlow.date == target)
                .first()
            )
            if exists:
                continue

            result = fetch_etf_flow(etf_id, target)
            if result is None:
                continue

            db.add(ETFFlow(**result))
            written += 1

    if written:
        db.commit()
        logger.info(f"[ETFFlow] 寫入 {written} 筆 ETF 申贖資料")
    return written

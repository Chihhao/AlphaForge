"""
ETF 外資買賣超爬蟲

資料來源：TWSE 外資及陸資買賣超彙總表
  https://www.twse.com.tw/fund/TWT38U?response=json&date=YYYYMMDD

注意：TWT38U 回傳的是「外資及陸資買賣超彙總表」，非 ETF 申購/買回受益單位數。
  net_flow = 外資淨買超股數 / 1000（轉換為張）
  正值 = 外資買超 0050 = 看多市場訊號
  負值 = 外資賣超 0050 = 看空市場訊號

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
    """解析 TWSE 外資買賣超 JSON，取出特定 ETF 的外資淨買賣。

    TWT38U 回傳格式（外資及陸資買賣超彙總表）：
    {
      "stat": "OK",
      "data": [
        [" ", "0050  ", "元大台灣50", "買進股數", "賣出股數", "買賣超股數", ...]
      ]
    }
    欄位：[空白, 證券代號, 證券名稱, 買進股數, 賣出股數, 買賣超股數, ...]（三組，各代表外資/陸資/合計）
    使用最後一組（合計，col[9-11]）；若只有一組則取 col[3-5]。
    """
    try:
        if data.get("stat") != "OK":
            return None

        rows = data.get("data", [])
        if not rows:
            return None

        # 尋找目標 ETF 的列（col[1] 含 etf_id）
        for row in rows:
            if len(row) < 6:
                continue
            code = str(row[1]).strip()
            if code != etf_id:
                continue

            # 欄位順序：[空, 代號, 名稱, 買進, 賣出, 買賣超, 買進, 賣出, 買賣超, 買進, 賣出, 買賣超]
            # 取最後一欄「買賣超股數」作為合計淨買賣
            col_idx = 11 if len(row) >= 12 else 5
            net_shares = int(str(row[col_idx]).replace(",", ""))
            buy_shares  = int(str(row[col_idx - 2]).replace(",", ""))
            sell_shares = int(str(row[col_idx - 1]).replace(",", ""))

            # 轉換為張（1 張 = 1000 股）
            creation   = buy_shares  // 1000
            redemption = sell_shares // 1000
            net_flow   = net_shares  // 1000

            logger.info(f"[ETFFlow] {etf_id} {target_date}: 外資買={creation:,} 賣={redemption:,} 淨={net_flow:,} 張")
            return {
                "date": target_date,
                "etf_id": etf_id,
                "creation": creation,
                "redemption": redemption,
                "net_flow": net_flow,
            }

        logger.info(f"[ETFFlow] {etf_id} {target_date}: 找不到 {etf_id} 資料")
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

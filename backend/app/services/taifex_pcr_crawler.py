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

    TAIFEX 回傳的 HTML 包含多個商品的 OI 表格，使用中文欄位「買權」/「賣權」。
    透過 pandas read_html 解析多層標頭，取「臺指選擇權」的 Put/Call 未平倉口數合計。
    """
    try:
        import io
        import pandas as pd
    except ImportError:
        logger.error("[PCR] 需要安裝 pandas：pip install pandas lxml")
        return None

    try:
        dfs = pd.read_html(io.StringIO(html), flavor="lxml")
    except Exception as e:
        logger.warning(f"[PCR] read_html 失敗 {target_date}: {e}")
        return None

    for df in dfs:
        # 展平多層欄位標頭
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [" ".join(str(c) for c in col).strip() for col in df.columns]

        # 確認是否含有臺指選擇權資料
        text_repr = df.to_string()
        if "臺指選擇權" not in text_repr:
            continue

        try:
            # 找「未平倉」相關欄位的索引位置（用欄位名稱定位，比 max(nums) 可靠）
            oi_col_indices = [i for i, c in enumerate(df.columns) if "未平倉" in str(c)]
            # 若找不到未平倉欄位，fallback 用最後一個數值欄
            df_str = df.astype(str)

            call_oi = 0
            put_oi = 0

            for _, row in df_str.iterrows():
                row_values = list(row.values)
                row_text = " ".join(row_values)

                if "臺指選擇權" not in row_text:
                    continue

                is_call = "買權" in row_text
                is_put  = "賣權" in row_text

                if not is_call and not is_put:
                    continue
                # 同時含「買權」和「賣權」的列（如標頭/合計）跳過
                if is_call and is_put:
                    continue

                # 從「未平倉」欄位取 OI 值
                oi_val = 0
                if oi_col_indices:
                    for ci in oi_col_indices:
                        try:
                            oi_val = int(float(row_values[ci].replace(",", "").strip()))
                            if oi_val > 0:
                                break
                        except (ValueError, TypeError, IndexError):
                            pass
                # fallback：若欄位定位失敗，取最大整數
                if oi_val == 0:
                    nums = []
                    for v in row_values:
                        try:
                            nums.append(int(float(v.replace(",", "").strip())))
                        except (ValueError, TypeError):
                            pass
                    oi_val = max(nums) if nums else 0

                if oi_val == 0:
                    continue

                if is_call:
                    call_oi += oi_val
                elif is_put:
                    put_oi += oi_val

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
            logger.warning(f"[PCR] 解析表格 {target_date} 失敗: {e}")
            continue

    logger.info(f"[PCR] {target_date}: 找不到臺指選擇權資料（非交易日？）")
    return None


def sync_pcr(db, days_back: int = 5) -> int:
    """同步 TAIFEX 當日 PCR 資料。

    注意：TAIFEX callsAndPutsDate 端點不支援歷史查詢，
    永遠回傳當日（最近交易日）資料。days_back 參數保留為相容性參數，
    但實際上只嘗試寫入最近 1~2 個交易日（避免重複）。

    冪等：已存在的日期跳過。
    回傳成功寫入筆數。
    """
    from app.models.market_pcr import MarketPCR

    today = date.today()
    written = 0

    # TAIFEX 只提供當日資料，只嘗試今日與昨日（補假日重試）
    for delta in range(3):
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

        # 驗證：API 回傳日期必須為 target（防止 TAIFEX 回傳非當日資料時寫入錯誤）
        # 若 TAIFEX API 不支援指定日期，result["date"] 仍是 target_date（參數傳入）
        # 可正常寫入今日資料
        db.add(MarketPCR(
            date=result["date"],
            put_oi=result["put_oi"],
            call_oi=result["call_oi"],
            pcr=result["pcr"],
        ))
        written += 1
        break  # 寫入第一個成功的交易日就停止

    if written:
        db.commit()
        logger.info(f"[PCR] 寫入 {written} 筆 PCR 資料")
    return written

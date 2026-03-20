"""
籌碼資料爬蟲 (Chip Data Crawler)

抓取台灣股市三大法人買賣超與融資融券餘額：
- TWSE T86：上市三大法人每日買賣超
- TWSE MI_MARGN：上市融資融券每日餘額
- TPEx 三大法人：上櫃三大法人每日買賣超
- TPEx 融資融券：上櫃融資融券每日餘額
"""
import logging
import time
from datetime import date
from typing import Optional, Dict, Any

import requests
import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy import delete

from app.models.stock_chip_data import StockChipData

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
}


def _clean_num(val) -> Optional[float]:
    if val is None:
        return None
    s = str(val).strip().replace(",", "")
    if s in ("", "--", "---", "X"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


# ─── TWSE 三大法人 (T86) ────────────────────────────────────────────────────

def fetch_twse_institutional(target_date: date) -> pd.DataFrame:
    """抓取上市三大法人每日買賣超（TWSE T86）

    回傳欄位：stock_id, foreign_net_buy, trust_net_buy, dealer_net_buy（單位：千股）
    """
    date_str = target_date.strftime("%Y%m%d")
    url = "https://www.twse.com.tw/fund/T86"
    params = {"response": "json", "date": date_str, "selectType": "ALLBUT0999"}

    try:
        resp = requests.get(url, params=params, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning(f"[ChipCrawler] TWSE T86 請求失敗 {date_str}: {e}")
        return pd.DataFrame()

    fields = data.get("fields", [])
    rows = data.get("data", [])
    if not fields or not rows:
        logger.info(f"[ChipCrawler] TWSE T86 無資料: {date_str}")
        return pd.DataFrame()

    df = pd.DataFrame(rows, columns=fields)

    # 只保留 4 碼純數字（普通股）
    df = df[df["證券代號"].str.match(r"^[1-9]\d{3}$", na=False)].copy()

    result = pd.DataFrame()
    result["stock_id"] = df["證券代號"].str.strip()

    # 外資淨買超 = 外陸資買進 - 外陸資賣出（單位：千股）
    buy_col  = next((c for c in fields if "外陸資買進" in c), None)
    sell_col = next((c for c in fields if "外陸資賣出" in c), None)
    if buy_col and sell_col:
        foreign_buy  = df[buy_col].apply(_clean_num).fillna(0)
        foreign_sell = df[sell_col].apply(_clean_num).fillna(0)
        result["foreign_net_buy"] = (foreign_buy - foreign_sell) / 1000  # 股→張
    else:
        result["foreign_net_buy"] = None

    # 投信淨買超
    t_buy  = next((c for c in fields if "投信買進" in c), None)
    t_sell = next((c for c in fields if "投信賣出" in c), None)
    if t_buy and t_sell:
        result["trust_net_buy"] = (
            df[t_buy].apply(_clean_num).fillna(0) -
            df[t_sell].apply(_clean_num).fillna(0)
        ) / 1000
    else:
        result["trust_net_buy"] = None

    # 自營商淨買超
    d_buy  = next((c for c in fields if "自營商買進股數(自行買賣)" in c or "自營商買進" in c), None)
    d_sell = next((c for c in fields if "自營商賣出股數(自行買賣)" in c or "自營商賣出" in c), None)
    if d_buy and d_sell:
        result["dealer_net_buy"] = (
            df[d_buy].apply(_clean_num).fillna(0) -
            df[d_sell].apply(_clean_num).fillna(0)
        ) / 1000
    else:
        result["dealer_net_buy"] = None

    return result.reset_index(drop=True)


# ─── TWSE 融資融券 (MI_MARGN) ────────────────────────────────────────────────

def fetch_twse_margin(target_date: date) -> pd.DataFrame:
    """抓取上市融資融券餘額（TWSE MI_MARGN）

    回傳欄位：stock_id, margin_balance, short_balance（單位：張）

    API 的 table[1] 欄位結構（欄位名有重複，用固定索引）：
    [0]代號 [1]名稱 [2~7]融資相關 [6]融資今日餘額
    [8~13]融券相關 [12]融券今日餘額
    """
    date_str = target_date.strftime("%Y%m%d")
    url = "https://www.twse.com.tw/exchangeReport/MI_MARGN"
    params = {"response": "json", "date": date_str, "selectType": "ALL"}

    try:
        resp = requests.get(url, params=params, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning(f"[ChipCrawler] TWSE MI_MARGN 請求失敗 {date_str}: {e}")
        return pd.DataFrame()

    # 找含「代號」欄位且有多欄的個股明細 table
    target_rows = None
    target_fields = None

    if "tables" in data:
        for table in data["tables"]:
            fields = table.get("fields", [])
            rows = table.get("data", [])
            # 個股明細 table 特徵：第一欄是「代號」，且有 14+ 欄（含融資+融券各 6 欄）
            if fields and fields[0] == "代號" and len(fields) >= 14 and rows:
                target_fields = fields
                target_rows = rows
                break
    elif "data" in data:
        target_rows = data["data"]

    if not target_rows:
        logger.info(f"[ChipCrawler] TWSE MI_MARGN 無資料: {date_str}")
        return pd.DataFrame()

    df = pd.DataFrame(target_rows)

    # 只保留 4 碼純數字普通股（第 0 欄是代號）
    df = df[df[0].astype(str).str.match(r"^[1-9]\d{3}$", na=False)].copy()

    result = pd.DataFrame()
    result["stock_id"]       = df[0].astype(str).str.strip()
    result["margin_balance"] = df[6].apply(_clean_num)   # 融資今日餘額（index 6）
    result["short_balance"]  = df[12].apply(_clean_num)  # 融券今日餘額（index 12）

    return result.reset_index(drop=True)


# ─── TPEx 三大法人 ───────────────────────────────────────────────────────────

def fetch_tpex_institutional(target_date: date) -> pd.DataFrame:
    """抓取上櫃三大法人每日買賣超

    回傳欄位：stock_id, foreign_net_buy, trust_net_buy, dealer_net_buy（單位：張）
    """
    roc_year = target_date.year - 1911
    date_str = f"{roc_year}/{target_date.strftime('%m/%d')}"
    url = "https://www.tpex.org.tw/web/stock/3insti/daily_trade/3itrade_hedge_result.php"
    params = {"l": "zh-tw", "d": date_str, "se": "EW"}

    try:
        resp = requests.get(url, params=params, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning(f"[ChipCrawler] TPEx 三大法人請求失敗 {date_str}: {e}")
        return pd.DataFrame()

    aa_data = None
    fields = None

    if "tables" in data:
        for table in data["tables"]:
            f = table.get("fields", [])
            if any("代號" in x for x in f):
                fields = f
                aa_data = table.get("aaData") or table.get("data")
                break
    elif "aaData" in data:
        aa_data = data["aaData"]

    if not aa_data:
        logger.info(f"[ChipCrawler] TPEx 三大法人無資料: {date_str}")
        return pd.DataFrame()

    df = pd.DataFrame(aa_data)

    # 找欄位索引
    if fields:
        idx = {f: i for i, f in enumerate(fields)}
        id_idx     = next((v for k, v in idx.items() if "代號" in k), 0)
        f_buy_idx  = next((v for k, v in idx.items() if "外資" in k and "買" in k), None)
        f_sell_idx = next((v for k, v in idx.items() if "外資" in k and "賣" in k), None)
        t_buy_idx  = next((v for k, v in idx.items() if "投信" in k and "買" in k), None)
        t_sell_idx = next((v for k, v in idx.items() if "投信" in k and "賣" in k), None)
        d_buy_idx  = next((v for k, v in idx.items() if "自營" in k and "買" in k), None)
        d_sell_idx = next((v for k, v in idx.items() if "自營" in k and "賣" in k), None)
    else:
        # 常見預設欄位順序（備用）
        id_idx, f_buy_idx, f_sell_idx = 0, 2, 3
        t_buy_idx, t_sell_idx = 7, 8
        d_buy_idx, d_sell_idx = 12, 13

    df = df[df[id_idx].astype(str).str.match(r"^[1-9]\d{3}$", na=False)].copy()

    result = pd.DataFrame()
    result["stock_id"] = df[id_idx].astype(str).str.strip()

    def _net(buy_i, sell_i):
        if buy_i is None or sell_i is None:
            return None
        buy  = df[buy_i].apply(_clean_num).fillna(0)
        sell = df[sell_i].apply(_clean_num).fillna(0)
        return buy - sell

    result["foreign_net_buy"] = _net(f_buy_idx, f_sell_idx)
    result["trust_net_buy"]   = _net(t_buy_idx, t_sell_idx)
    result["dealer_net_buy"]  = _net(d_buy_idx, d_sell_idx)

    return result.reset_index(drop=True)


# ─── TWSE 外資持股比率 (MI_QFIIS) ────────────────────────────────────────────

def fetch_twse_foreign_holding(target_date: date) -> pd.DataFrame:
    """抓取上市股票全體外資持股比率（TWSE MI_QFIIS）

    回傳欄位：stock_id, foreign_hold_pct（外資持股比率 %）
    注意：僅覆蓋上市股票（TWSE），上櫃股票不在此 API 中
    """
    date_str = target_date.strftime("%Y%m%d")
    url = "https://www.twse.com.tw/fund/MI_QFIIS"
    params = {"response": "json", "date": date_str, "selectType": "ALLBUT0999"}

    try:
        resp = requests.get(url, params=params, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning(f"[ChipCrawler] TWSE MI_QFIIS 請求失敗 {date_str}: {e}")
        return pd.DataFrame()

    fields = data.get("fields", [])
    rows = data.get("data", [])
    if not fields or not rows:
        logger.info(f"[ChipCrawler] TWSE MI_QFIIS 無資料: {date_str}")
        return pd.DataFrame()

    df = pd.DataFrame(rows, columns=fields)

    # 只保留 4 碼純數字（普通股）
    id_col = fields[0]  # 第 0 欄為證券代號
    df = df[df[id_col].astype(str).str.match(r"^[1-9]\d{3}$", na=False)].copy()

    if df.empty:
        return pd.DataFrame()

    # 持股比率：第 7 欄（全體外資及陸資持股比率）
    hold_col = fields[7] if len(fields) > 7 else None
    if hold_col is None:
        logger.warning(f"[ChipCrawler] MI_QFIIS 欄位結構異常: {fields}")
        return pd.DataFrame()

    result = pd.DataFrame()
    result["stock_id"] = df[id_col].astype(str).str.strip()
    result["foreign_hold_pct"] = df[hold_col].apply(_clean_num)

    return result.reset_index(drop=True)


# ─── TPEx 融資融券 ───────────────────────────────────────────────────────────

def fetch_tpex_margin(target_date: date) -> pd.DataFrame:
    """抓取上櫃融資融券餘額（單位：張）"""
    roc_year = target_date.year - 1911
    date_str = f"{roc_year}/{target_date.strftime('%m/%d')}"
    url = "https://www.tpex.org.tw/web/stock/margin_trading/margin_balance/mbalance_result.php"
    params = {"l": "zh-tw", "d": date_str}

    try:
        resp = requests.get(url, params=params, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning(f"[ChipCrawler] TPEx 融資融券請求失敗 {date_str}: {e}")
        return pd.DataFrame()

    aa_data = None
    fields = None

    if "tables" in data:
        for table in data["tables"]:
            f = table.get("fields", [])
            if any("代號" in x for x in f) and any("融資" in x for x in f):
                fields = f
                aa_data = table.get("aaData") or table.get("data")
                break
    elif "aaData" in data:
        aa_data = data["aaData"]

    if not aa_data:
        logger.info(f"[ChipCrawler] TPEx 融資融券無資料: {date_str}")
        return pd.DataFrame()

    df = pd.DataFrame(aa_data)

    if fields:
        idx = {f: i for i, f in enumerate(fields)}
        id_idx     = next((v for k, v in idx.items() if "代號" in k), 0)
        margin_idx = next((v for k, v in idx.items() if "融資" in k and "餘額" in k), None)
        short_idx  = next((v for k, v in idx.items() if "融券" in k and "餘額" in k), None)
    else:
        id_idx, margin_idx, short_idx = 0, 4, 10  # 常見預設索引（備用）

    df = df[df[id_idx].astype(str).str.match(r"^[1-9]\d{3}$", na=False)].copy()

    result = pd.DataFrame()
    result["stock_id"]      = df[id_idx].astype(str).str.strip()
    result["margin_balance"] = df[margin_idx].apply(_clean_num) if margin_idx is not None else None
    result["short_balance"]  = df[short_idx].apply(_clean_num)  if short_idx  is not None else None

    return result.reset_index(drop=True)


# ─── 整合寫入 ────────────────────────────────────────────────────────────────

def sync_daily_chip_data(db: Session, target_date: Optional[date] = None) -> Dict[str, Any]:
    """抓取單日籌碼資料並寫入 stock_chip_data 表

    流程：
    1. 抓 TWSE/TPEx 三大法人 + 融資融券
    2. 合併（outer join on stock_id）
    3. Upsert 進 stock_chip_data
    """
    if target_date is None:
        target_date = date.today()

    logger.info(f"[ChipCrawler] 開始抓取 {target_date} 籌碼資料...")

    # 1. 抓取資料
    twse_inst   = fetch_twse_institutional(target_date)
    time.sleep(1)
    twse_margin = fetch_twse_margin(target_date)
    time.sleep(1)
    tpex_inst   = fetch_tpex_institutional(target_date)
    time.sleep(1)
    tpex_margin = fetch_tpex_margin(target_date)
    time.sleep(1)
    twse_holding = fetch_twse_foreign_holding(target_date)

    # 2. 合併三大法人（TWSE + TPEx）
    inst_dfs = [df for df in [twse_inst, tpex_inst] if not df.empty]
    inst_df  = pd.concat(inst_dfs, ignore_index=True) if inst_dfs else pd.DataFrame()

    # 合併融資融券
    margin_dfs = [df for df in [twse_margin, tpex_margin] if not df.empty]
    margin_df  = pd.concat(margin_dfs, ignore_index=True) if margin_dfs else pd.DataFrame()

    if inst_df.empty and margin_df.empty:
        logger.info(f"[ChipCrawler] {target_date} 無籌碼資料（非交易日或資料未發佈）")
        return {"status": "no_data", "date": str(target_date), "inserted": 0}

    # 3. Merge
    if not inst_df.empty and not margin_df.empty:
        merged = pd.merge(inst_df, margin_df, on="stock_id", how="outer")
    elif not inst_df.empty:
        merged = inst_df.copy()
        for col in ("margin_balance", "short_balance"):
            merged[col] = None
    else:
        merged = margin_df.copy()
        for col in ("foreign_net_buy", "trust_net_buy", "dealer_net_buy"):
            merged[col] = None

    # 去重（保留第一筆，避免同股票重複）
    merged = merged.drop_duplicates(subset=["stock_id"], keep="first")

    # Merge 外資持股比率（只有上市股票有資料）
    if not twse_holding.empty:
        merged = pd.merge(merged, twse_holding, on="stock_id", how="left")
    else:
        merged["foreign_hold_pct"] = None

    # 4. Upsert（先刪後插）
    db.execute(delete(StockChipData).where(StockChipData.date == target_date))

    records = []
    for _, row in merged.iterrows():
        sid = str(row["stock_id"]).strip()
        if not sid:
            continue
        records.append(StockChipData(
            stock_id=sid,
            date=target_date,
            foreign_net_buy=_safe_float(row.get("foreign_net_buy")),
            trust_net_buy=_safe_float(row.get("trust_net_buy")),
            dealer_net_buy=_safe_float(row.get("dealer_net_buy")),
            margin_balance=_safe_int(row.get("margin_balance")),
            short_balance=_safe_int(row.get("short_balance")),
            foreign_hold_pct=_safe_float(row.get("foreign_hold_pct")),
        ))

    if records:
        db.bulk_save_objects(records)
    db.commit()

    logger.info(f"[ChipCrawler] {target_date}: 寫入 {len(records)} 筆籌碼資料")
    return {"status": "success", "date": str(target_date), "inserted": len(records)}


def _safe_float(val) -> Optional[float]:
    if val is None:
        return None
    try:
        import math
        f = float(val)
        return None if (math.isnan(f) or math.isinf(f)) else round(f, 2)
    except (TypeError, ValueError):
        return None


def _safe_int(val) -> Optional[int]:
    f = _safe_float(val)
    return int(f) if f is not None else None

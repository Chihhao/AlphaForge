"""
CBOE VIX 恐慌指數爬蟲

資料來源：Yahoo Finance (^VIX)
VIX 衡量 S&P 500 選擇權的隱含波動率，反映全球市場恐慌程度。
高 VIX（>30）= 市場恐慌；低 VIX（<15）= 市場平靜。
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

logger = logging.getLogger(__name__)


def fetch_vix(start_date: date, end_date: date) -> list[dict]:
    """從 Yahoo Finance 抓取 VIX 歷史資料。

    回傳 list[dict]: [{'date': date, 'open': float, 'high': float, 'low': float, 'close': float}]
    """
    try:
        import yfinance as yf
    except ImportError:
        logger.error("[VIX] 需要安裝 yfinance：pip install yfinance")
        return []

    try:
        # yfinance end_date 是 exclusive，加 1 天
        df = yf.download(
            "^VIX",
            start=start_date.isoformat(),
            end=(end_date + timedelta(days=1)).isoformat(),
            progress=False,
        )
    except Exception as e:
        logger.warning(f"[VIX] 抓取失敗: {e}")
        return []

    if df.empty:
        return []

    results = []
    for idx, row in df.iterrows():
        d = idx.date() if hasattr(idx, 'date') else idx
        try:
            results.append({
                "date": d,
                "open": round(float(row[("Open", "^VIX")]), 2),
                "high": round(float(row[("High", "^VIX")]), 2),
                "low": round(float(row[("Low", "^VIX")]), 2),
                "close": round(float(row[("Close", "^VIX")]), 2),
            })
        except (KeyError, TypeError):
            # fallback: 舊版 yfinance 沒有 MultiIndex
            results.append({
                "date": d,
                "open": round(float(row["Open"]), 2),
                "high": round(float(row["High"]), 2),
                "low": round(float(row["Low"]), 2),
                "close": round(float(row["Close"]), 2),
            })

    logger.info(f"[VIX] 取得 {len(results)} 筆 ({start_date} ~ {end_date})")
    return results


def sync_vix(db, days_back: int = 7) -> int:
    """同步近 N 天的 VIX 資料。冪等：已存在的日期跳過。"""
    from app.models.market_vix import MarketVIX

    today = date.today()
    start = today - timedelta(days=days_back)

    existing = set(
        r[0] for r in db.query(MarketVIX.date).filter(
            MarketVIX.date >= start,
        ).all()
    )

    rows = fetch_vix(start, today)
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
        logger.info(f"[VIX] 寫入 {written} 筆")
    return written

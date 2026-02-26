from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Dict, Any
import yfinance as yf
import pandas as pd
from datetime import datetime

app = FastAPI(title="TW-STOCK-168 Demo Server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Simple in-memory stock list for search
STOCKS_DB = [
    {"stock_id": "2330", "stock_name": "台積電", "market": "上市"},
    {"stock_id": "2454", "stock_name": "聯發科", "market": "上市"},
    {"stock_id": "3008", "stock_name": "瑞昱", "market": "上市"},
    {"stock_id": "2308", "stock_name": "台達電", "market": "上市"},
    {"stock_id": "3034", "stock_name": "聯詠", "market": "上市"},
]

# 常用台股中文名稱映射（可擴充）
STOCK_CN_NAMES = {
    "2330": "台積電",
    "2454": "聯發科",
    "3008": "瑞昱",
    "2308": "台達電",
    "3034": "聯詠",
    "2337": "旺宏",
}


@app.get("/api/stocks/search")
def search_stocks(q: str, limit: int = 20):
    ql = q.lower()
    results = [s for s in STOCKS_DB if ql in s["stock_id"] or ql in s["stock_name"].lower()]
    # If no results and the query looks like a numeric stock id, try yfinance to validate
    if len(results) == 0 and q.isdigit():
        stock_id = q
        ticker = f"{stock_id}.TW"
        try:
            t = yf.Ticker(ticker)
            hist = t.history(period="1d")
            if not hist.empty:
                # Use any available longName or fallback name
                info_name = None
                try:
                    info = t.info
                    info_name = info.get("longName") or info.get("shortName")
                except Exception:
                    info_name = None

                results = [{
                    "stock_id": stock_id,
                    "stock_name": STOCK_CN_NAMES.get(stock_id, info_name or f"股票 {stock_id}"),
                    "market": "上市",
                }]
        except Exception:
            # ignore and return empty
            pass

    return {"results": results[:limit], "count": len(results[:limit])}


@app.get("/api/stocks/{stock_id}/quote")
def get_quote(stock_id: str):
    ticker = f"{stock_id}.TW"
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period="2d")
        if hist.empty:
            raise HTTPException(status_code=404, detail="No data")
        latest = hist.iloc[-1]
        prev = hist.iloc[-2] if len(hist) >= 2 else None
        prev_close = prev["Close"] if prev is not None else latest["Close"]
        change_pct = (latest["Close"] - prev_close) / prev_close * 100 if prev is not None else 0.0

        # 優先使用中文映射
        name_cn = STOCK_CN_NAMES.get(stock_id)
        default_name = next((s['stock_name'] for s in STOCKS_DB if s['stock_id'] == stock_id), None)
        stock_name = name_cn or default_name

        # 若仍無中文名稱，嘗試從 yfinance info 取得名稱
        if not stock_name:
            try:
                info = t.info
                stock_name = info.get("longName") or info.get("shortName")
            except Exception:
                stock_name = f"股票 {stock_id}"

        return {
            "stock_id": stock_id,
            "stock_name": stock_name,
            "current_price": float(latest["Close"]),
            "open": float(latest["Open"]),
            "high": float(latest["High"]),
            "low": float(latest["Low"]),
            "volume": int(latest.get("Volume", 0)),
            "change_percent": float(round(change_pct, 4)),
            "timestamp": datetime.utcnow().isoformat() + 'Z'
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stocks/{stock_id}/kline")
def get_kline(stock_id: str, period: str = "1y", interval: str = "1d"):
    ticker = f"{stock_id}.TW"
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period=period, interval=interval)
        if hist.empty:
            raise HTTPException(status_code=404, detail="No data")
        # Ensure columns
        hist = hist.reset_index()
        data = []
        for _, row in hist.iterrows():
            data.append({
                "date": row["Date"].isoformat(),
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "volume": int(row.get("Volume", 0)),
            })
        return {"stock_id": stock_id, "period": period, "interval": interval, "data": data}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

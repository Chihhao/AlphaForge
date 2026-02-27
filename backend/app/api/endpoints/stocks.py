from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.db.database import get_db
from app.schemas.stock import Stock, StockCreate, StockQuote
from app.services.stock_service import StockService
from app.models.user import Stock as StockModel


router = APIRouter(prefix="/api/stocks", tags=["stocks"])


@router.get("/search")
def search_stocks(q: str, limit: int = 20):
    """
    搜尋股票

    - **q**: 搜尋關鍵字（股票代號或名稱）
    - **limit**: 最多返回結果數（預設 20）

    Returns:
    - 股票列表，包含 stock_id, stock_name, market 等信息
    """
    if not q or len(q) < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="搜尋關鍵字不能為空"
        )

    results = StockService.search_stocks(q, limit)
    return {"results": results, "count": len(results)}


@router.get("/{stock_id}/quote")
def get_stock_quote(stock_id: str):
    """
    取得股票最新報價

    - **stock_id**: 股票代號，如 "2330"

    Returns:
    - 股票報價信息，包含現價、開盤、最高、最低、成交量、漲跌幅
    """
    quote = StockService.get_stock_quote(stock_id)
    if not quote:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"無法取得股票 {stock_id} 的報價"
        )

    return quote


@router.get("/{stock_id}/kline")
def get_kline_data(
    stock_id: str,
    period: str = "1y",
    interval: str = "1d"
):
    """
    取得 K 線數據

    - **stock_id**: 股票代號，如 "2330"
    - **period**: 時間週期（預設 "1y"）
      - "1d" - 1 天
      - "5d" - 5 天
      - "1mo" - 1 個月
      - "3mo" - 3 個月
      - "6mo" - 6 個月
      - "1y" - 1 年
      - "2y" - 2 年
      - "5y" - 5 年
      - "10y" - 10 年
    - **interval**: K 線間隔（預設 "1d"）
      - "1m" - 1 分鐘
      - "5m" - 5 分鐘
      - "15m" - 15 分鐘
      - "30m" - 30 分鐘
      - "1h" - 1 小時
      - "1d" - 1 天
      - "1wk" - 1 週
      - "1mo" - 1 個月

    Returns:
    - K 線數據，包含日期、開盤、最高、最低、收盤、成交量
    """
    df = StockService.get_kline_data(stock_id, period, interval)
    if df is None or df.empty:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"無法取得股票 {stock_id} 的 K 線數據"
        )

    # 格式化為 JSON
    data = []
    for date, row in df.iterrows():
        data.append({
            "date": date.isoformat(),
            "open": float(row['開盤']),
            "high": float(row['最高']),
            "low": float(row['最低']),
            "close": float(row['收盤']),
            "volume": int(row['成交量']),
        })

    return {"stock_id": stock_id, "period": period, "interval": interval, "data": data}


@router.get("/{stock_id}/indicators")
def get_indicators(
    stock_id: str,
    period: str = "1y",
    interval: str = "1d"
):
    """
    取得技術指標

    - **stock_id**: 股票代號
    - **period**: 時間週期
    - **interval**: K 線間隔

    Returns:
    - 技術指標數據，包含移動平均線、布林通道、RSI 等
    """
    df = StockService.get_kline_data(stock_id, period, interval)
    if df is None or df.empty:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"無法取得股票 {stock_id} 的數據"
        )

    prices = df['收盤']

    # 計算各項指標
    ma20 = StockService.calculate_ma(prices, 20)
    ma50 = StockService.calculate_ma(prices, 50)
    rsi = StockService.calculate_rsi(prices, 14)
    bb = StockService.calculate_bollinger_bands(prices, 20, 2)

    # 格式化為 JSON
    data = []
    for i, date in enumerate(df.index):
        data.append({
            "date": date.isoformat(),
            "close": float(prices.iloc[i]),
            "ma20": float(ma20.iloc[i]) if not pd.isna(ma20.iloc[i]) else None,
            "ma50": float(ma50.iloc[i]) if not pd.isna(ma50.iloc[i]) else None,
            "rsi": float(rsi.iloc[i]) if not pd.isna(rsi.iloc[i]) else None,
            "bb_upper": float(bb["upper"].iloc[i]) if not pd.isna(bb["upper"].iloc[i]) else None,
            "bb_middle": float(bb["middle"].iloc[i]) if not pd.isna(bb["middle"].iloc[i]) else None,
            "bb_lower": float(bb["lower"].iloc[i]) if not pd.isna(bb["lower"].iloc[i]) else None,
        })

    return {"stock_id": stock_id, "data": data}


# 導入 pandas
import pandas as pd

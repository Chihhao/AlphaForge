from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from datetime import date as date_type

from app.db.database import get_db
from app.schemas.stock import Stock, StockCreate, StockQuote
from app.schemas.market import MarketRankingResponse
from app.services.stock_service import StockService
from app.services.market_service import MarketService
from app.services.ai_analysis_service import get_or_create_analysis
from app.models.user import Stock as StockModel


router = APIRouter(prefix="/stocks", tags=["stocks"])

@router.get("/rankings", response_model=MarketRankingResponse)
def get_market_rankings(limit: int = 5):
    """
    取得市場概況排行榜
    包含每日漲幅、跌幅、成交量排行榜。
    """
    return MarketService.get_market_rankings(limit=limit)


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
        # 確保 date 是帶有時資訊的 ISO 字串，如果是 naive 則視為台北時間
        if date.tzinfo is None:
            # 視為台北時間並轉換為 UTC 輸出，或是直接標註時區
            # 這裡為了前端方便，我們統一轉成正確的 ISO 格式
            formatted_date = date.strftime("%Y-%m-%dT%H:%M:%S+08:00")
        else:
            formatted_date = date.isoformat()
            
        data.append({
            "date": formatted_date,
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
    bias_ma20 = StockService.calculate_bias(prices, 20)

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
            "bias_ma20": float(bias_ma20.iloc[i]) if not pd.isna(bias_ma20.iloc[i]) else None,
        })

    return {"stock_id": stock_id, "data": data}


@router.get("/{stock_id}/advanced-indicators")
def get_advanced_indicators(stock_id: str):
    """
    進階技術分析：多期乖離率、均線扣抵分析、多指標綜合評等 (0-100)
    """
    df = StockService.get_kline_data(stock_id, "1y", "1d")
    if df is None or df.empty:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"無法取得股票 {stock_id} 的數據",
        )

    prices = df["收盤"]
    current_price = float(prices.iloc[-1])

    # ── 多期乖離率 ─────────────────────────────────────────────────
    bias: dict = {}
    for period in [5, 10, 20, 60]:
        b = StockService.calculate_bias(prices, period)
        b_clean = b.dropna()
        bias[f"bias{period}"] = round(float(b_clean.iloc[-1]), 2) if not b_clean.empty else None

    # ── 均線扣抵分析 ──────────────────────────────────────────────
    ma_deduction: dict = {}
    for period in [5, 20]:
        ma = StockService.calculate_ma(prices, period)
        ma_clean = ma.dropna()
        latest_ma = round(float(ma_clean.iloc[-1]), 2) if not ma_clean.empty else None
        # 扣抵價：即將「脫離」MA 視窗的那根收盤價（period 個交易日前）
        ded_price = round(float(prices.iloc[-period - 1]), 2) if len(prices) > period else None
        if latest_ma and ded_price:
            deviation_pct = round((current_price - ded_price) / ded_price * 100, 2)
            trend = "up" if current_price >= ded_price else "down"
        else:
            deviation_pct, trend = None, None
        ma_deduction[f"ma{period}"] = {
            "current_price": current_price,
            "deduction_price": ded_price,
            "ma_value": latest_ma,
            "deviation_pct": deviation_pct,
            "trend": trend,
        }

    # ── 多指標綜合評等 (0-100) ────────────────────────────────────
    rsi = StockService.calculate_rsi(prices, 14)
    rsi_val = float(rsi.dropna().iloc[-1]) if not rsi.dropna().empty else 50.0

    ma20 = StockService.calculate_ma(prices, 20)
    latest_ma20 = float(ma20.dropna().iloc[-1]) if not ma20.dropna().empty else None

    bb = StockService.calculate_bollinger_bands(prices, 20, 2)
    bb_upper = float(bb["upper"].dropna().iloc[-1]) if not bb["upper"].dropna().empty else None
    bb_lower = float(bb["lower"].dropna().iloc[-1]) if not bb["lower"].dropna().empty else None

    score = 50
    # RSI
    if rsi_val > 70:       score -= 10
    elif rsi_val > 55:     score += 5
    elif rsi_val < 30:     score += 10
    elif rsi_val < 45:     score -= 5
    # MA20 位階
    if latest_ma20:
        score += 15 if current_price > latest_ma20 else -15
    # 布林位置
    if bb_upper and bb_lower:
        rng = bb_upper - bb_lower
        if rng > 0:
            pos = (current_price - bb_lower) / rng
            if pos > 0.85:   score -= 10
            elif pos > 0.5:  score += 5
            elif pos < 0.15: score += 10
            else:            score -= 5
    # BIAS20
    b20 = bias.get("bias20")
    if b20 is not None:
        if b20 > 10:    score -= 10
        elif b20 > 3:   score += 5
        elif b20 < -10: score += 10
        elif b20 < -3:  score -= 5

    composite_score = max(0, min(100, score))

    return {
        "stock_id": stock_id,
        "current_price": current_price,
        "bias": bias,
        "ma_deduction": ma_deduction,
        "composite_score": composite_score,
    }


from app.models.stock_revenue import StockMonthlyRevenue
from app.models.stock_eps import StockQuarterlyEPS


@router.get("/{stock_id}/fundamental/trends")
def get_fundamental_trends(stock_id: str, db: Session = Depends(get_db)):
    """
    取得基本面成長趨勢
    包含近 12 個月營收趨勢與近 8 季 EPS 趨勢。
    """
    # 1. 取得營收趨勢 (近 12 個月)
    revenue_history = db.query(StockMonthlyRevenue).filter(
        StockMonthlyRevenue.stock_id == stock_id
    ).order_by(StockMonthlyRevenue.year.desc(), StockMonthlyRevenue.month.desc()).limit(12).all()
    
    # 校正順序為從舊到新
    revenue_history = sorted(revenue_history, key=lambda x: (x.year, x.month))
    
    # 2. 取得 EPS 趨勢 (近 8 季)
    eps_history = db.query(StockQuarterlyEPS).filter(
        StockQuarterlyEPS.stock_id == stock_id
    ).order_by(StockQuarterlyEPS.year.desc(), StockQuarterlyEPS.quarter.desc()).limit(8).all()
    
    # 校正順序為從舊到新
    eps_history = sorted(eps_history, key=lambda x: (x.year, x.quarter))
    
    return {
        "stock_id": stock_id,
        "revenue_trends": [
            {
                "label": f"{r.year}/M{r.month:02d}",
                "revenue": r.revenue,
                "yoy": r.revenue_yoy,
                "mom": r.revenue_mom
            } for r in revenue_history
        ],
        "eps_trends": [
            {
                "label": f"{e.year}Q{e.quarter}",
                "eps": e.eps
            } for e in eps_history
        ]
    }


@router.get("/{stock_id}/ai-analysis")
def get_ai_analysis(
    stock_id: str,
    refresh: bool = False,
    db: Session = Depends(get_db),
):
    """
    取得個股 AI 智慧解讀（當日快取，同日多人共用同一份分析）

    - **stock_id**: 股票代號，如 "2330"
    - **refresh**: 傳 true 強制重新分析（忽略快取）
    """
    # 取得股名
    quote = StockService.get_stock_quote(stock_id)
    stock_name = getattr(quote, "stock_name", stock_id) if quote else stock_id

    today = date_type.today().strftime("%Y-%m-%d")

    try:
        result = get_or_create_analysis(
            db=db,
            stock_id=stock_id,
            stock_name=stock_name,
            today=today,
            force_refresh=refresh,
        )
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))

    return {"stock_id": stock_id, "date": today, **result}


# 導入 pandas
import pandas as pd


@router.get("/{stock_id}/chip-data")
def get_chip_data(stock_id: str, days: int = 20, db: Session = Depends(get_db)):
    """
    取得個股近期籌碼數據（三大法人買賣超 + 融資融券 + 外資持股比率）

    - **stock_id**: 股票代號
    - **days**: 近幾個交易日（預設 20）
    """
    from app.models.stock_chip_data import StockChipData
    rows = (
        db.query(StockChipData)
        .filter(StockChipData.stock_id == stock_id)
        .order_by(StockChipData.date.desc())
        .limit(days)
        .all()
    )
    return [
        {
            "date": r.date.isoformat(),
            "foreign_net_buy": r.foreign_net_buy,
            "trust_net_buy": r.trust_net_buy,
            "dealer_net_buy": r.dealer_net_buy,
            "margin_balance": r.margin_balance,
            "short_balance": r.short_balance,
            "foreign_hold_pct": r.foreign_hold_pct,
        }
        for r in reversed(rows)
    ]

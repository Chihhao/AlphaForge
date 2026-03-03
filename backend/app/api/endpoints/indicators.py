from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional

from app.services.indicator_service import IndicatorService
from app.schemas.indicator import IndicatorResponse, KDStatus

router = APIRouter(prefix="/indicators", tags=["indicators"])


@router.get("/kd/{stock_id}", response_model=IndicatorResponse)
def get_kd(
    stock_id: str,
    days: int = Query(30, description="回傳的天數")
):
    """取得 KD 指標數據"""
    values = IndicatorService.get_kd_indicator(stock_id, days)
    if not values:
        raise HTTPException(status_code=404, detail="無法取得該股票的指標數據")

    return IndicatorResponse(
        stock_id=stock_id,
        indicator_type="KD",
        values=values
    )


@router.get("/kd/{stock_id}/status", response_model=KDStatus)
def get_kd_status(stock_id: str):
    """取得當前的 KD 狀態與訊號"""
    status = IndicatorService.get_current_kd_status(stock_id)
    if not status:
        raise HTTPException(status_code=404, detail="無法取得該股票的狀態")
    return status

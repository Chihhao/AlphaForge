from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.db.database import get_db
from app.schemas.trading import OrderCreate, Order, Portfolio
from app.services.trading_service import TradingService
from app.models.user import User


router = APIRouter(prefix="/trading", tags=["trading"])


@router.post("/orders", response_model=Order)
def create_order(
    username: str,
    order_create: OrderCreate,
    db: Session = Depends(get_db)
):
    """
    建立交易訂單
    
    - **username**: 用戶名
    - **stock_id**: 股票 ID
    - **order_type**: 訂單類型 ("買入" 或 "賣出")
    - **price_type**: 價格類型 ("市價" 或 "限價")
    - **quantity**: 數量
    - **price**: 限價單的價格（市價單不需要）
    
    Returns:
    - 新建立的訂單信息
    """
    # 這裡簡化了，實際應該通過驗證取得當前用戶
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用戶未找到"
        )
    
    order = TradingService.create_order(db, user.id, order_create)
    return order


@router.get("/portfolio")
def get_portfolio(username: str, db: Session = Depends(get_db)):
    """
    取得用戶投資組合
    
    - **username**: 用戶名
    
    Returns:
    - 投資組合列表，包含持股信息
    """
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用戶未找到"
        )
    
    portfolio = TradingService.get_user_portfolio(db, user.id)
    return {"portfolio": portfolio}


@router.get("/orders")
def get_orders(username: str, db: Session = Depends(get_db)):
    """
    取得用戶訂單歷史
    
    - **username**: 用戶名
    
    Returns:
    - 訂單列表
    """
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用戶未找到"
        )
    
    orders = TradingService.get_user_orders(db, user.id)
    return {"orders": orders, "count": len(orders)}


@router.get("/account")
def get_account_info(username: str, db: Session = Depends(get_db)):
    """
    取得帳戶信息
    
    - **username**: 用戶名
    
    Returns:
    - 帳戶信息，包含虛擬資金、持股市值、總資產等
    """
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用戶未找到"
        )
    
    portfolio = TradingService.get_user_portfolio(db, user.id)
    
    # 計算總持股市值
    total_market_value = sum(p.current_price * p.quantity for p in portfolio if p.current_price)
    total_asset = user.virtual_balance + total_market_value
    
    return {
        "user_id": user.id,
        "virtual_balance": user.virtual_balance,
        "portfolio_value": total_market_value,
        "total_asset": total_asset,
        "holding_count": len(portfolio),
    }

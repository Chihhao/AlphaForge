from sqlalchemy.orm import Session
from app.models.user import Order, Portfolio, Stock
from app.schemas.trading import OrderCreate


class TradingService:
    """模擬交易服務"""

    @staticmethod
    def create_order(db: Session, user_id: int, order_create: OrderCreate) -> Order:
        """建立訂單"""
        order = Order(
            user_id=user_id,
            stock_id=order_create.stock_id,
            order_type=order_create.order_type,
            price_type=order_create.price_type,
            quantity=order_create.quantity,
            price=order_create.price,
            status="未成交",
        )
        db.add(order)
        db.commit()
        db.refresh(order)
        return order

    @staticmethod
    def get_user_portfolio(db: Session, user_id: int) -> list[Portfolio]:
        """取得用戶投資組合"""
        return db.query(Portfolio).filter(Portfolio.user_id == user_id).all()

    @staticmethod
    def get_user_orders(db: Session, user_id: int) -> list[Order]:
        """取得用戶訂單歷史"""
        return db.query(Order).filter(Order.user_id == user_id).order_by(Order.created_at.desc()).all()

    @staticmethod
    def match_order(db: Session, order: Order, market_price: float) -> bool:
        """
        模擬訂單成交（簡單版：根據市場價格直接成交）
        
        Args:
            db: 數據庫會話
            order: 訂單
            market_price: 市場價格
        
        Returns:
            是否成功成交
        """
        # 市價單或限價單到達目標價格都可以成交
        if order.price_type == "市價":
            order.executed_price = market_price
            order.executed_quantity = order.quantity
            order.status = "完全成交"
        elif order.price_type == "限價" and order.price is not None:
            # 買入時，市場價格 <= 限價才能成交
            # 賣出時，市場價格 >= 限價才能成交
            can_execute = False
            if order.order_type == "買入" and market_price <= order.price:
                can_execute = True
            elif order.order_type == "賣出" and market_price >= order.price:
                can_execute = True
            
            if can_execute:
                order.executed_price = market_price
                order.executed_quantity = order.quantity
                order.status = "完全成交"
        
        db.add(order)
        db.commit()
        return order.status == "完全成交"

    @staticmethod
    def update_portfolio(
        db: Session,
        user_id: int,
        stock_id: int,
        quantity_change: int,
        price: float
    ) -> Portfolio:
        """
        更新投資組合
        
        Args:
            db: 數據庫會話
            user_id: 用戶 ID
            stock_id: 股票 ID
            quantity_change: 數量變化（正數為買入，負數為賣出）
            price: 交易價格
        
        Returns:
            更新後的投資組合
        """
        portfolio = db.query(Portfolio).filter(
            Portfolio.user_id == user_id,
            Portfolio.stock_id == stock_id
        ).first()
        
        if portfolio is None:
            # 新建投資組合
            portfolio = Portfolio(
                user_id=user_id,
                stock_id=stock_id,
                quantity=quantity_change,
                average_cost=price,
                current_price=price,
            )
        else:
            # 更新平均成本
            total_cost = (portfolio.quantity * portfolio.average_cost) + (quantity_change * price)
            new_quantity = portfolio.quantity + quantity_change
            
            if new_quantity > 0:
                portfolio.average_cost = total_cost / new_quantity
                portfolio.quantity = new_quantity
            else:
                # 全部賣出
                portfolio.quantity = 0
            
            portfolio.current_price = price
        
        db.add(portfolio)
        db.commit()
        db.refresh(portfolio)
        return portfolio

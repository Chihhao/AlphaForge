from sqlalchemy.orm import Session
from app.models.user import User
from app.core.security import get_password_hash, verify_password
from app.schemas.user import UserCreate, UserUpdate


class UserService:
    """用戶服務"""

    @staticmethod
    def create_user(db: Session, user_create: UserCreate) -> User:
        """建立新用戶"""
        db_user = User(
            email=user_create.email,
            username=user_create.username,
            full_name=user_create.full_name,
            hashed_password=get_password_hash(user_create.password),
        )
        db.add(db_user)
        db.commit()
        db.refresh(db_user)
        return db_user

    @staticmethod
    def get_user_by_email(db: Session, email: str) -> User | None:
        """按郵箱取得用戶"""
        return db.query(User).filter(User.email == email).first()

    @staticmethod
    def get_user_by_username(db: Session, username: str) -> User | None:
        """按用戶名取得用戶"""
        return db.query(User).filter(User.username == username).first()

    @staticmethod
    def get_user_by_id(db: Session, user_id: int) -> User | None:
        """按 ID 取得用戶"""
        return db.query(User).filter(User.id == user_id).first()

    @staticmethod
    def authenticate_user(db: Session, username: str, password: str) -> User | None:
        """驗證用戶"""
        user = UserService.get_user_by_username(db, username)
        if not user or not verify_password(password, user.hashed_password):
            return None
        return user

    @staticmethod
    def update_user(db: Session, user: User, user_update: UserUpdate) -> User:
        """更新用戶信息"""
        if user_update.full_name:
            user.full_name = user_update.full_name
        if user_update.password:
            user.hashed_password = get_password_hash(user_update.password)
        
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

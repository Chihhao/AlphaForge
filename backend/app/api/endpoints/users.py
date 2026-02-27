from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import timedelta

from app.db.database import get_db
from app.schemas.user import UserCreate, User, UserUpdate
from app.services.user_service import UserService
from app.core.security import create_access_token
from app.core.config import settings


router = APIRouter(prefix="/users", tags=["users"])


@router.post("/register", response_model=User)
def register(user_create: UserCreate, db: Session = Depends(get_db)):
    """
    用戶註冊

    - **email**: 用戶郵箱
    - **username**: 用戶名
    - **password**: 密碼
    - **full_name**: 全名（可選）
    """
    # 檢查用戶是否已存在
    existing_user = UserService.get_user_by_email(db, user_create.email)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="郵箱已被註冊"
        )

    existing_username = UserService.get_user_by_username(db, user_create.username)
    if existing_username:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="用戶名已被使用"
        )

    user = UserService.create_user(db, user_create)
    return user


@router.post("/login")
def login(username: str, password: str, db: Session = Depends(get_db)):
    """
    用戶登入

    - **username**: 用戶名
    - **password**: 密碼

    Returns:
    - **access_token**: JWT 訪問令牌
    - **token_type**: 令牌類型（bearer）
    - **user**: 用戶信息
    """
    user = UserService.authenticate_user(db, username, password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用戶名或密碼錯誤"
        )

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username},
        expires_delta=access_token_expires
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": user
    }


@router.get("/me", response_model=User)
def get_current_user(
    username: str,
    db: Session = Depends(get_db)
):
    """
    取得當前用戶信息

    需要提供有效的 username
    """
    user = UserService.get_user_by_username(db, username)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用戶未找到"
        )
    return user


@router.put("/me", response_model=User)
def update_current_user(
    username: str,
    user_update: UserUpdate,
    db: Session = Depends(get_db)
):
    """
    更新當前用戶信息

    - **full_name**: 全名（可選）
    - **password**: 新密碼（可選）
    """
    user = UserService.get_user_by_username(db, username)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用戶未找到"
        )

    updated_user = UserService.update_user(db, user, user_update)
    return updated_user

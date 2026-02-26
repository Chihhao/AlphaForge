from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime


class UserBase(BaseModel):
    """用戶基本信息"""
    email: EmailStr
    username: str
    full_name: Optional[str] = None


class UserCreate(UserBase):
    """用戶註冊信息"""
    password: str


class UserUpdate(BaseModel):
    """用戶更新信息"""
    full_name: Optional[str] = None
    password: Optional[str] = None


class User(UserBase):
    """用戶響應信息"""
    id: int
    is_active: bool
    virtual_balance: float
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

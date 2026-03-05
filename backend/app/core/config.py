import os
from typing import Optional
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """應用程式配置"""
    
    # 應用程式配置
    APP_NAME: str = "AlphaForge"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = os.getenv("DEBUG", "True").lower() == "true"
    
    # 数据库配置
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "sqlite:///./test.db"  # 开发环境使用 SQLite
    )
    SQLALCHEMY_ECHO: bool = DEBUG
    
    # JWT 配置
    SECRET_KEY: str = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    
    # CORS 配置
    BACKEND_CORS_ORIGINS: list = [
        "http://localhost",
        "http://localhost:3000",
        "http://10.0.4.3:3001",
        "http://localhost:8000",
        "https://junesnow39.synology.me",
    ]
    
    # 數據源配置
    STOCK_SEARCH_LIMIT: int = 20
    
    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()

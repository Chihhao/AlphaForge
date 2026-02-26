from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.db.database import Base, engine
from app.api.endpoints import users, stocks, trading

# 建立數據庫表
Base.metadata.create_all(bind=engine)

# 建立 FastAPI 應用
app = FastAPI(
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse

    from app.core.config import settings
    from app.db.database import Base, engine
    from app.api.endpoints import users, stocks, trading

    # 建立數據庫表
    Base.metadata.create_all(bind=engine)

    # 建立 FastAPI 應用
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description="台灣股市分析與模擬交易平台 API",
    )

    # CORS 中間件配置
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.BACKEND_CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 註冊路由
    app.include_router(users.router)
    app.include_router(stocks.router)
    app.include_router(trading.router)


    @app.get("/")
    def read_root():
        """根路由"""
        return {
            "app_name": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "description": "台灣股市分析與模擬交易平台 API",
            "docs": "/docs",
            "redoc": "/redoc",
        }


    @app.get("/health")
    def health_check():
        """健康檢查"""
        return {
            "status": "healthy",
            "app_name": settings.APP_NAME,
        }


    if __name__ == "__main__":
        import uvicorn
        uvicorn.run(
            "main:app",
            host="0.0.0.0",
            port=8000,
            reload=settings.DEBUG,
        )

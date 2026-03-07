# Build Timestamp: 2026-02-27T18:03:00 (Forcing build context change)
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.db.database import Base, engine
from app.api.endpoints import users, stocks, trading, indicators, glossary, market
from app.models.stock_price import StockPrice
from app.models.system_event import SystemEvent
from app.core.scheduler import start_scheduler, stop_scheduler



# 建立數據庫表
Base.metadata.create_all(bind=engine)

# 建立 FastAPI 應用
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="台灣股市分析與模擬交易平台 API",
)

@app.on_event("startup")
def startup_event():
    start_scheduler()

@app.on_event("shutdown")
def shutdown_event():
    stop_scheduler()


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
app.include_router(indicators.router)
app.include_router(glossary.router)
app.include_router(market.router)


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

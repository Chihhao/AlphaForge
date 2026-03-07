from datetime import datetime
from app.db.database import SessionLocal
from app.models.system_event import SystemEvent

class SystemLogger:
    """系統日誌服務，將訊息寫入資料庫供前端顯示"""

    @staticmethod
    def log(message: str, level: str = "INFO", category: str = "system"):
        """記錄一條訊息到資料庫"""
        db = SessionLocal()
        try:
            event = SystemEvent(
                level=level,
                message=message,
                category=category,
                timestamp=datetime.now()
            )
            db.add(event)
            db.commit()
            print(f"[{level}][{category}] {message}")
        except Exception as e:
            print(f"Failed to log system event: {e}")
            db.rollback()
        finally:
            db.close()

    @staticmethod
    def info(message: str, category: str = "system"):
        SystemLogger.log(message, "INFO", category)

    @staticmethod
    def success(message: str, category: str = "system"):
        SystemLogger.log(message, "SUCCESS", category)

    @staticmethod
    def warning(message: str, category: str = "system"):
        SystemLogger.log(message, "WARNING", category)

    @staticmethod
    def error(message: str, category: str = "system"):
        SystemLogger.log(message, "ERROR", category)

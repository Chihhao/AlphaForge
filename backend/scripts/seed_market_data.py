import sys
import os

from app.services.stock_sync_service import StockSyncService
from app.db.database import SessionLocal

def seed_data():
    db = SessionLocal()
    pool_ids = [
        "^TWII", "2330", "2317", "2454", "2308", "2382", "2881", "2882", "2412", "2891", "2303",
        "2886", "2884", "1216", "2002", "2885", "3231", "2603", "2892", "3045", "5871",
        "2890", "2207", "3008", "2357", "2618", "2609", "3481", "2409", "3037", "3711"
    ]
    print(f"Seeding {len(pool_ids)} stocks...")
    for sid in pool_ids:
        StockSyncService.sync_stock_data(db, sid, days=15)
    
    print("Seed complete.")

if __name__ == "__main__":
    seed_data()

import sys
import os
import argparse

# 將項目根目錄添加到 Python 路徑
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.stock_sync_service import StockSyncService


def main():
    parser = argparse.ArgumentParser(description="AlphaForge 股市數據初始化工具")
    parser.add_argument("--days", type=int, default=365, help="歷史數據天數 (預設 365 天)")
    parser.add_argument("--batch", type=int, default=50, help="批次大小 (預設 50)")
    parser.add_argument("--all", action="store_true", help="同步所有台股（耗時較長）")
    parser.add_argument("--limit", type=int, help="僅同步前 N 支股票（測試用）")

    args = parser.parse_args()

    print("=== AlphaForge 數據同步初始化 ===")
    
    if args.all:
        print(f"模式: 全同步 (天數: {args.days})")
        # 直接調用服務，但我們可以根據 limit 進行限制
        if args.limit:
            stock_ids = StockSyncService.get_all_stock_ids()[:args.limit]
            print(f"限制同步前 {args.limit} 支股票")
            from app.db.database import SessionLocal
            db = SessionLocal()
            try:
                for i, sid in enumerate(stock_ids):
                    StockSyncService.sync_stock_data(db, sid, days=args.days)
                    if (i + 1) % args.batch == 0:
                        print(f"已同步 {i + 1} 支股票...")
            finally:
                db.close()
            print("同步完成！")
        else:
            StockSyncService.sync_all_stocks(batch_size=args.batch)
    else:
        print("未指定 --all，目前僅支持全同步模式或透過 API 觸發增量更新。")
        print("範例: python scripts/init_stock_data.py --all --limit 10")

if __name__ == "__main__":
    main()

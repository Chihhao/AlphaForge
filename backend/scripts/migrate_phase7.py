"""
Phase 7 DB Migration: 新增籌碼面中長期 + 波動率 + 市場狀態欄位
用法: cd backend && ./.venv/bin/python scripts/migrate_phase7.py
"""
import sys, os
sys.path.insert(0, os.getcwd())

from app.db.database import engine
from sqlalchemy import text, inspect

COLUMNS_STOCK_FEATURES = [
    ("foreign_buy_10d", "FLOAT"),
    ("foreign_buy_20d", "FLOAT"),
    ("trust_buy_10d", "FLOAT"),
    ("trust_buy_20d", "FLOAT"),
    ("dealer_buy_10d", "FLOAT"),
    ("dealer_buy_20d", "FLOAT"),
    ("atr20", "FLOAT"),
    ("atr_pct", "FLOAT"),
    ("market_breadth", "FLOAT"),
    ("market_trend", "FLOAT"),
]

COLUMNS_BACKTEST_PARAMS = [
    ("is_atr_based", "BOOLEAN DEFAULT TRUE"),
]


def migrate():
    insp = inspect(engine)

    # stock_features
    existing_sf = {c["name"] for c in insp.get_columns("stock_features")}
    with engine.begin() as conn:
        for col_name, col_type in COLUMNS_STOCK_FEATURES:
            if col_name not in existing_sf:
                conn.execute(text(f"ALTER TABLE stock_features ADD COLUMN {col_name} {col_type}"))
                print(f"  + stock_features.{col_name}")
            else:
                print(f"  ~ stock_features.{col_name} already exists")

    # strategy_backtest_params
    existing_bp = {c["name"] for c in insp.get_columns("strategy_backtest_params")}
    with engine.begin() as conn:
        for col_name, col_type in COLUMNS_BACKTEST_PARAMS:
            if col_name not in existing_bp:
                conn.execute(text(f"ALTER TABLE strategy_backtest_params ADD COLUMN {col_name} {col_type}"))
                print(f"  + strategy_backtest_params.{col_name}")
            else:
                print(f"  ~ strategy_backtest_params.{col_name} already exists")

    print("Phase 7 migration complete.")


if __name__ == "__main__":
    migrate()

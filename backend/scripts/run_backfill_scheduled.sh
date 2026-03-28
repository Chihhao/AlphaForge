#!/bin/bash
cd /Users/chihhaolai/Documents/GitHub/AlphaForge/backend
LOG=scripts/backfill_revenue_eps.log

echo "=== $(date '+%Y-%m-%d %H:%M:%S') 開始回補 ===" >> "$LOG"
PYTHONPATH=. ./.venv/bin/python scripts/backfill_revenue_eps.py --resume >> "$LOG" 2>&1
echo "=== $(date '+%Y-%m-%d %H:%M:%S') 結束 ===" >> "$LOG"
echo "" >> "$LOG"

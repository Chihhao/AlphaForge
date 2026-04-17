"""公平維度對照（research only，不碰 production）。

背景：DIMENSIONS=['20d'] 是孤兒決策（只 26 筆 trades）。本腳本暫時把
AlphaMinerService.DIMENSIONS 擴到 5d/10d/20d/30d 各跑一次同 pipeline 訓練，
拿到 IC、prob、p-value、樣本數、勝率對照表。

- monkey-patch DIMENSIONS 只影響本 process
- monkey-patch _save_snapshot 為 noop，避免污染 alpha_miner_snapshot 表
- 直接呼叫 _train_all（同步），不走 multiprocessing 子程序
- 完全不寫任何 DB
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# 讓 backend/ 成為 import root
BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

# 載入 .env
try:
    from dotenv import load_dotenv
    load_dotenv(BACKEND / ".env")
except Exception:
    pass

from app.db.database import SessionLocal  # noqa: E402
from app.services.alpha_miner_service import AlphaMinerService  # noqa: E402


RESEARCH_DIMENSIONS = [
    {"key": "5d",  "forward_days": 5,  "threshold_low": 0.03, "threshold_high": 0.05, "direction": "long"},
    {"key": "10d", "forward_days": 10, "threshold_low": 0.03, "threshold_high": 0.05, "direction": "long"},
    {"key": "20d", "forward_days": 20, "threshold_low": 0.03, "threshold_high": 0.05, "direction": "long"},
    {"key": "30d", "forward_days": 30, "threshold_low": 0.03, "threshold_high": 0.05, "direction": "long"},
]


def _noop_save_snapshot(*args, **kwargs) -> None:
    print("[research] _save_snapshot skipped (research mode)")


def main() -> int:
    print(f"[research] DATABASE_URL={os.environ.get('DATABASE_URL', '(unset)')}")
    print(f"[research] 原始 DIMENSIONS = {[d['key'] for d in AlphaMinerService.DIMENSIONS]}")
    print(f"[research] 研究 DIMENSIONS = {[d['key'] for d in RESEARCH_DIMENSIONS]}")

    # monkey-patch（只影響本 process）
    AlphaMinerService.DIMENSIONS = RESEARCH_DIMENSIONS  # type: ignore[assignment]
    AlphaMinerService._save_snapshot = classmethod(_noop_save_snapshot)  # type: ignore[assignment]

    db = SessionLocal()
    try:
        result = AlphaMinerService._train_all(db)
    finally:
        db.close()

    print()
    print(f"train_period = {result.train_period}")
    print(f"test_period  = {result.test_period}")
    print(f"strategies_returned = {len(result.strategies)}")
    print()

    header = (
        f"{'dim':>5} | "
        f"{'ic':>7} | "
        f"{'p_corr':>8} | "
        f"{'sig':>4} | "
        f"{'n_train':>7} | "
        f"{'n_test':>6} | "
        f"{'wr_in':>6} | "
        f"{'wr_out':>6} | "
        f"{'wr_mkt':>6} | "
        f"{'wr_pos':>6} | "
        f"{'avg_top':>7} | "
        f"{'overfit':>7}"
    )
    print(header)
    print("-" * len(header))

    # 依 DIMENSIONS 順序顯示（不要被 _train_all 的 IC 排序覆蓋）
    by_dim = {r.time_dimension: r for r in result.strategies}
    for d in RESEARCH_DIMENSIONS:
        k = d["key"]
        r = by_dim.get(k)
        if r is None:
            print(f"{k:>5} | (no ranking returned — 資料不足或訓練失敗)")
            continue
        print(
            f"{k:>5} | "
            f"{r.ic:>+7.4f} | "
            f"{r.p_value_corrected:>8.4f} | "
            f"{('Y' if r.is_significant else 'N'):>4} | "
            f"{r.sample_count_train:>7d} | "
            f"{r.sample_count_test:>6d} | "
            f"{r.win_rate_insample*100:>5.1f}% | "
            f"{r.win_rate_outsample*100:>5.1f}% | "
            f"{r.market_win_rate*100:>5.1f}% | "
            f"{r.win_rate_positive*100:>5.1f}% | "
            f"{r.avg_return_top:>+6.2f}% | "
            f"{('Y' if r.overfit_warning else 'N'):>7}"
        )

    print()
    print("欄位說明：")
    print("  ic        = Spearman IC (test)")
    print("  p_corr    = Bonferroni-corrected p-value")
    print("  n_train   = 訓練集總列數")
    print("  n_test    = 測試集 Top20% 訊號數")
    print("  wr_in     = in-sample Top20% (>+3%) 勝率")
    print("  wr_out    = out-sample Top20% (>+3%) 勝率")
    print("  wr_mkt    = 測試集全市場 (>+3%) 基準")
    print("  wr_pos    = out-sample Top20% (>0%) 真實勝率")
    print("  avg_top   = out-sample Top20% 平均報酬")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

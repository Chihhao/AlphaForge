"""Phase 1: 對結案 picks 跑全因子 ablation 診斷。

職責: 從 NAS Postgres pull stock_picks (concluded) + 對應 stock_features,
跑 per-factor IC + quality gate impact + universe slice, 輸出 markdown report。

純 read-only, 不改 schema 不改 production。

Usage (從 backend/ 目錄):
    ./.venv/bin/python -m scripts.research_factor_ablation
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd
from scipy import stats
from sqlalchemy import create_engine, text


TAIPEI_TZ = timezone(timedelta(hours=8))

FACTOR_COLUMNS = [
    # 技術 (價格 / MA / bias / RSI / KD / MACD / 布林)
    "change_pct",
    "ma5", "ma10", "ma20", "ma60",
    "bias5", "bias10", "bias20",
    "rsi14", "rsi2",
    "k", "d",
    "macd_dif", "macd_dea", "macd_osc",
    "bb_pctb",
    "vol_ratio",
    "price_vs_high20", "ma_trend",
    "atr20", "atr_pct", "ivol_20d",
    "log_amihud_20d",
    "divergence_avg",
    # 基本面
    "yield_rate", "roe", "pb_ratio", "revenue_yoy",
    "rev_surprise", "rev_accel",
    # 籌碼
    "foreign_net_buy", "foreign_buy_5d", "foreign_buy_10d", "foreign_buy_20d",
    "trust_net_buy", "trust_buy_5d", "trust_buy_10d", "trust_buy_20d",
    "dealer_net_buy", "dealer_buy_5d", "dealer_buy_10d", "dealer_buy_20d",
    "margin_chg_5d", "short_chg_5d",
    "foreign_hold_pct", "foreign_hold_chg_5d",
    "sector_rs",
    # 市場
    "market_pcr", "etf_net_flow_5d", "market_breadth", "market_trend",
]


def _join_picks_features(picks: pd.DataFrame, features: pd.DataFrame) -> pd.DataFrame:
    picks = picks.copy()
    features = features.copy()
    picks["_d"] = pd.to_datetime(picks["pick_date"]).dt.date.astype(str)
    features["_d"] = pd.to_datetime(features["date"]).dt.date.astype(str)
    merged = picks.merge(
        features.drop(columns=["date"]),
        left_on=["stock_id", "_d"],
        right_on=["stock_id", "_d"],
        how="inner",
        suffixes=("", "_feat"),
    )
    return merged.drop(columns=["_d"])


def per_factor_ic(df: pd.DataFrame, factors: list[str]) -> pd.DataFrame:
    rows = []
    for factor in factors:
        if factor not in df.columns:
            rows.append({"factor": factor, "n": 0, "ic": float("nan"), "p_value": float("nan"),
                         "top_q_wr": float("nan"), "bot_q_wr": float("nan"),
                         "top_q_avg": float("nan"), "bot_q_avg": float("nan"), "spread_pp": float("nan")})
            continue
        sub = df[[factor, "return_pct"]].dropna()
        n = len(sub)
        if n < 10:
            rows.append({"factor": factor, "n": n, "ic": float("nan"), "p_value": float("nan"),
                         "top_q_wr": float("nan"), "bot_q_wr": float("nan"),
                         "top_q_avg": float("nan"), "bot_q_avg": float("nan"), "spread_pp": float("nan")})
            continue
        ic, p_value = stats.spearmanr(sub[factor], sub["return_pct"])
        try:
            sub = sub.copy()
            sub["_q"] = pd.qcut(sub[factor], 5, labels=False, duplicates="drop")
        except ValueError:
            sub["_q"] = pd.NA
        top = sub[sub["_q"] == 4]
        bot = sub[sub["_q"] == 0]
        top_q_wr = (top["return_pct"] > 0).mean() * 100 if len(top) else float("nan")
        bot_q_wr = (bot["return_pct"] > 0).mean() * 100 if len(bot) else float("nan")
        top_q_avg = top["return_pct"].mean() if len(top) else float("nan")
        bot_q_avg = bot["return_pct"].mean() if len(bot) else float("nan")
        spread_pp = top_q_wr - bot_q_wr if not (pd.isna(top_q_wr) or pd.isna(bot_q_wr)) else float("nan")
        rows.append({
            "factor": factor, "n": n,
            "ic": float(ic) if not pd.isna(ic) else float("nan"),
            "p_value": float(p_value) if not pd.isna(p_value) else float("nan"),
            "top_q_wr": top_q_wr, "bot_q_wr": bot_q_wr,
            "top_q_avg": top_q_avg, "bot_q_avg": bot_q_avg,
            "spread_pp": spread_pp,
        })
    return pd.DataFrame(rows).sort_values("ic", ascending=False, na_position="last")


def quality_gate_impact(df: pd.DataFrame, gate_col: str = "quality_gate_passed") -> dict:
    if gate_col not in df.columns:
        sub = df.dropna(subset=["return_pct"])
        n = len(sub)
        return {
            "passed": {"n": n,
                       "wr": (sub["return_pct"] > 0).mean() * 100 if n else float("nan"),
                       "avg": sub["return_pct"].mean() if n else float("nan")},
            "failed": {"n": 0, "wr": float("nan"), "avg": float("nan")},
        }
    result = {}
    for label, val in [("passed", True), ("failed", False)]:
        sub = df[df[gate_col] == val].dropna(subset=["return_pct"])
        n = len(sub)
        result[label] = {
            "n": n,
            "wr": (sub["return_pct"] > 0).mean() * 100 if n else float("nan"),
            "avg": sub["return_pct"].mean() if n else float("nan"),
        }
    return result


def universe_slice_alpha(df: pd.DataFrame, by: str) -> pd.DataFrame:
    if by not in df.columns:
        return pd.DataFrame([{"slice": "__all__", "n": len(df),
                              "wr": (df["return_pct"] > 0).mean() * 100 if len(df) else float("nan"),
                              "avg": df["return_pct"].mean() if len(df) else float("nan")}])
    rows = []
    for slice_val, sub in df.groupby(by):
        sub = sub.dropna(subset=["return_pct"])
        n = len(sub)
        rows.append({
            "slice": str(slice_val),
            "n": n,
            "wr": (sub["return_pct"] > 0).mean() * 100 if n else float("nan"),
            "avg": sub["return_pct"].mean() if n else float("nan"),
        })
    return pd.DataFrame(rows).sort_values("n", ascending=False)


# ── runtime helpers (NAS Postgres + report rendering) ────────


def _load_db_url() -> str:
    """從 backend/.env 讀 DATABASE_URL (NAS Postgres)。"""
    env = Path(__file__).resolve().parents[1] / ".env"
    if not env.exists():
        raise RuntimeError(f"backend/.env not found at {env}")
    for line in env.read_text().splitlines():
        line = line.strip()
        if line.startswith("DATABASE_URL="):
            return line.split("=", 1)[1]
    raise RuntimeError("DATABASE_URL not in backend/.env")


def _fetch_picks_features(engine) -> pd.DataFrame:
    """從 NAS 拉結案 trades + 對應 entry_date 的 features。

    Source table: strategy_miner_trades (結案 trades, ~27k 筆)
      - strategy_id ('5d' / '10d' / '20d' / '30d' / *_short) → time_dimension + direction
      - entry_date 對應 pick_date
      - return_pct / exit_reason / hold_days 都有
    """
    sql_picks = text("""
        SELECT
            stock_id,
            entry_date AS pick_date,
            return_pct,
            exit_reason,
            hold_days,
            strategy_id AS time_dimension,
            CASE WHEN strategy_id LIKE '%_short' THEN 'short' ELSE 'long' END AS direction
        FROM strategy_miner_trades
        WHERE return_pct IS NOT NULL
    """)
    sql_feats = text("""
        SELECT * FROM stock_features
        WHERE date >= (SELECT MIN(entry_date) FROM strategy_miner_trades WHERE return_pct IS NOT NULL)
    """)
    with engine.connect() as conn:
        picks = pd.read_sql(sql_picks, conn)
        features = pd.read_sql(sql_feats, conn)
    return _join_picks_features(picks, features)


def _render_report(ic_df: pd.DataFrame, gate: dict, slice_dim: pd.DataFrame,
                   slice_dir: pd.DataFrame, n_total: int) -> str:
    now = datetime.now(TAIPEI_TZ).strftime("%Y-%m-%d %H:%M")
    today = datetime.now(TAIPEI_TZ).strftime("%Y-%m-%d")
    lines = [
        "###### tags: `日報`,`AlphaForge`,`alpha 研究`,`factor-ablation`",
        "",
        "# Phase 1 — 全因子 Ablation Report",
        "",
        f"`文件版本: {today}a`",
        "",
        f"產生時間: {now} (Asia/Taipei)",
        "",
        f"## 樣本: {n_total} 結案 picks",
        "",
        "## Per-Factor IC (Spearman 排序; 只列 n >= 30)",
        "",
        "| 因子 | n | IC | p | top-q wr | bot-q wr | spread (pp) | top-q avg | bot-q avg |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for _, r in ic_df.iterrows():
        if r["n"] < 30:
            continue
        ic = r["ic"]
        p = r["p_value"]
        if pd.isna(ic):
            continue
        lines.append(
            f"| {r['factor']} | {int(r['n'])} | {ic:+.3f} | {p:.3f} | "
            f"{r['top_q_wr']:.1f}% | {r['bot_q_wr']:.1f}% | {r['spread_pp']:+.1f} | "
            f"{r['top_q_avg']:+.2f}% | {r['bot_q_avg']:+.2f}% |"
        )
    lines += ["", "## Quality Gate 影響", "",
              f"- passed: n={gate['passed']['n']}, wr={gate['passed']['wr']:.1f}%, avg={gate['passed']['avg']:+.2f}%",
              f"- failed: n={gate['failed']['n']}, wr={gate['failed']['wr']:.1f}%, avg={gate['failed']['avg']:+.2f}%",
              "", "## 維度切片", "",
              "| dimension | n | wr | avg |", "|---|---|---|---|"]
    for _, r in slice_dim.iterrows():
        lines.append(f"| {r['slice']} | {int(r['n'])} | {r['wr']:.1f}% | {r['avg']:+.2f}% |")
    lines += ["", "## 方向切片", "",
              "| direction | n | wr | avg |", "|---|---|---|---|"]
    for _, r in slice_dir.iterrows():
        lines.append(f"| {r['slice']} | {int(r['n'])} | {r['wr']:.1f}% | {r['avg']:+.2f}% |")
    lines += ["", "## 結論建議", "", "(由 user / 後續 session 看完數字後填)", ""]
    return "\n".join(lines)


def main() -> int:
    db_url = _load_db_url()
    engine = create_engine(db_url, pool_pre_ping=True)
    print("loading picks + features from NAS Postgres ...")
    df = _fetch_picks_features(engine)
    print(f"  loaded {len(df)} rows")
    if len(df) == 0:
        print("ERROR: empty join, abort")
        return 1
    ic_df = per_factor_ic(df, FACTOR_COLUMNS)
    gate = quality_gate_impact(df)
    slice_dim = universe_slice_alpha(df, by="time_dimension")
    slice_dir = universe_slice_alpha(df, by="direction")
    report = _render_report(ic_df, gate, slice_dim, slice_dir, len(df))

    out_dir = Path(__file__).resolve().parents[2] / "docs" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{datetime.now(TAIPEI_TZ).strftime('%Y-%m-%d')}-factor-ablation.md"
    out_path.write_text(report, encoding="utf-8")
    print(f"report → {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

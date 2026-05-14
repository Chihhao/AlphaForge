###### tags: `專案`,`AlphaForge`,`alpha 研究`,`pivot`,`plan`

# Alpha Pivot — 籌碼/法人/事件訊號 Implementation Plan

`文件版本: 2026-05-14a`

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task。Steps use checkbox (`- [ ]`) syntax for tracking。

**Goal**: 在不動 production 推薦邏輯前提下, (Phase 1) 跑 40+ 因子 ablation 找出真正的正向 / 負向 / 雜訊因子; (Phase 2) 對既有籌碼資料做 event-driven 分析 (連續淨買事件 → 後續報酬), 證明是否有 incremental orthogonal alpha。

**Architecture**: 兩個 research scripts (`research_factor_ablation.py` + `research_chip_events.py`), 純 read-only 從 NAS Postgres pull (stock_picks + stock_features + stock_chip_data + stock_prices), 用 pandas 跑統計, 輸出 markdown report。Helper 函式都用 DataFrame 參數 (pure function 好 unit test), 用 mock data 跑 unit test, 不戰真實 DB。

**Tech Stack**: Python 3.9.1 + pandas + numpy + scipy.stats + SQLAlchemy (連 NAS Postgres) + pytest (mock data unit test) + matplotlib (optional 視覺化, YAGNI 先不做)。

**Spec**: `docs/superpowers/specs/2026-05-14-alpha-pivot-chip-signals-design.md`

**Spec 已過時 (要注意)**: spec §1.2 寫 Phase 2 要建 chip_crawler / migration / backfill — **不必做**。`stock_chip_data` 表 NAS 上已有 93 萬筆 (2024-03~2026-05), `stock_features` 已 derive 15 個籌碼因子。Phase 2 改成「對既有資料跑 event detection」。

---

## File Structure

**新增**:
- `backend/scripts/research_factor_ablation.py` — Phase 1 全因子 ablation runner
- `backend/scripts/research_chip_events.py` — Phase 2 連續淨買 event 分析
- `backend/tests/test_research_factor_ablation.py` — Phase 1 unit tests (mock df)
- `backend/tests/test_research_chip_events.py` — Phase 2 unit tests (mock df)

**修改**: 無

**Runtime 產出 (不 commit, 跑時生成)**:
- `docs/reports/2026-MM-DD-factor-ablation.md` — Phase 1 report
- `docs/reports/2026-MM-DD-chip-event-prototype.md` — Phase 2 report

**不動**:
- 既有 `stock_picks` / `stock_features` / `stock_chip_data` / `stock_prices` schema
- 既有 `alpha_miner_service` / `screener_service` / `feature_service`
- 既有 scheduler / production endpoints / UI

---

## Phase 1 — 全因子 Ablation 診斷

### Task 1: `research_factor_ablation.py` 骨架 + 資料載入

**Files:**
- Create: `backend/scripts/research_factor_ablation.py`
- Create: `backend/tests/test_research_factor_ablation.py`

- [ ] **Step 1: 寫 failing tests**

寫到 `backend/tests/test_research_factor_ablation.py`:

```python
import pandas as pd
import pytest

from scripts.research_factor_ablation import FACTOR_COLUMNS, _join_picks_features


def test_factor_columns_list_includes_chip():
    """FACTOR_COLUMNS 必須涵蓋技術 / 基本面 / 籌碼 / 市場 / 波動 / 背離 全部。"""
    # 技術
    assert "rsi14" in FACTOR_COLUMNS
    assert "ma_trend" in FACTOR_COLUMNS
    # 基本面
    assert "roe" in FACTOR_COLUMNS
    assert "rev_surprise" in FACTOR_COLUMNS
    # 籌碼
    assert "foreign_buy_5d" in FACTOR_COLUMNS
    assert "trust_buy_10d" in FACTOR_COLUMNS
    assert "dealer_buy_20d" in FACTOR_COLUMNS
    assert "margin_chg_5d" in FACTOR_COLUMNS
    assert "short_chg_5d" in FACTOR_COLUMNS
    # 流動性 / 波動率 / 背離
    assert "log_amihud_20d" in FACTOR_COLUMNS
    assert "atr_pct" in FACTOR_COLUMNS
    assert "divergence_avg" in FACTOR_COLUMNS


def test_join_picks_features_matches_by_sid_date():
    picks = pd.DataFrame([
        {"stock_id": "2330", "pick_date": "2026-05-01", "return_pct": 5.0, "time_dimension": "5d"},
        {"stock_id": "2454", "pick_date": "2026-05-02", "return_pct": -2.0, "time_dimension": "10d"},
    ])
    features = pd.DataFrame([
        {"stock_id": "2330", "date": "2026-05-01", "rsi14": 60.0, "foreign_buy_5d": 1000.0},
        {"stock_id": "2454", "date": "2026-05-02", "rsi14": 30.0, "foreign_buy_5d": -500.0},
        {"stock_id": "9999", "date": "2026-05-01", "rsi14": 50.0, "foreign_buy_5d": 0.0},  # 不 match
    ])
    out = _join_picks_features(picks, features)
    assert len(out) == 2
    assert "rsi14" in out.columns
    assert "return_pct" in out.columns
    row_2330 = out[out["stock_id"] == "2330"].iloc[0]
    assert row_2330["rsi14"] == 60.0
    assert row_2330["return_pct"] == 5.0
```

- [ ] **Step 2: 跑 test 看到 fail**

```bash
cd /Users/chihhaolai/Documents/GitHub/AlphaForge/backend
./.venv/bin/python -m pytest tests/test_research_factor_ablation.py -v
```

預期: `ModuleNotFoundError` / `ImportError`

- [ ] **Step 3: 寫 minimal impl**

寫 `backend/scripts/research_factor_ablation.py`:

```python
"""Phase 1: 對結案 picks 跑全因子 ablation 診斷。

職責: 從 NAS Postgres pull stock_picks (concluded) + 對應 stock_features,
跑 per-factor IC + quality gate impact + universe slice, 輸出 markdown report。

純 read-only, 不改 schema 不改 production。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd

# 對齊 stock_feature.py 的 40+ 因子列表 (不含 id/stock_id/date/close/volume 等 non-feature)
FACTOR_COLUMNS = [
    # 技術 (價格 / MA / bias / RSI / KD / MACD / 布林)
    "change_pct",
    "ma5", "ma10", "ma20", "ma60",
    "bias5", "bias10", "bias20",
    "rsi14", "rsi2",
    "k", "d",
    "macd_dif", "macd_dea", "macd_osc",
    "bb_pctb",
    # 量
    "vol_ratio",
    # 技術新 (Phase 5B / 7)
    "price_vs_high20", "ma_trend",
    "atr20", "atr_pct", "ivol_20d",
    "log_amihud_20d",
    "divergence_avg",
    # 基本面
    "yield_rate", "roe", "pb_ratio", "revenue_yoy",
    "rev_surprise", "rev_accel",
    # 籌碼 (Phase 4B / 5B / 6 / 7 / 9)
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
    """join stock_picks (用 pick_date) + stock_features (用 date) by (stock_id, date)。
    inner join, 結果含 pick 的所有欄位 + features 的因子欄位。
    """
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
```

- [ ] **Step 4: 跑 test 看到 pass**

```bash
./.venv/bin/python -m pytest tests/test_research_factor_ablation.py -v
```

預期: 2 passed

- [ ] **Step 5: commit**

```bash
cd /Users/chihhaolai/Documents/GitHub/AlphaForge
git add backend/scripts/research_factor_ablation.py backend/tests/test_research_factor_ablation.py
git commit -m "feat(research): factor ablation scaffold + FACTOR_COLUMNS"
```

---

### Task 2: `per_factor_ic()` — Spearman IC + quintile spread

**Files:**
- Modify: `backend/scripts/research_factor_ablation.py`
- Modify: `backend/tests/test_research_factor_ablation.py`

- [ ] **Step 1: 寫 failing tests**

加到 test 檔結尾:

```python
import numpy as np
from scripts.research_factor_ablation import per_factor_ic


def test_per_factor_ic_strong_positive_signal():
    """因子值跟報酬完全 monotonic 正相關 → IC ≈ 1, spread 大。"""
    n = 100
    rng = np.random.default_rng(42)
    factor = rng.uniform(0, 100, n)
    # return 跟 factor 完全 positive 相關 + 小 noise
    ret = factor / 100.0 * 10 - 5 + rng.normal(0, 0.5, n)
    df = pd.DataFrame({"factor_x": factor, "return_pct": ret})
    out = per_factor_ic(df, ["factor_x"])
    row = out[out["factor"] == "factor_x"].iloc[0]
    assert row["ic"] > 0.8
    assert row["spread_pp"] > 5.0     # top quintile - bot quintile > 5 percentage point
    assert row["n"] == n


def test_per_factor_ic_no_signal():
    """因子值跟報酬無相關 → IC ≈ 0, spread 小。"""
    n = 200
    rng = np.random.default_rng(7)
    factor = rng.uniform(0, 100, n)
    ret = rng.normal(0, 5, n)      # 跟 factor 獨立
    df = pd.DataFrame({"factor_x": factor, "return_pct": ret})
    out = per_factor_ic(df, ["factor_x"])
    row = out[out["factor"] == "factor_x"].iloc[0]
    assert abs(row["ic"]) < 0.2


def test_per_factor_ic_skips_all_null_factor():
    """若整欄 NaN, 函式不 crash, 輸出 n=0。"""
    df = pd.DataFrame({"factor_x": [None]*10, "return_pct": [1.0]*10})
    out = per_factor_ic(df, ["factor_x"])
    row = out[out["factor"] == "factor_x"].iloc[0]
    assert row["n"] == 0
    assert pd.isna(row["ic"])
```

- [ ] **Step 2: 跑 test 看到 fail**

```bash
./.venv/bin/python -m pytest tests/test_research_factor_ablation.py::test_per_factor_ic_strong_positive_signal -v
```

預期: `ImportError: cannot import name 'per_factor_ic'`

- [ ] **Step 3: 寫實作**

加進 `backend/scripts/research_factor_ablation.py`:

```python
from scipy import stats


def per_factor_ic(df: pd.DataFrame, factors: list[str]) -> pd.DataFrame:
    """每個因子算:
      - ic: Spearman 相關係數 (factor value vs return_pct), 排序相關性
      - p_value: 顯著性
      - top_q_wr, bot_q_wr: top / bottom quintile 的勝率
      - top_q_avg, bot_q_avg: top / bottom quintile 平均報酬
      - spread_pp: top wr - bot wr (percentage point)
      - n: 有效樣本數 (factor 與 return 都 not null)

    NaN policy: 各因子個別處理, 整欄全 NaN 時 n=0 / ic=NaN。
    """
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
        # quintile cut
        try:
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
            "ic": float(ic), "p_value": float(p_value),
            "top_q_wr": top_q_wr, "bot_q_wr": bot_q_wr,
            "top_q_avg": top_q_avg, "bot_q_avg": bot_q_avg,
            "spread_pp": spread_pp,
        })
    return pd.DataFrame(rows).sort_values("ic", ascending=False, na_position="last")
```

注意: file 開頭加 `from scipy import stats` import。

- [ ] **Step 4: 跑 test 看到 pass**

```bash
./.venv/bin/python -m pytest tests/test_research_factor_ablation.py -v
```

預期: 5 passed (Task 1 的 2 + Task 2 的 3)

- [ ] **Step 5: commit**

```bash
cd /Users/chihhaolai/Documents/GitHub/AlphaForge
git add backend/scripts/research_factor_ablation.py backend/tests/test_research_factor_ablation.py
git commit -m "feat(research): per_factor_ic Spearman + quintile spread"
```

---

### Task 3: `quality_gate_impact()` + `universe_slice_alpha()`

**Files:**
- Modify: `backend/scripts/research_factor_ablation.py`
- Modify: `backend/tests/test_research_factor_ablation.py`

- [ ] **Step 1: 寫 failing tests**

加到 test 檔:

```python
from scripts.research_factor_ablation import quality_gate_impact, universe_slice_alpha


def test_quality_gate_impact_separates_pass_fail():
    """有 quality_gate_passed=True / False 的 picks, 應該各自算 wr / avg / n。"""
    df = pd.DataFrame([
        {"quality_gate_passed": True, "return_pct": 5.0},
        {"quality_gate_passed": True, "return_pct": 3.0},
        {"quality_gate_passed": True, "return_pct": -1.0},
        {"quality_gate_passed": False, "return_pct": -3.0},
        {"quality_gate_passed": False, "return_pct": -2.0},
    ])
    out = quality_gate_impact(df)
    assert out["passed"]["n"] == 3
    assert out["passed"]["wr"] == pytest.approx(66.67, abs=0.5)
    assert out["failed"]["n"] == 2
    assert out["failed"]["wr"] == 0.0


def test_universe_slice_alpha_by_dimension():
    """按 time_dimension 切片, 各維度算自己的 wr / avg / n。"""
    df = pd.DataFrame([
        {"time_dimension": "5d", "return_pct": 2.0},
        {"time_dimension": "5d", "return_pct": -1.0},
        {"time_dimension": "5d", "return_pct": 3.0},
        {"time_dimension": "10d", "return_pct": -2.0},
        {"time_dimension": "10d", "return_pct": -1.0},
    ])
    out = universe_slice_alpha(df, by="time_dimension")
    out_dict = {row["slice"]: row for _, row in out.iterrows()}
    assert out_dict["5d"]["n"] == 3
    assert out_dict["5d"]["wr"] == pytest.approx(66.67, abs=0.5)
    assert out_dict["10d"]["n"] == 2
    assert out_dict["10d"]["wr"] == 0.0
```

- [ ] **Step 2: 跑 test 看到 fail**

預期: ImportError

- [ ] **Step 3: 寫實作**

加進 `research_factor_ablation.py`:

```python
def quality_gate_impact(df: pd.DataFrame, gate_col: str = "quality_gate_passed") -> dict:
    """有/沒 pass quality gate 兩組對比。
    回 {"passed": {n, wr, avg}, "failed": {n, wr, avg}}。
    若 gate_col 不在 df 內, 整體當 "passed" group。
    """
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
    """按 by 欄位切片, 每組算 n / wr / avg。
    常用 by: time_dimension / direction / 自訂 market_cap_bucket 等。
    """
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
```

- [ ] **Step 4: 跑 test 看到 pass**

預期: 7 passed (累計)

- [ ] **Step 5: commit**

```bash
cd /Users/chihhaolai/Documents/GitHub/AlphaForge
git add backend/scripts/research_factor_ablation.py backend/tests/test_research_factor_ablation.py
git commit -m "feat(research): quality_gate_impact + universe_slice_alpha"
```

---

### Task 4: `main()` — 連 NAS Postgres + 跑分析 + 寫 report

**Files:**
- Modify: `backend/scripts/research_factor_ablation.py`

- [ ] **Step 1: 寫 main 連線 + 跑 report**

加進 `research_factor_ablation.py`:

```python
from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine, text

TAIPEI_TZ = timezone(timedelta(hours=8))


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
    """從 NAS 拉結案 picks + 對應日 features。"""
    sql_picks = text("""
        SELECT stock_id, pick_date, return_pct, time_dimension, direction,
               exit_reason, days_held
        FROM stock_picks
        WHERE exit_reason IS NOT NULL
          AND return_pct IS NOT NULL
    """)
    sql_feats = text("""
        SELECT * FROM stock_features
        WHERE date >= (SELECT MIN(pick_date) FROM stock_picks WHERE exit_reason IS NOT NULL)
    """)
    picks = pd.read_sql(sql_picks, engine)
    features = pd.read_sql(sql_feats, engine)
    return _join_picks_features(picks, features)


def _render_report(ic_df: pd.DataFrame, gate: dict, slice_dim: pd.DataFrame,
                   slice_dir: pd.DataFrame, n_total: int) -> str:
    now = datetime.now(TAIPEI_TZ).strftime("%Y-%m-%d %H:%M")
    lines = [
        "###### tags: `日報`,`AlphaForge`,`alpha 研究`,`factor-ablation`",
        "",
        "# Phase 1 — 全因子 Ablation Report",
        "",
        f"`文件版本: {datetime.now(TAIPEI_TZ).strftime('%Y-%m-%d')}a`",
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
        lines.append(
            f"| {r['factor']} | {int(r['n'])} | {r['ic']:+.3f} | {r['p_value']:.3f} | "
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
```

- [ ] **Step 2: 跑 script (真戰 NAS Postgres)**

```bash
cd /Users/chihhaolai/Documents/GitHub/AlphaForge/backend
./.venv/bin/python -m scripts.research_factor_ablation
```

預期: stdout 印 `loaded N rows` (N 應 > 100), `report → docs/reports/YYYY-MM-DD-factor-ablation.md`, exit 0。

- [ ] **Step 3: 看 report + commit**

```bash
cd /Users/chihhaolai/Documents/GitHub/AlphaForge
cat docs/reports/$(date +%Y-%m-%d)-factor-ablation.md | head -60
```

讀 report, 列出: top-5 正向 IC 因子 / bottom-5 負向 IC 因子 / quality gate 是否在拖累 / 5d vs 10d vs 20d 切片差異。

```bash
git add backend/scripts/research_factor_ablation.py docs/reports/$(date +%Y-%m-%d)-factor-ablation.md
git commit -m "feat(research): factor ablation runner + first report"
```

- [ ] **Step 4: user review report**

stop. ask user 「ablation report 在 `docs/reports/<date>-factor-ablation.md`, 看完決定砍哪些因子 / 留哪些 / 加權哪些, 再進 Phase 2」。

---

## Phase 2 — 籌碼連續淨買 Event 分析

### Task 5: `research_chip_events.py` 骨架 + event detection

**Files:**
- Create: `backend/scripts/research_chip_events.py`
- Create: `backend/tests/test_research_chip_events.py`

- [ ] **Step 1: 寫 failing tests**

寫 `backend/tests/test_research_chip_events.py`:

```python
import pandas as pd
import pytest

from scripts.research_chip_events import find_consecutive_buy_events


def test_find_consecutive_buy_events_basic():
    """連續 3 日外資淨買 → 1 個 event。"""
    df = pd.DataFrame([
        {"stock_id": "2330", "date": "2026-05-01", "foreign_net_buy": 100},
        {"stock_id": "2330", "date": "2026-05-02", "foreign_net_buy": 200},
        {"stock_id": "2330", "date": "2026-05-03", "foreign_net_buy": 150},
        {"stock_id": "2330", "date": "2026-05-04", "foreign_net_buy": -50},   # 斷
        {"stock_id": "2330", "date": "2026-05-05", "foreign_net_buy": 80},
    ])
    events = find_consecutive_buy_events(df, factor_col="foreign_net_buy", min_days=3)
    assert len(events) == 1
    e = events.iloc[0]
    assert e["stock_id"] == "2330"
    assert str(e["event_date"]) == "2026-05-03"
    assert e["consecutive_days"] == 3
    assert e["cumulative_net_buy"] == 450


def test_find_consecutive_buy_events_min_days_filter():
    """只連續 2 日 (< min_days=3), 不算 event。"""
    df = pd.DataFrame([
        {"stock_id": "2330", "date": "2026-05-01", "foreign_net_buy": 100},
        {"stock_id": "2330", "date": "2026-05-02", "foreign_net_buy": 200},
        {"stock_id": "2330", "date": "2026-05-03", "foreign_net_buy": -50},
    ])
    events = find_consecutive_buy_events(df, factor_col="foreign_net_buy", min_days=3)
    assert len(events) == 0


def test_find_consecutive_buy_events_multi_stock():
    """多 stock 各自獨立計算。"""
    df = pd.DataFrame([
        {"stock_id": "2330", "date": "2026-05-01", "foreign_net_buy": 100},
        {"stock_id": "2330", "date": "2026-05-02", "foreign_net_buy": 200},
        {"stock_id": "2330", "date": "2026-05-03", "foreign_net_buy": 50},
        {"stock_id": "2454", "date": "2026-05-01", "foreign_net_buy": 80},
        {"stock_id": "2454", "date": "2026-05-02", "foreign_net_buy": 90},
        {"stock_id": "2454", "date": "2026-05-03", "foreign_net_buy": 110},
    ])
    events = find_consecutive_buy_events(df, factor_col="foreign_net_buy", min_days=3)
    assert len(events) == 2
    assert set(events["stock_id"].tolist()) == {"2330", "2454"}
```

- [ ] **Step 2: 跑 test 看到 fail**

預期: `ModuleNotFoundError`

- [ ] **Step 3: 寫實作**

寫 `backend/scripts/research_chip_events.py`:

```python
"""Phase 2: 籌碼連續淨買 event 偵測 + 事件後報酬分析。

純 read-only, 用既有 stock_chip_data (NAS 93 萬筆) + stock_prices 跑分析。
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd
import numpy as np

TAIPEI_TZ = timezone(timedelta(hours=8))


def find_consecutive_buy_events(df: pd.DataFrame, factor_col: str, min_days: int = 3) -> pd.DataFrame:
    """對每個 stock 找 factor_col > 0 連續 ≥ min_days 的 event。

    Event 定義: 連續 N 日同正後**第 N 日**該日為 event date (即連續 streak 的最後一天)。
    Args:
        df: 含 stock_id / date / factor_col 三欄, 按 (stock_id, date) 排序
        factor_col: e.g. 'foreign_net_buy' / 'trust_net_buy' / 'dealer_net_buy'
        min_days: 連續日數門檻
    Return:
        DataFrame [stock_id, event_date, consecutive_days, cumulative_net_buy]
    """
    df = df.copy().sort_values(["stock_id", "date"]).reset_index(drop=True)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["_positive"] = df[factor_col] > 0
    # group by stock, 計算 streak length
    df["_streak_group"] = (df["_positive"] != df.groupby("stock_id")["_positive"].shift()).cumsum()
    streaks = (
        df[df["_positive"]]
        .groupby(["stock_id", "_streak_group"])
        .agg(
            event_date=("date", "last"),
            consecutive_days=(factor_col, "size"),
            cumulative_net_buy=(factor_col, "sum"),
        )
        .reset_index()
        .drop(columns=["_streak_group"])
    )
    return streaks[streaks["consecutive_days"] >= min_days].reset_index(drop=True)
```

- [ ] **Step 4: 跑 test 看到 pass**

```bash
cd /Users/chihhaolai/Documents/GitHub/AlphaForge/backend
./.venv/bin/python -m pytest tests/test_research_chip_events.py -v
```

預期: 3 passed

- [ ] **Step 5: commit**

```bash
cd /Users/chihhaolai/Documents/GitHub/AlphaForge
git add backend/scripts/research_chip_events.py backend/tests/test_research_chip_events.py
git commit -m "feat(research): chip event detection (consecutive net buy)"
```

---

### Task 6: `event_post_returns()` — 事件後 N 日報酬

**Files:**
- Modify: `backend/scripts/research_chip_events.py`
- Modify: `backend/tests/test_research_chip_events.py`

- [ ] **Step 1: 寫 failing tests**

加到 test 檔:

```python
from scripts.research_chip_events import event_post_returns


def test_event_post_returns_5d():
    """event 後 5 個交易日報酬計算 (使用 trading day index, 不是 calendar)。"""
    prices = pd.DataFrame([
        {"stock_id": "2330", "date": "2026-05-01", "close": 100.0},
        {"stock_id": "2330", "date": "2026-05-02", "close": 102.0},
        {"stock_id": "2330", "date": "2026-05-03", "close": 105.0},
        {"stock_id": "2330", "date": "2026-05-04", "close": 103.0},
        {"stock_id": "2330", "date": "2026-05-05", "close": 108.0},
        {"stock_id": "2330", "date": "2026-05-06", "close": 110.0},   # event+5d 應該是這天
    ])
    events = pd.DataFrame([
        {"stock_id": "2330", "event_date": pd.to_datetime("2026-05-01").date(),
         "consecutive_days": 3, "cumulative_net_buy": 500},
    ])
    out = event_post_returns(events, prices, horizons=[5])
    row = out.iloc[0]
    # event_date=5/1 (close=100), event+5 trading days = 5/6 (close=110) → +10%
    assert row["ret_5d"] == pytest.approx(10.0, abs=0.1)


def test_event_post_returns_skips_when_horizon_overflows():
    """event 後沒夠交易日 → ret = NaN。"""
    prices = pd.DataFrame([
        {"stock_id": "2330", "date": "2026-05-01", "close": 100.0},
        {"stock_id": "2330", "date": "2026-05-02", "close": 102.0},
    ])
    events = pd.DataFrame([
        {"stock_id": "2330", "event_date": pd.to_datetime("2026-05-01").date(),
         "consecutive_days": 3, "cumulative_net_buy": 500},
    ])
    out = event_post_returns(events, prices, horizons=[5])
    row = out.iloc[0]
    assert pd.isna(row["ret_5d"])
```

- [ ] **Step 2-4: 跑 fail → 寫 impl → 跑 pass**

加進 `research_chip_events.py`:

```python
def event_post_returns(
    events: pd.DataFrame,
    prices: pd.DataFrame,
    horizons: list[int] = [5, 10, 20],
) -> pd.DataFrame:
    """對每個 event 算 horizon 個交易日後的累積報酬 (%)。

    使用 trading day index (依 prices 表內每股的實際 trading days), 不算 calendar days。
    若 horizon 超過該股可用 trading day, 該 horizon ret = NaN。
    """
    prices = prices.copy().sort_values(["stock_id", "date"]).reset_index(drop=True)
    prices["date"] = pd.to_datetime(prices["date"]).dt.date
    # 對每 stock 建 trading-day index
    prices["_td_idx"] = prices.groupby("stock_id").cumcount()
    p_lookup = prices.set_index(["stock_id", "date"])
    p_by_idx = prices.set_index(["stock_id", "_td_idx"])

    out = events.copy()
    for h in horizons:
        col = f"ret_{h}d"
        out[col] = float("nan")
    for i, e in out.iterrows():
        sid = e["stock_id"]
        edate = e["event_date"]
        try:
            base_idx = int(p_lookup.loc[(sid, edate), "_td_idx"])
        except KeyError:
            continue
        try:
            base_close = float(p_lookup.loc[(sid, edate), "close"])
        except KeyError:
            continue
        for h in horizons:
            try:
                future_close = float(p_by_idx.loc[(sid, base_idx + h), "close"])
                out.at[i, f"ret_{h}d"] = (future_close / base_close - 1) * 100
            except KeyError:
                pass
    return out
```

- [ ] **Step 5: commit**

```bash
cd /Users/chihhaolai/Documents/GitHub/AlphaForge
git add backend/scripts/research_chip_events.py backend/tests/test_research_chip_events.py
git commit -m "feat(research): event post-return (trading day horizon)"
```

---

### Task 7: `walk_forward_backtest()` + TAIEX baseline

**Files:**
- Modify: `backend/scripts/research_chip_events.py`
- Modify: `backend/tests/test_research_chip_events.py`

- [ ] **Step 1: 寫 failing tests**

加到 test 檔:

```python
from scripts.research_chip_events import walk_forward_summary


def test_walk_forward_summary_aggregates_by_quarter():
    events_with_ret = pd.DataFrame([
        {"event_date": pd.to_datetime("2026-01-15").date(), "ret_5d": 1.5, "ret_10d": 3.0},
        {"event_date": pd.to_datetime("2026-02-15").date(), "ret_5d": -0.5, "ret_10d": 1.0},
        {"event_date": pd.to_datetime("2026-03-15").date(), "ret_5d": 2.0, "ret_10d": 4.0},
        {"event_date": pd.to_datetime("2026-04-15").date(), "ret_5d": 0.0, "ret_10d": -1.0},
        {"event_date": pd.to_datetime("2026-05-15").date(), "ret_5d": 3.0, "ret_10d": 5.0},
    ])
    out = walk_forward_summary(events_with_ret, horizons=[5, 10])
    # 應該分 2026Q1, 2026Q2 兩 group
    assert set(out["quarter"].tolist()) == {"2026Q1", "2026Q2"}
    q1 = out[out["quarter"] == "2026Q1"].iloc[0]
    assert q1["n"] == 3
    assert q1["wr_5d"] == pytest.approx(66.67, abs=0.5)   # 2/3 positive
    assert q1["avg_5d"] == pytest.approx(1.0, abs=0.01)
```

- [ ] **Step 2-4: 跑 fail → 寫 impl → 跑 pass**

加進 `research_chip_events.py`:

```python
def walk_forward_summary(events_with_ret: pd.DataFrame, horizons: list[int] = [5, 10, 20]) -> pd.DataFrame:
    """按 quarter 切 events, 算各 horizon 的 n / wr / avg。"""
    df = events_with_ret.copy()
    df["event_date"] = pd.to_datetime(df["event_date"])
    df["quarter"] = df["event_date"].dt.to_period("Q").astype(str)
    rows = []
    for q, sub in df.groupby("quarter"):
        row = {"quarter": q, "n": len(sub)}
        for h in horizons:
            col = f"ret_{h}d"
            valid = sub[col].dropna()
            row[f"wr_{h}d"] = (valid > 0).mean() * 100 if len(valid) else float("nan")
            row[f"avg_{h}d"] = valid.mean() if len(valid) else float("nan")
        rows.append(row)
    return pd.DataFrame(rows).sort_values("quarter")
```

- [ ] **Step 5: commit**

```bash
cd /Users/chihhaolai/Documents/GitHub/AlphaForge
git add backend/scripts/research_chip_events.py backend/tests/test_research_chip_events.py
git commit -m "feat(research): walk-forward summary by quarter"
```

---

### Task 8: `main()` — 跑 Phase 2 完整 pipeline

**Files:**
- Modify: `backend/scripts/research_chip_events.py`

- [ ] **Step 1: 寫 main**

加進 `research_chip_events.py`:

```python
from sqlalchemy import create_engine, text


def _load_db_url() -> str:
    env = Path(__file__).resolve().parents[1] / ".env"
    if not env.exists():
        raise RuntimeError(f"backend/.env not found at {env}")
    for line in env.read_text().splitlines():
        line = line.strip()
        if line.startswith("DATABASE_URL="):
            return line.split("=", 1)[1]
    raise RuntimeError("DATABASE_URL not in backend/.env")


def _fetch_chip_data(engine) -> pd.DataFrame:
    sql = text("""
        SELECT stock_id, date, foreign_net_buy, trust_net_buy, dealer_net_buy
        FROM stock_chip_data
        WHERE date >= CURRENT_DATE - INTERVAL '1 year'
    """)
    return pd.read_sql(sql, engine)


def _fetch_prices(engine) -> pd.DataFrame:
    sql = text("""
        SELECT stock_id, date, close
        FROM stock_prices
        WHERE date >= CURRENT_DATE - INTERVAL '1 year'
    """)
    return pd.read_sql(sql, engine)


def _fetch_taiex(engine) -> pd.DataFrame:
    """讀 TAIEX 大盤 close (stock_id='IX0001' 或對應 index 表)。
    若 stock_prices 沒 TAIEX, return 空 df, report 內標 baseline=N/A。
    """
    sql = text("""
        SELECT date, close FROM stock_prices
        WHERE stock_id = 'IX0001' AND date >= CURRENT_DATE - INTERVAL '1 year'
        ORDER BY date
    """)
    try:
        return pd.read_sql(sql, engine)
    except Exception:
        return pd.DataFrame(columns=["date", "close"])


def _render_report(
    summary_foreign: pd.DataFrame,
    summary_trust: pd.DataFrame,
    overall_foreign: dict,
    overall_trust: dict,
    n_events_foreign: int,
    n_events_trust: int,
    taiex_baseline: dict,
) -> str:
    now = datetime.now(TAIPEI_TZ).strftime("%Y-%m-%d %H:%M")
    lines = [
        "###### tags: `日報`,`AlphaForge`,`alpha 研究`,`chip-event-prototype`",
        "",
        "# Phase 2 — 籌碼連續淨買 Event Prototype Report",
        "",
        f"`文件版本: {datetime.now(TAIPEI_TZ).strftime('%Y-%m-%d')}a`",
        "",
        f"產生時間: {now} (Asia/Taipei)",
        "",
        f"## 事件樣本 (近 1 年, 連續淨買 ≥ 3 日)",
        f"- 外資 (foreign): {n_events_foreign} 事件",
        f"- 投信 (trust): {n_events_trust} 事件",
        "",
        "## 整體 (所有事件聚合)",
        "",
        "| 訊號源 | 5d wr | 5d avg | 10d wr | 10d avg | 20d wr | 20d avg |",
        "|---|---|---|---|---|---|---|",
    ]
    for label, ov in [("外資", overall_foreign), ("投信", overall_trust)]:
        lines.append(
            f"| {label} | {ov.get('wr_5d', float('nan')):.1f}% | {ov.get('avg_5d', float('nan')):+.2f}% | "
            f"{ov.get('wr_10d', float('nan')):.1f}% | {ov.get('avg_10d', float('nan')):+.2f}% | "
            f"{ov.get('wr_20d', float('nan')):.1f}% | {ov.get('avg_20d', float('nan')):+.2f}% |"
        )
    lines += ["", "## TAIEX baseline (同期大盤)", ""]
    if taiex_baseline:
        lines.append(
            f"- TAIEX 5d avg: {taiex_baseline.get('5d', float('nan')):+.2f}%, "
            f"10d avg: {taiex_baseline.get('10d', float('nan')):+.2f}%, "
            f"20d avg: {taiex_baseline.get('20d', float('nan')):+.2f}%"
        )
    else:
        lines.append("- (TAIEX 資料缺, baseline=N/A)")
    lines += ["", "## Walk-forward (按 quarter)", "",
              "### 外資", "",
              "| quarter | n | 5d wr | 5d avg | 10d wr | 10d avg | 20d wr | 20d avg |",
              "|---|---|---|---|---|---|---|---|"]
    for _, r in summary_foreign.iterrows():
        lines.append(
            f"| {r['quarter']} | {int(r['n'])} | {r.get('wr_5d', float('nan')):.1f}% | "
            f"{r.get('avg_5d', float('nan')):+.2f}% | {r.get('wr_10d', float('nan')):.1f}% | "
            f"{r.get('avg_10d', float('nan')):+.2f}% | {r.get('wr_20d', float('nan')):.1f}% | "
            f"{r.get('avg_20d', float('nan')):+.2f}% |"
        )
    lines += ["", "### 投信", "",
              "| quarter | n | 5d wr | 5d avg | 10d wr | 10d avg | 20d wr | 20d avg |",
              "|---|---|---|---|---|---|---|---|"]
    for _, r in summary_trust.iterrows():
        lines.append(
            f"| {r['quarter']} | {int(r['n'])} | {r.get('wr_5d', float('nan')):.1f}% | "
            f"{r.get('avg_5d', float('nan')):+.2f}% | {r.get('wr_10d', float('nan')):.1f}% | "
            f"{r.get('avg_10d', float('nan')):+.2f}% | {r.get('wr_20d', float('nan')):.1f}% | "
            f"{r.get('avg_20d', float('nan')):+.2f}% |"
        )
    lines += ["", "## Verdict", "",
              "- Pass 條件: 5d 或 10d wr > 53% AND avg > TAIEX baseline 同期",
              "- 看上述 overall + walk-forward 是否符合, 由 user 看完決定 Phase 3 整不整合", ""]
    return "\n".join(lines)


def _overall_stats(events_with_ret: pd.DataFrame, horizons: list[int]) -> dict:
    out = {}
    for h in horizons:
        col = f"ret_{h}d"
        valid = events_with_ret[col].dropna()
        out[f"wr_{h}d"] = (valid > 0).mean() * 100 if len(valid) else float("nan")
        out[f"avg_{h}d"] = valid.mean() if len(valid) else float("nan")
    return out


def _taiex_baseline(taiex: pd.DataFrame, horizons: list[int]) -> dict:
    """大盤 baseline: 對每個 day 算 day+H close / day close - 1, 取所有 day 平均。
    """
    if taiex.empty:
        return {}
    taiex = taiex.copy().sort_values("date").reset_index(drop=True)
    taiex["date"] = pd.to_datetime(taiex["date"]).dt.date
    closes = taiex["close"].values
    out = {}
    for h in horizons:
        rets = (closes[h:] / closes[:-h] - 1) * 100
        out[f"{h}d"] = float(np.mean(rets)) if len(rets) else float("nan")
    return out


def main() -> int:
    db_url = _load_db_url()
    engine = create_engine(db_url, pool_pre_ping=True)
    print("loading chip data + prices from NAS Postgres ...")
    chip = _fetch_chip_data(engine)
    prices = _fetch_prices(engine)
    taiex = _fetch_taiex(engine)
    print(f"  chip: {len(chip)} rows, prices: {len(prices)} rows, taiex: {len(taiex)} rows")
    if chip.empty or prices.empty:
        print("ERROR: empty input")
        return 1

    horizons = [5, 10, 20]
    # 外資 events
    events_f = find_consecutive_buy_events(chip, factor_col="foreign_net_buy", min_days=3)
    events_f_ret = event_post_returns(events_f, prices, horizons=horizons)
    summary_f = walk_forward_summary(events_f_ret, horizons=horizons)
    overall_f = _overall_stats(events_f_ret, horizons)
    # 投信 events
    events_t = find_consecutive_buy_events(chip, factor_col="trust_net_buy", min_days=3)
    events_t_ret = event_post_returns(events_t, prices, horizons=horizons)
    summary_t = walk_forward_summary(events_t_ret, horizons=horizons)
    overall_t = _overall_stats(events_t_ret, horizons)
    # TAIEX baseline
    base = _taiex_baseline(taiex, horizons)

    report = _render_report(summary_f, summary_t, overall_f, overall_t,
                            len(events_f), len(events_t), base)
    out_dir = Path(__file__).resolve().parents[2] / "docs" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{datetime.now(TAIPEI_TZ).strftime('%Y-%m-%d')}-chip-event-prototype.md"
    out_path.write_text(report, encoding="utf-8")
    print(f"report → {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 跑 script (真戰 NAS)**

```bash
cd /Users/chihhaolai/Documents/GitHub/AlphaForge/backend
./.venv/bin/python -m scripts.research_chip_events
```

預期: stdout 印 `chip: ~XXXk rows, prices: ~XXXk rows, taiex: XX rows`, report → `docs/reports/YYYY-MM-DD-chip-event-prototype.md`, exit 0。

- [ ] **Step 3: 看 report + commit**

```bash
cd /Users/chihhaolai/Documents/GitHub/AlphaForge
cat docs/reports/$(date +%Y-%m-%d)-chip-event-prototype.md | head -60
git add backend/scripts/research_chip_events.py docs/reports/$(date +%Y-%m-%d)-chip-event-prototype.md
git commit -m "feat(research): chip event prototype + first report"
```

- [ ] **Step 4: user verdict**

stop. ask user 看 report, 給 verdict: Pass (5d 或 10d wr > 53% + avg > TAIEX baseline) → Phase 3 整合 plan; Fail → 換 source (融資融券 / 月營收 / 內部人轉讓)。

---

## Self-Review Checklist

- [x] **Spec coverage**: spec §1.1 Phase 1 (ablation) → Task 1-4; spec §1.2 Phase 2 → Task 5-8 (簡化, 無 crawler/migration 因 data 已存在)
- [x] **Placeholder scan**: 無 TBD / TODO; `<JSON_ARRAY_*>` 之類占位都是 prompt template
- [x] **Type consistency**: `per_factor_ic` / `quality_gate_impact` / `universe_slice_alpha` / `find_consecutive_buy_events` / `event_post_returns` / `walk_forward_summary` signatures 跨 task 一致
- [x] **Scope check**: 8 tasks single plan, 適合一 session 跑完

## 風險與緩解

- **NAS Postgres 連線**: backend/.env 已含 DATABASE_URL (5/12 commit `c52843d` 之前就有)
- **stock_features picks join 對不上**: pick_date 跟 feature date 應該都是同一天, 若有時區 / 格式不一致, `_join_picks_features` 內已標準化 `str(date)`
- **大量 chip 資料 (93 萬筆)**: 近 1 年 filter 縮到 ~40 萬, pandas in-memory 處理 OK
- **TAIEX 不在 stock_prices**: `_fetch_taiex` 試 IX0001, 失敗 return 空, report 標 N/A; 不阻擋 Phase 2 完成
- **Phase 2 verdict 失敗**: spec §1.2 已寫「Fail → 換 source」, plan 8 task 完成是 deliverable, 是否進 Phase 3 取決於數字

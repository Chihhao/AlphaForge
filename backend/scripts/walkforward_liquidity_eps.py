"""Walk-Forward 驗證：log_amihud_20d + eps_momentum vs baseline 13 因子.

Compares four configurations across rolling 4-month OOS windows:
    A) baseline — existing 13 training factors
    B) +amihud  — baseline + log_amihud_20d
    C) +eps_mom — baseline + eps_momentum
    D) +both    — baseline + both new factors

Reports per-window OOS IC, top-decile excess return, long-short spread,
and paired t-test across windows (B/C/D vs A).

Usage:
    cd backend
    ./.venv/bin/python scripts/walkforward_liquidity_eps.py
"""
from __future__ import annotations

import logging
import os
import warnings
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.ensemble import HistGradientBoostingClassifier
from sqlalchemy import create_engine, text

warnings.filterwarnings("ignore")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

PG_URL = os.environ.get(
    "PG_URL",
    "postgresql://alphaforge:alphaforge_secret@10.0.4.3:5433/alphaforge",
)
engine = create_engine(PG_URL)

# ── 研究參數 ──
STUDY_START = "2023-03-01"
STUDY_END = "2026-04-08"
MIN_DAILY_VOLUME = 500  # 張，活躍股過濾
HORIZON = 20  # 交易日
LABEL_THRESHOLD = 0.03  # 20d 超過 +3% 視為正樣本
TRAIN_MIN_MONTHS = 9
TEST_MONTHS = 4
GAP_MONTHS = 1  # train end 到 test start 之間 gap（避免 label 洩漏）
TOP_DECILE = 0.10

# 台灣季報公告截止日（無前視偏差）
EPS_AVAIL = {1: (0, 5, 15), 2: (0, 8, 14), 3: (0, 11, 14), 4: (1, 3, 31)}

# Baseline 13 訓練因子
BASELINE_FACTORS: tuple[str, ...] = (
    "roe",
    "yield_rate",
    "pb_ratio",
    "revenue_yoy",
    "rev_surprise",
    "rev_accel",
    "foreign_hold_chg_5d",
    "dealer_buy_20d",
    "vol_ratio",
    "ivol_20d",
    "neg_trust_net_buy",
    "short_chg_5d",
    "neg_divergence_avg",
)

# stock_features 原始欄位（neg_* 因子的原欄位）
FEATURE_COLS_RAW: tuple[str, ...] = (
    "roe",
    "yield_rate",
    "pb_ratio",
    "revenue_yoy",
    "rev_surprise",
    "rev_accel",
    "foreign_hold_chg_5d",
    "dealer_buy_20d",
    "vol_ratio",
    "ivol_20d",
    "trust_net_buy",
    "short_chg_5d",
    "divergence_avg",
)


@dataclass(frozen=True)
class Window:
    """Walk-forward 視窗定義."""

    wid: int
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp


@dataclass(frozen=True)
class WindowResult:
    """單一視窗 × 單一配置的 OOS 結果."""

    config: str
    wid: int
    ic: float
    ls_spread: float
    top_excess: float
    n_test: int


# ════════════════════════════════════════
# 1. 資料載入
# ════════════════════════════════════════
def load_features() -> pd.DataFrame:
    """Load baseline features from stock_features."""
    log.info("Loading stock_features...")
    cols = ["stock_id", "date", "close", "volume"] + list(FEATURE_COLS_RAW)
    col_str = ", ".join(cols)
    query = text(
        f"SELECT {col_str} FROM stock_features "
        f"WHERE date >= :start AND date <= :end AND close > 0"
    )
    df = pd.read_sql(query, engine, params={"start": STUDY_START, "end": STUDY_END})
    df["date"] = pd.to_datetime(df["date"])
    # 衍生 neg_* 因子
    df["neg_trust_net_buy"] = -df["trust_net_buy"]
    df["neg_divergence_avg"] = -df["divergence_avg"]
    log.info("  features: %d rows", len(df))
    return df


def load_prices() -> pd.DataFrame:
    """Load stock_prices for amihud computation."""
    log.info("Loading stock_prices...")
    query = text(
        "SELECT stock_id, date, close, volume FROM stock_prices "
        "WHERE date >= :start AND date <= :end AND close > 0"
    )
    df = pd.read_sql(query, engine, params={"start": STUDY_START, "end": STUDY_END})
    df["date"] = pd.to_datetime(df["date"])
    log.info("  prices: %d rows", len(df))
    return df


def load_eps() -> pd.DataFrame:
    """Load quarterly EPS with publication availability dates."""
    log.info("Loading stock_eps_history...")
    query = text("SELECT stock_id, year, quarter, eps FROM stock_eps_history")
    df = pd.read_sql(query, engine)
    # 計算每筆 EPS 對市場可用的日期
    year_offsets, months, days = zip(*(EPS_AVAIL[q] for q in df["quarter"]))
    df["avail_date"] = pd.to_datetime(
        pd.DataFrame(
            {
                "year": df["year"].to_numpy() + np.array(year_offsets),
                "month": np.array(months),
                "day": np.array(days),
            }
        )
    )
    log.info("  eps: %d rows", len(df))
    return df


# ════════════════════════════════════════
# 2. 新因子建構
# ════════════════════════════════════════
def compute_amihud(prices: pd.DataFrame) -> pd.DataFrame:
    """Compute log_amihud_20d factor from prices."""
    log.info("Computing log_amihud_20d...")
    df = prices.sort_values(["stock_id", "date"]).copy()
    df["ret"] = df.groupby("stock_id")["close"].pct_change()
    df["dollar_vol"] = df["close"] * df["volume"]
    df["abs_ret_over_dvol"] = (
        df["ret"].abs() / df["dollar_vol"].replace(0, np.nan)
    )
    df["amihud_20d"] = df.groupby("stock_id")["abs_ret_over_dvol"].transform(
        lambda x: x.rolling(20, min_periods=15).mean()
    )
    df["log_amihud_20d"] = np.log1p(df["amihud_20d"] * 1e8)
    return df[["stock_id", "date", "log_amihud_20d"]]


def compute_eps_momentum(prices: pd.DataFrame, eps: pd.DataFrame) -> pd.DataFrame:
    """Compute eps_momentum factor with look-ahead protection."""
    log.info("Computing eps_momentum (look-ahead protected)...")
    eps_sorted = eps.sort_values(["stock_id", "year", "quarter"]).copy()
    eps_sorted["trailing_4q"] = eps_sorted.groupby("stock_id")["eps"].transform(
        lambda x: x.rolling(4, min_periods=4).sum()
    )
    eps_sorted["prev_trailing_4q"] = eps_sorted.groupby("stock_id")[
        "trailing_4q"
    ].shift(1)
    eps_sorted["eps_momentum"] = (
        eps_sorted["trailing_4q"] - eps_sorted["prev_trailing_4q"]
    ) / eps_sorted["prev_trailing_4q"].abs().replace(0, np.nan)

    eps_merge = eps_sorted[["stock_id", "avail_date", "eps_momentum"]].dropna(
        subset=["avail_date", "eps_momentum"]
    )
    eps_merge = eps_merge.rename(columns={"avail_date": "date"}).sort_values(
        ["stock_id", "date"]
    )

    # 逐股 merge_asof 避免全局排序限制
    px = prices[["stock_id", "date"]].copy()
    eps_grouped = eps_merge.groupby("stock_id")
    parts = []
    for sid, px_g in px.groupby("stock_id"):
        px_g = px_g.sort_values("date").reset_index(drop=True)
        if sid in eps_grouped.groups:
            # drop stock_id from right to avoid _x/_y suffixes after merge_asof
            e_g = (
                eps_grouped.get_group(sid)
                .drop(columns=["stock_id"])
                .sort_values("date")
                .reset_index(drop=True)
            )
            merged = pd.merge_asof(
                px_g, e_g, on="date", direction="backward"
            )
        else:
            merged = px_g.copy()
            merged["eps_momentum"] = np.nan
        parts.append(merged)
    result = pd.concat(parts, ignore_index=True)
    return result[["stock_id", "date", "eps_momentum"]]


# ════════════════════════════════════════
# 3. 標籤與 Walk-Forward 視窗
# ════════════════════════════════════════
def add_labels(df: pd.DataFrame) -> pd.DataFrame:
    """Add forward return and classification label (20d horizon, T+1 entry)."""
    df = df.sort_values(["stock_id", "date"]).copy()
    # T+1 進場，T+1+HORIZON 出場
    df["entry_close"] = df.groupby("stock_id")["close"].shift(-1)
    df["exit_close"] = df.groupby("stock_id")["close"].shift(-(1 + HORIZON))
    df["fwd_return"] = (df["exit_close"] - df["entry_close"]) / df[
        "entry_close"
    ]
    df["label"] = (df["fwd_return"] > LABEL_THRESHOLD).astype(float)
    df.loc[df["fwd_return"].isna(), "label"] = np.nan
    return df


def generate_windows(df: pd.DataFrame) -> list[Window]:
    """Generate rolling walk-forward windows."""
    mn, mx = df["date"].min(), df["date"].max()
    test_start = mn + pd.DateOffset(months=TRAIN_MIN_MONTHS + GAP_MONTHS)
    windows: list[Window] = []
    wid = 1
    while test_start + pd.DateOffset(months=2) <= mx:
        test_end = min(test_start + pd.DateOffset(months=TEST_MONTHS), mx)
        train_end = test_start - pd.DateOffset(months=GAP_MONTHS)
        windows.append(
            Window(
                wid=wid,
                train_end=pd.Timestamp(train_end),
                test_start=pd.Timestamp(test_start),
                test_end=pd.Timestamp(test_end),
            )
        )
        test_start += pd.DateOffset(months=TEST_MONTHS)
        wid += 1
    return windows


# ════════════════════════════════════════
# 4. Walk-Forward 單窗口訓練與評估
# ════════════════════════════════════════
def add_cross_sectional_ranks(
    df: pd.DataFrame, factors: tuple[str, ...]
) -> pd.DataFrame:
    """Add per-day cross-sectional rank columns for each factor."""
    out = df.copy()
    for f in factors:
        if f in out.columns:
            out[f"{f}_rank"] = (
                out.groupby("date")[f]
                .rank(pct=True, na_option="keep")
                .astype(float)
            )
    return out


def train_and_predict(
    train: pd.DataFrame,
    test: pd.DataFrame,
    factors: tuple[str, ...],
) -> Optional[np.ndarray]:
    """Train HistGradientBoostingClassifier and return test predictions."""
    rank_cols = [f"{f}_rank" for f in factors]
    available = [c for c in rank_cols if c in train.columns and c in test.columns]
    if len(available) < 5:
        return None

    X_train = train[available].to_numpy(dtype=float)
    y_train = train["label"].to_numpy(dtype=float)
    mask = ~np.isnan(y_train)
    if mask.sum() < 2000:
        return None

    clf = HistGradientBoostingClassifier(
        max_iter=200,
        max_depth=4,
        max_leaf_nodes=15,
        learning_rate=0.03,
        min_samples_leaf=100,
        l2_regularization=1.0,
        random_state=42,
        class_weight="balanced",
    )
    clf.fit(X_train[mask], y_train[mask])
    return clf.predict_proba(test[available].to_numpy(dtype=float))[:, 1]


def evaluate_window(
    df_all: pd.DataFrame,
    window: Window,
    config_name: str,
    factors: tuple[str, ...],
) -> Optional[WindowResult]:
    """Train on train window, evaluate OOS on test window."""
    df = add_cross_sectional_ranks(df_all, factors)

    train = df[df["date"] <= window.train_end].dropna(subset=["label"])
    test = df[
        (df["date"] >= window.test_start) & (df["date"] <= window.test_end)
    ].dropna(subset=["label", "fwd_return"])

    if len(train) < 2000 or len(test) < 300:
        return None

    prob = train_and_predict(train, test, factors)
    if prob is None:
        return None

    test = test.copy()
    test["prob"] = prob

    # OOS IC (Spearman rank correlation of prob vs fwd_return, daily mean)
    daily_ic = (
        test.groupby("date")
        .apply(
            lambda g: g["prob"].corr(g["fwd_return"], method="spearman")
            if len(g) >= 30
            else np.nan,
            include_groups=False,
        )
        .dropna()
    )
    ic = float(daily_ic.mean()) if len(daily_ic) else np.nan

    # Top-decile excess vs market
    cut = test["prob"].quantile(1 - TOP_DECILE)
    top = test[test["prob"] >= cut]
    top_mean = top["fwd_return"].mean()
    mkt_mean = test["fwd_return"].mean()
    top_excess = float(top_mean - mkt_mean) if pd.notna(top_mean) else np.nan

    # Long-Short (Q5 - Q1)
    test["q"] = test.groupby("date")["prob"].transform(
        lambda x: pd.qcut(x, 5, labels=False, duplicates="drop")
        if x.dropna().shape[0] >= 50
        else np.nan
    )
    q_ret = test.groupby("q")["fwd_return"].mean()
    ls_spread = (
        float(q_ret.get(4, np.nan) - q_ret.get(0, np.nan))
        if 4 in q_ret.index and 0 in q_ret.index
        else np.nan
    )

    return WindowResult(
        config=config_name,
        wid=window.wid,
        ic=ic,
        ls_spread=ls_spread,
        top_excess=top_excess,
        n_test=len(test),
    )


# ════════════════════════════════════════
# 5. Orchestration
# ════════════════════════════════════════
def merge_all_factors(
    features: pd.DataFrame,
    amihud: pd.DataFrame,
    eps_mom: pd.DataFrame,
) -> pd.DataFrame:
    """Merge baseline features with new factors and add labels."""
    log.info("Merging all factor sources...")
    df = features.merge(amihud, on=["stock_id", "date"], how="left")
    df = df.merge(eps_mom, on=["stock_id", "date"], how="left")
    # 活躍股過濾
    before = len(df)
    df = df[df["volume"] >= MIN_DAILY_VOLUME * 1000]
    log.info("  active filter: %d -> %d", before, len(df))
    df = add_labels(df)
    return df


def run_all_configs(
    df: pd.DataFrame,
    windows: list[Window],
) -> dict[str, list[WindowResult]]:
    """Run walk-forward for all 4 configurations."""
    configs: dict[str, tuple[str, ...]] = {
        "A_baseline": BASELINE_FACTORS,
        "B_+amihud": BASELINE_FACTORS + ("log_amihud_20d",),
        "C_+eps_mom": BASELINE_FACTORS + ("eps_momentum",),
        "D_+both": BASELINE_FACTORS + ("log_amihud_20d", "eps_momentum"),
    }

    results: dict[str, list[WindowResult]] = {k: [] for k in configs}
    for w in windows:
        log.info(
            "Window W%d: train<=%s, test=%s~%s",
            w.wid,
            w.train_end.date(),
            w.test_start.date(),
            w.test_end.date(),
        )
        for name, factors in configs.items():
            r = evaluate_window(df, w, name, factors)
            if r is None:
                log.warning("  %s: skipped", name)
                continue
            results[name].append(r)
            log.info(
                "  %s: IC=%+.4f L-S=%+.3f%% TopExc=%+.3f%% n=%d",
                name,
                r.ic,
                r.ls_spread * 100 if pd.notna(r.ls_spread) else np.nan,
                r.top_excess * 100 if pd.notna(r.top_excess) else np.nan,
                r.n_test,
            )
    return results


def summarize(results: dict[str, list[WindowResult]]) -> None:
    """Print summary table and paired t-tests."""
    print("\n" + "=" * 100)
    print("Walk-Forward Summary")
    print("=" * 100)

    rows: list[dict[str, object]] = []
    for name, rs in results.items():
        if not rs:
            continue
        ics = np.array([r.ic for r in rs])
        lss = np.array([r.ls_spread for r in rs])
        tops = np.array([r.top_excess for r in rs])
        rows.append(
            {
                "config": name,
                "n_win": len(rs),
                "ic_mean": float(np.nanmean(ics)),
                "ic_pos_pct": float(np.nanmean(ics > 0)),
                "ls_mean": float(np.nanmean(lss)),
                "top_excess_mean": float(np.nanmean(tops)),
            }
        )

    print(
        f"{'Config':<14} {'N':>3} {'IC':>8} {'IC+%':>6} "
        f"{'L-S':>8} {'TopExc':>8}"
    )
    print("-" * 60)
    for row in rows:
        print(
            f"{row['config']:<14} "
            f"{row['n_win']:>3} "
            f"{row['ic_mean']:+.4f}  "
            f"{row['ic_pos_pct']:.0%}   "
            f"{row['ls_mean']*100:+.2f}%   "
            f"{row['top_excess_mean']*100:+.2f}%"
        )

    # Per-window IC table
    print("\nPer-Window IC:")
    baseline = results.get("A_baseline", [])
    max_wid = max((r.wid for r in baseline), default=0)
    header = f"{'W':>3}"
    for name in results:
        short = name.split("_", 1)[1]
        header += f"  {short:>12}"
    print(header)
    for wid in range(1, max_wid + 1):
        line = f"W{wid:>2}"
        for name in results:
            match = [r for r in results[name] if r.wid == wid]
            if match:
                line += f"  {match[0].ic:>+12.4f}"
            else:
                line += f"  {'N/A':>12}"
        print(line)

    # Paired t-test: configs vs baseline
    print("\nPaired t-test vs A_baseline (IC):")
    base_ic = {r.wid: r.ic for r in baseline}
    for name in ["B_+amihud", "C_+eps_mom", "D_+both"]:
        rs = results.get(name, [])
        if not rs:
            continue
        pairs = [
            (r.ic, base_ic[r.wid])
            for r in rs
            if r.wid in base_ic and pd.notna(r.ic) and pd.notna(base_ic[r.wid])
        ]
        if len(pairs) < 3:
            print(f"  {name}: insufficient paired data")
            continue
        a = np.array([p[0] for p in pairs])
        b = np.array([p[1] for p in pairs])
        diff = a - b
        t_stat, p_val = stats.ttest_rel(a, b)
        print(
            f"  {name:<12} vs baseline: ΔIC={diff.mean():+.4f}  "
            f"t={t_stat:+.3f}  p={p_val:.4f}  "
            f"win_rate={(diff > 0).mean():.0%}"
        )

    # Top-excess paired t-test
    print("\nPaired t-test vs A_baseline (Top-decile excess return):")
    base_top = {r.wid: r.top_excess for r in baseline}
    for name in ["B_+amihud", "C_+eps_mom", "D_+both"]:
        rs = results.get(name, [])
        if not rs:
            continue
        pairs = [
            (r.top_excess, base_top[r.wid])
            for r in rs
            if r.wid in base_top
            and pd.notna(r.top_excess)
            and pd.notna(base_top[r.wid])
        ]
        if len(pairs) < 3:
            continue
        a = np.array([p[0] for p in pairs])
        b = np.array([p[1] for p in pairs])
        diff = a - b
        t_stat, p_val = stats.ttest_rel(a, b)
        print(
            f"  {name:<12} vs baseline: Δ={diff.mean()*100:+.3f}%  "
            f"t={t_stat:+.3f}  p={p_val:.4f}  "
            f"win_rate={(diff > 0).mean():.0%}"
        )


def main() -> None:
    features = load_features()
    prices = load_prices()
    eps = load_eps()

    amihud = compute_amihud(prices)
    eps_mom = compute_eps_momentum(prices, eps)

    df = merge_all_factors(features, amihud, eps_mom)
    log.info("Final dataset: %d rows, %d stocks", len(df), df["stock_id"].nunique())

    # 檢查新因子覆蓋率
    for col in ("log_amihud_20d", "eps_momentum"):
        cov = df[col].notna().mean()
        log.info("  %s coverage: %.1f%%", col, cov * 100)

    windows = generate_windows(df)
    log.info("Generated %d windows", len(windows))
    for w in windows:
        log.info(
            "  W%d: train<=%s test=%s~%s",
            w.wid,
            w.train_end.date(),
            w.test_start.date(),
            w.test_end.date(),
        )

    results = run_all_configs(df, windows)
    summarize(results)


if __name__ == "__main__":
    main()

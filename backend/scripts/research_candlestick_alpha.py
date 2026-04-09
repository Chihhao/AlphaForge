"""
K 線型態因子 Alpha 研究

三層候選因子 × 三維度(5d/10d/20d)驗證：
  Layer 1: K 棒解剖因子（連續型，每日有值）
  Layer 2: 滾動型態得分（半連續型，N 日累積）
  Layer 3: ECF 複合評分（綜合型）

驗證方法：
  - 每日截面 Spearman Rank IC → t-test
  - Bonferroni 校正（16 因子 × 3 維度 = 48 次比較）
  - Walk-Forward Long-Short（Top10% vs Bottom10%）
"""
from __future__ import annotations

import os
import warnings
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
from scipy import stats
from sqlalchemy import create_engine, text

warnings.filterwarnings("ignore")

PG_URL = os.getenv(
    "PG_URL",
    "postgresql://alphaforge:alphaforge_secret@10.0.4.3:5433/alphaforge",
)
engine = create_engine(PG_URL)

# ─── 常數 ─────────────────────────────────────────────────────────
GAP = 1
HORIZONS = [5, 10, 20]
COST = 0.006  # 來回交易成本
N_FACTORS = 16
N_TESTS = N_FACTORS * len(HORIZONS)  # 48
BONFERRONI_P = 0.05 / N_TESTS  # ≈ 0.00104

# ECF v60 型態權重
PATTERN_WEIGHTS: Dict[str, int] = {
    # 看漲
    "three_white_soldiers": 25,
    "morning_star": 20,
    "three_inside_up": 20,
    "bullish_engulfing": 18,
    "piercing_line": 15,
    "hammer": 12,
    "inverted_hammer": 10,
    "dragonfly_doji": 8,
    # 看跌
    "three_black_crows": -25,
    "evening_star": -20,
    "three_inside_down": -20,
    "bearish_engulfing": -18,
    "dark_cloud_cover": -15,
    "shooting_star": -15,
    "hanging_man": -12,
    "gravestone_doji": -10,
}

BULLISH_PATTERNS = [k for k, v in PATTERN_WEIGHTS.items() if v > 0]
BEARISH_PATTERNS = [k for k, v in PATTERN_WEIGHTS.items() if v < 0]


# ═══════════════════════════════════════════════════════════════════
# Phase 1: 資料載入
# ═══════════════════════════════════════════════════════════════════
def load_data() -> pd.DataFrame:
    """從 stock_prices 載入 OHLCV，計算三維度 forward return"""
    sql = text("""
        SELECT stock_id, date, open, high, low, close, volume
        FROM stock_prices
        WHERE date >= '2023-01-01'
          AND close > 0
        ORDER BY stock_id, date
    """)
    df = pd.read_sql(sql, engine)
    df["date"] = pd.to_datetime(df["date"])

    # 流動性過濾：日均成交量 >= 500 張 (500,000 股)
    df["vol_ma20"] = df.groupby("stock_id")["volume"].transform(
        lambda x: x.rolling(20, min_periods=5).mean()
    )
    df = df[df["vol_ma20"] >= 500_000].copy()

    # 只保留 4 碼股票代號（排除 ETF、權證等）
    df = df[df["stock_id"].str.match(r"^[1-9]\d{3}$")].copy()

    # 量比（Layer 3 的 candle_score_vol 需要）
    df["vol_ratio"] = df["volume"] / df["vol_ma20"].replace(0, np.nan)

    # 三維度 forward return
    for h in HORIZONS:
        entry = df.groupby("stock_id")["close"].shift(-GAP)
        exit_ = df.groupby("stock_id")["close"].shift(-(GAP + h))
        df[f"fwd_ret_{h}d"] = (exit_ - entry) / entry

    print(f"[Data] {len(df):,} 筆，"
          f"{df['date'].min().date()} ~ {df['date'].max().date()}，"
          f"{df['stock_id'].nunique()} 檔股票")
    return df


# ═══════════════════════════════════════════════════════════════════
# Phase 2: Layer 1 — K 棒解剖因子
# ═══════════════════════════════════════════════════════════════════
def compute_anatomy_factors(df: pd.DataFrame) -> pd.DataFrame:
    """計算 7 個連續型 K 棒解剖因子"""
    range_ = df["high"] - df["low"]
    range_safe = range_.replace(0, np.nan)

    body = (df["close"] - df["open"]).abs()
    upper_shadow = df["high"] - df[["open", "close"]].max(axis=1)
    lower_shadow = df[["open", "close"]].min(axis=1) - df["low"]

    # 基礎 4 因子
    df["body_pct"] = (body / range_safe).fillna(1.0)
    df["upper_shadow_pct"] = (upper_shadow / range_safe).fillna(0.0)
    df["lower_shadow_pct"] = (lower_shadow / range_safe).fillna(0.0)
    df["candle_direction"] = ((df["close"] - df["open"]) / range_safe).fillna(0.0)

    # 5 日均值版本
    grp = df.groupby("stock_id")
    df["body_pct_5d"] = grp["body_pct"].transform(
        lambda x: x.rolling(5, min_periods=3).mean()
    )
    df["upper_shadow_5d"] = grp["upper_shadow_pct"].transform(
        lambda x: x.rolling(5, min_periods=3).mean()
    )
    df["lower_shadow_5d"] = grp["lower_shadow_pct"].transform(
        lambda x: x.rolling(5, min_periods=3).mean()
    )

    print(f"[Layer 1] 7 個解剖因子計算完成")
    return df


# ═══════════════════════════════════════════════════════════════════
# Phase 3: 16 種 K 線型態向量化偵測
# ═══════════════════════════════════════════════════════════════════
def detect_patterns(df: pd.DataFrame) -> pd.DataFrame:
    """向量化偵測 16 種 K 線型態（ECF v60 邏輯）"""
    grp = df.groupby("stock_id")

    # 預計算 shift 資料
    prev1_open = grp["open"].shift(1)
    prev1_close = grp["close"].shift(1)
    prev1_high = grp["high"].shift(1)
    prev1_low = grp["low"].shift(1)

    prev2_open = grp["open"].shift(2)
    prev2_close = grp["close"].shift(2)
    prev2_high = grp["high"].shift(2)
    prev2_low = grp["low"].shift(2)

    # 基礎屬性
    body = (df["close"] - df["open"]).abs()
    range_ = df["high"] - df["low"]
    range_safe = range_.replace(0, np.nan)
    upper_shadow = df["high"] - df[["open", "close"]].max(axis=1)
    lower_shadow = df[["open", "close"]].min(axis=1) - df["low"]

    prev1_body = (prev1_close - prev1_open).abs()
    prev1_range = prev1_high - prev1_low
    prev2_body = (prev2_close - prev2_open).abs()
    prev2_range = prev2_high - prev2_low

    is_red = df["close"] > df["open"]     # 陽線
    is_green = df["close"] < df["open"]   # 陰線
    prev1_red = prev1_close > prev1_open
    prev1_green = prev1_close < prev1_open
    prev2_red = prev2_close > prev2_open
    prev2_green = prev2_close < prev2_open

    body_ratio = body / range_safe

    # ─── 單根 K 線型態 ────────────────────────────────────────────

    # 錘子線 (Hammer): 小實體在上，長下影線，前一日陰線
    df["hammer"] = (
        (body_ratio < 0.35)
        & (lower_shadow >= body * 2)
        & (upper_shadow < body * 0.5)
        & prev1_green
    ).astype(np.int8)

    # 倒錘子 (Inverted Hammer): 小實體在下，長上影線，前一日陰線
    df["inverted_hammer"] = (
        (body_ratio < 0.35)
        & (upper_shadow >= body * 2)
        & (lower_shadow < body * 0.5)
        & prev1_green
    ).astype(np.int8)

    # 上吊線 (Hanging Man): 同錘子形狀，但前一日陽線（上漲趨勢）
    df["hanging_man"] = (
        (body_ratio < 0.35)
        & (lower_shadow >= body * 2)
        & (upper_shadow < body * 0.5)
        & prev1_red
    ).astype(np.int8)

    # 射擊之星 (Shooting Star): 同倒錘子形狀，但前一日陽線
    df["shooting_star"] = (
        (body_ratio < 0.35)
        & (upper_shadow >= body * 2)
        & (lower_shadow < body * 0.5)
        & prev1_red
    ).astype(np.int8)

    # 蜻蜓十字 (Dragonfly Doji): 極小實體，長下影線
    upper_ratio = upper_shadow / range_safe
    lower_ratio = lower_shadow / range_safe
    df["dragonfly_doji"] = (
        (body_ratio < 0.1)
        & (lower_ratio > 0.6)
        & (upper_ratio < 0.1)
    ).astype(np.int8)

    # 墓碑十字 (Gravestone Doji): 極小實體，長上影線
    df["gravestone_doji"] = (
        (body_ratio < 0.1)
        & (upper_ratio > 0.6)
        & (lower_ratio < 0.1)
    ).astype(np.int8)

    # ─── 二根 K 線型態 ────────────────────────────────────────────

    # 看漲吞噬 (Bullish Engulfing)
    df["bullish_engulfing"] = (
        prev1_green
        & is_red
        & (df["open"] <= prev1_close)
        & (df["close"] >= prev1_open)
        & (body > prev1_body)
    ).astype(np.int8)

    # 看跌吞噬 (Bearish Engulfing)
    df["bearish_engulfing"] = (
        prev1_red
        & is_green
        & (df["open"] >= prev1_close)
        & (df["close"] <= prev1_open)
        & (body > prev1_body)
    ).astype(np.int8)

    # 貫穿線 (Piercing Line)
    mid_prev1 = (prev1_open + prev1_close) / 2
    df["piercing_line"] = (
        prev1_green
        & is_red
        & (df["open"] < prev1_close)
        & (df["close"] > mid_prev1)
        & (df["close"] < prev1_open)
    ).astype(np.int8)

    # 烏雲蓋頂 (Dark Cloud Cover)
    df["dark_cloud_cover"] = (
        prev1_red
        & is_green
        & (df["open"] > prev1_close)
        & (df["close"] < mid_prev1)
        & (df["close"] > prev1_open)
    ).astype(np.int8)

    # ─── 三根 K 線型態 ────────────────────────────────────────────

    # 晨星 (Morning Star)
    prev2_big_down = prev2_green & (prev2_body > prev2_range.replace(0, np.nan) * 0.5)
    prev1_small = prev1_body < prev2_body * 0.3
    curr_big_up = is_red & (body > prev2_body * 0.5)
    penetrates_up = df["close"] > (prev2_open + prev2_close) / 2
    df["morning_star"] = (
        prev2_big_down & prev1_small & curr_big_up & penetrates_up
    ).astype(np.int8)

    # 夜星 (Evening Star)
    prev2_big_up = prev2_red & (prev2_body > prev2_range.replace(0, np.nan) * 0.5)
    curr_big_down = is_green & (body > prev2_body * 0.5)
    penetrates_down = df["close"] < (prev2_open + prev2_close) / 2
    df["evening_star"] = (
        prev2_big_up & prev1_small & curr_big_down & penetrates_down
    ).astype(np.int8)

    # 紅三兵 (Three White Soldiers)
    rising = (prev1_close > prev2_close) & (df["close"] > prev1_close)
    open_in_body1 = (prev1_open >= prev2_open) & (prev1_open <= prev2_close)
    open_in_body2 = (df["open"] >= prev1_open) & (df["open"] <= prev1_close)
    df["three_white_soldiers"] = (
        prev2_red & prev1_red & is_red & rising & open_in_body1 & open_in_body2
    ).astype(np.int8)

    # 三隻烏鴉 (Three Black Crows)
    falling = (prev1_close < prev2_close) & (df["close"] < prev1_close)
    open_in_body1_bear = (prev1_open <= prev2_open) & (prev1_open >= prev2_close)
    open_in_body2_bear = (df["open"] <= prev1_open) & (df["open"] >= prev1_close)
    df["three_black_crows"] = (
        prev2_green & prev1_green & is_green
        & falling & open_in_body1_bear & open_in_body2_bear
    ).astype(np.int8)

    # 三內升 (Three Inside Up)
    first_big_down = prev2_green & (prev2_body > prev2_range.replace(0, np.nan) * 0.5)
    second_inside_up = (
        prev1_red
        & (prev1_open > prev2_close)
        & (prev1_close < prev2_open)
    )
    third_up = is_red & (df["close"] > prev2_open)
    df["three_inside_up"] = (
        first_big_down & second_inside_up & third_up
    ).astype(np.int8)

    # 三內降 (Three Inside Down)
    first_big_up = prev2_red & (prev2_body > prev2_range.replace(0, np.nan) * 0.5)
    second_inside_down = (
        prev1_green
        & (prev1_open < prev2_close)
        & (prev1_close > prev2_open)
    )
    third_down = is_green & (df["close"] < prev2_open)
    df["three_inside_down"] = (
        first_big_up & second_inside_down & third_down
    ).astype(np.int8)

    # 統計
    all_patterns = list(PATTERN_WEIGHTS.keys())
    total_hits = sum(df[p].sum() for p in all_patterns)
    total_rows = len(df)
    print(f"[Layer 型態] 16 種型態偵測完成，"
          f"總命中 {total_hits:,} 次 / {total_rows:,} 筆 "
          f"({total_hits / total_rows * 100:.2f}%)")
    for p in all_patterns:
        cnt = df[p].sum()
        if cnt > 0:
            print(f"  {p:30s} {cnt:6,} ({cnt / total_rows * 100:.3f}%)")
    return df


# ═══════════════════════════════════════════════════════════════════
# Phase 4: Layer 2 & 3
# ═══════════════════════════════════════════════════════════════════
def compute_rolling_scores(df: pd.DataFrame) -> pd.DataFrame:
    """計算 Layer 2 滾動型態得分 + Layer 3 複合評分"""
    grp = df.groupby("stock_id")

    # 看漲/看跌總計
    df["_bull_hit"] = sum(df[p] for p in BULLISH_PATTERNS)
    df["_bear_hit"] = sum(df[p] for p in BEARISH_PATTERNS)

    # ECF 加權當日分數
    df["_weighted_hit"] = sum(
        df[p] * PATTERN_WEIGHTS[p] for p in PATTERN_WEIGHTS
    )

    # Layer 2: 滾動計數/加權
    for window in [5, 10]:
        suffix = f"{window}d"
        df[f"bullish_pattern_{suffix}"] = grp["_bull_hit"].transform(
            lambda x, w=window: x.rolling(w, min_periods=1).sum()
        )
        neg_bear = -df["_bear_hit"]  # 取負值讓看跌也為正
        df[f"bearish_pattern_{suffix}"] = df.groupby("stock_id")[
            "_bear_hit"
        ].transform(lambda x, w=window: x.rolling(w, min_periods=1).sum())
        # bearish 取負（出現越多看跌 → 因子值越負）
        df[f"bearish_pattern_{suffix}"] = -df[f"bearish_pattern_{suffix}"]

        df[f"net_pattern_{suffix}"] = (
            df[f"bullish_pattern_{suffix}"] + df[f"bearish_pattern_{suffix}"]
        )
        df[f"weighted_pattern_{suffix}"] = grp["_weighted_hit"].transform(
            lambda x, w=window: x.rolling(w, min_periods=1).sum()
        )

    # 去掉 bullish_pattern_10d（留 5d 和 10d net/weighted，減少冗餘）
    # 保留全部 7 個因子如計畫

    # Layer 3: 半衰期衰減複合評分
    # 近 10 日指數衰減加權，半衰期 3 天 → λ = ln2/3 ≈ 0.231
    half_life = 3
    decay = np.exp(-np.log(2) / half_life * np.arange(10))  # [1.0, 0.79, 0.63, ...]
    decay = decay / decay.sum()  # 正規化

    def _ewm_score(x: pd.Series) -> pd.Series:
        """以半衰期 3 天衰減的加權滾動分數"""
        return x.rolling(10, min_periods=1).apply(
            lambda w: np.dot(w, decay[-len(w):] / decay[-len(w):].sum()),
            raw=True,
        )

    df["candle_score"] = grp["_weighted_hit"].transform(_ewm_score)
    # clip 到 -100 ~ +100
    df["candle_score"] = df["candle_score"].clip(-100, 100)

    # 量能放大版
    df["candle_score_vol"] = df["candle_score"] * df["vol_ratio"].clip(upper=3).fillna(1)

    # 清理暫存列
    df.drop(columns=["_bull_hit", "_bear_hit", "_weighted_hit"], inplace=True)

    print(f"[Layer 2+3] 9 個滾動/複合因子計算完成")
    return df


# ═══════════════════════════════════════════════════════════════════
# Phase 5: 單因子 IC 篩選
# ═══════════════════════════════════════════════════════════════════
CANDIDATE_FACTORS: List[str] = [
    # Layer 1
    "body_pct", "upper_shadow_pct", "lower_shadow_pct", "candle_direction",
    "body_pct_5d", "upper_shadow_5d", "lower_shadow_5d",
    # Layer 2
    "bullish_pattern_5d", "bearish_pattern_5d", "net_pattern_5d",
    "bullish_pattern_10d", "net_pattern_10d",
    "weighted_pattern_5d", "weighted_pattern_10d",
    # Layer 3
    "candle_score", "candle_score_vol",
]


def single_factor_ic(
    df: pd.DataFrame,
) -> pd.DataFrame:
    """計算 16 因子 × 3 維度的單因子 IC"""
    rows = []
    dates = sorted(df["date"].unique())

    for horizon in HORIZONS:
        fwd_col = f"fwd_ret_{horizon}d"
        for factor in CANDIDATE_FACTORS:
            daily_ics: List[float] = []

            for d in dates:
                day = df.loc[df["date"] == d, [factor, fwd_col]].dropna()
                if len(day) < 30:
                    continue
                # 檢查因子變異性
                if day[factor].nunique() < 3:
                    continue
                ic, _ = stats.spearmanr(day[factor], day[fwd_col])
                if not np.isnan(ic):
                    daily_ics.append(ic)

            if len(daily_ics) < 20:
                rows.append({
                    "horizon": f"{horizon}d",
                    "factor": factor,
                    "ic_mean": np.nan,
                    "ic_std": np.nan,
                    "ic_pos_pct": np.nan,
                    "t_stat": np.nan,
                    "p_value": np.nan,
                    "p_bonf": np.nan,
                    "n_days": len(daily_ics),
                    "coverage": np.nan,
                    "significant": False,
                })
                continue

            ics = np.array(daily_ics)
            ic_mean = float(np.mean(ics))
            ic_std = float(np.std(ics, ddof=1))
            ic_pos = float(np.mean(ics > 0))
            t_stat, p_val = stats.ttest_1samp(ics, 0)
            p_bonf = min(float(p_val) * N_TESTS, 1.0)

            # 覆蓋率：非 NaN 的 stock-day 佔比
            valid_count = df[factor].notna().sum()
            # 對 Layer 2/3 也看非零佔比
            nonzero_count = (df[factor].notna() & (df[factor] != 0)).sum()
            coverage = float(nonzero_count / len(df)) if len(df) > 0 else 0

            rows.append({
                "horizon": f"{horizon}d",
                "factor": factor,
                "ic_mean": round(ic_mean, 5),
                "ic_std": round(ic_std, 5),
                "ic_pos_pct": round(ic_pos * 100, 1),
                "t_stat": round(float(t_stat), 3),
                "p_value": float(p_val),
                "p_bonf": round(p_bonf, 6),
                "n_days": len(daily_ics),
                "coverage": round(coverage * 100, 1),
                "significant": p_bonf < 0.05,
            })

    result = pd.DataFrame(rows)
    return result


def print_ic_table(ic_df: pd.DataFrame) -> None:
    """美化輸出 IC 結果表"""
    for horizon in HORIZONS:
        subset = ic_df[ic_df["horizon"] == f"{horizon}d"].sort_values(
            "ic_mean", ascending=False, key=abs, na_position="last"
        )
        print(f"\n{'='*80}")
        print(f"  {horizon}d Forward Return — 單因子 IC 排行")
        print(f"{'='*80}")
        print(f"{'Factor':<25s} {'IC':>8s} {'IC±':>8s} {'IC+%':>6s} "
              f"{'t':>7s} {'p(Bonf)':>10s} {'Cov%':>6s} {'Sig':>4s}")
        print("-" * 80)
        for _, r in subset.iterrows():
            sig = "***" if r["significant"] else ""
            if pd.isna(r["ic_mean"]):
                print(f"{r['factor']:<25s}  (insufficient data)")
                continue
            print(f"{r['factor']:<25s} {r['ic_mean']:>8.4f} {r['ic_std']:>8.4f} "
                  f"{r['ic_pos_pct']:>5.1f}% {r['t_stat']:>7.2f} "
                  f"{r['p_bonf']:>10.6f} {r['coverage']:>5.1f}% {sig:>4s}")

    # 跨維度比較
    print(f"\n{'='*80}")
    print(f"  跨維度比較 — 同因子在 5d/10d/20d 的 IC")
    print(f"{'='*80}")
    print(f"{'Factor':<25s} {'5d IC':>8s} {'10d IC':>8s} {'20d IC':>8s} {'趨勢':>8s}")
    print("-" * 80)
    for factor in CANDIDATE_FACTORS:
        vals = {}
        for h in HORIZONS:
            row = ic_df[(ic_df["factor"] == factor) & (ic_df["horizon"] == f"{h}d")]
            vals[h] = row["ic_mean"].values[0] if len(row) > 0 else np.nan

        trend = ""
        if all(not np.isnan(v) for v in vals.values()):
            abs_vals = [abs(vals[h]) for h in HORIZONS]
            if abs_vals[0] > abs_vals[2] * 1.5:
                trend = "短期↑"
            elif abs_vals[2] > abs_vals[0] * 1.5:
                trend = "長期↑"
            else:
                trend = "平穩"

        print(f"{factor:<25s} "
              f"{vals[5]:>8.4f} {vals[10]:>8.4f} {vals[20]:>8.4f} "
              f"{trend:>8s}")


# ═══════════════════════════════════════════════════════════════════
# Phase 5.5: 分年度 IC 穩定性
# ═══════════════════════════════════════════════════════════════════
def yearly_ic_stability(
    df: pd.DataFrame, ic_df: pd.DataFrame
) -> None:
    """對通過篩選的因子做分年度 IC 穩定性檢驗"""
    sig_rows = ic_df[ic_df["significant"]]
    if sig_rows.empty:
        print("\n[穩定性] 無因子通過 Bonferroni 篩選，跳過年度穩定性")
        return

    print(f"\n{'='*80}")
    print(f"  分年度 IC 穩定性（僅通過 Bonferroni 的因子）")
    print(f"{'='*80}")

    df["year"] = df["date"].dt.year
    years = sorted(df["year"].unique())

    for _, r in sig_rows.iterrows():
        factor = r["factor"]
        horizon = r["horizon"]
        h = int(horizon.replace("d", ""))
        fwd_col = f"fwd_ret_{h}d"

        print(f"\n  {factor} ({horizon}):")
        for yr in years:
            yr_data = df[df["year"] == yr]
            daily_ics = []
            for d in sorted(yr_data["date"].unique()):
                day = yr_data.loc[yr_data["date"] == d, [factor, fwd_col]].dropna()
                if len(day) < 30:
                    continue
                if day[factor].nunique() < 3:
                    continue
                ic, _ = stats.spearmanr(day[factor], day[fwd_col])
                if not np.isnan(ic):
                    daily_ics.append(ic)
            if daily_ics:
                ic_mean = np.mean(daily_ics)
                ic_pos = np.mean(np.array(daily_ics) > 0)
                print(f"    {yr}: IC={ic_mean:+.4f}  IC+={ic_pos*100:.0f}%  "
                      f"N={len(daily_ics)}")
            else:
                print(f"    {yr}: (no data)")

    df.drop(columns=["year"], inplace=True)


# ═══════════════════════════════════════════════════════════════════
# Phase 6: Walk-Forward Long-Short 驗證
# ═══════════════════════════════════════════════════════════════════
def longshort_validation(
    df: pd.DataFrame, ic_df: pd.DataFrame
) -> None:
    """對通過篩選的因子做單因子 Long-Short 驗證"""
    sig_rows = ic_df[ic_df["significant"]]
    if sig_rows.empty:
        print("\n[L-S] 無因子通過 Bonferroni 篩選，跳過 Long-Short 驗證")
        # 退而求其次：列出 p < 0.05（未校正）的因子
        relaxed = ic_df[ic_df["p_value"] < 0.05].sort_values("p_value")
        if not relaxed.empty:
            print(f"\n  但有 {len(relaxed)} 個因子在未校正下 p < 0.05：")
            for _, r in relaxed.iterrows():
                print(f"    {r['factor']:25s} {r['horizon']}  "
                      f"IC={r['ic_mean']:+.4f}  p={r['p_value']:.4f}")
        return

    print(f"\n{'='*80}")
    print(f"  Walk-Forward Long-Short 驗證")
    print(f"{'='*80}")

    df["ym"] = df["date"].dt.to_period("M")
    months = sorted(df["ym"].unique())

    for _, r in sig_rows.iterrows():
        factor = r["factor"]
        horizon = r["horizon"]
        h = int(horizon.replace("d", ""))
        fwd_col = f"fwd_ret_{h}d"

        print(f"\n  {factor} ({horizon}), IC={r['ic_mean']:+.4f}")

        # Walk-Forward: 12 月訓練期（只做排序），每月滑動
        train_months = 12
        ls_spreads = []
        top_rets = []
        bot_rets = []

        for i in range(train_months, len(months)):
            test_month = months[i]
            test_data = df[df["ym"] == test_month].dropna(
                subset=[factor, fwd_col]
            ).copy()
            if len(test_data) < 50:
                continue

            # 以每日截面為單位做排序
            test_dates = sorted(test_data["date"].unique())
            for td in test_dates:
                day = test_data[test_data["date"] == td].copy()
                if len(day) < 50:
                    continue

                day["rank"] = day[factor].rank(pct=True)
                top = day[day["rank"] >= 0.9]
                bot = day[day["rank"] <= 0.1]

                if len(top) < 3 or len(bot) < 3:
                    continue

                ret_top = top[fwd_col].mean()
                ret_bot = bot[fwd_col].mean()
                ls = ret_top - ret_bot

                ls_spreads.append(ls)
                top_rets.append(ret_top)
                bot_rets.append(ret_bot)

        if not ls_spreads:
            print(f"    (insufficient data for L-S)")
            continue

        ls_arr = np.array(ls_spreads)
        top_arr = np.array(top_rets)
        bot_arr = np.array(bot_rets)

        avg_ls = np.mean(ls_arr) * 100
        ls_pos = np.mean(ls_arr > 0) * 100
        avg_top = np.mean(top_arr) * 100
        avg_bot = np.mean(bot_arr) * 100
        sharpe = np.mean(ls_arr) / np.std(ls_arr, ddof=1) if np.std(ls_arr) > 0 else 0

        verdict = "PASS" if avg_ls > 1.5 and ls_pos > 60 else (
            "WATCH" if avg_ls > 0.5 else "FAIL"
        )

        print(f"    L-S 均值: {avg_ls:+.2f}%  正比率: {ls_pos:.0f}%  "
              f"Sharpe: {sharpe:.2f}")
        print(f"    Top10%: {avg_top:+.2f}%  Bot10%: {avg_bot:+.2f}%")
        print(f"    判定: {verdict}  (N={len(ls_spreads)} 交易日)")

    if "ym" in df.columns:
        df.drop(columns=["ym"], inplace=True)


# ═══════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════
def main() -> None:
    print("=" * 80)
    print("  K 線型態因子 Alpha 研究")
    print("  16 因子 × 3 維度(5d/10d/20d)，Bonferroni p < 0.00104")
    print("=" * 80)

    # Phase 1
    df = load_data()

    # Phase 2
    df = compute_anatomy_factors(df)

    # Phase 3
    df = detect_patterns(df)

    # Phase 4
    df = compute_rolling_scores(df)

    # Phase 5
    print("\n[IC] 開始計算 16 × 3 = 48 組單因子 IC...")
    ic_df = single_factor_ic(df)
    print_ic_table(ic_df)

    # Phase 5.5: 年度穩定性
    yearly_ic_stability(df, ic_df)

    # Phase 6: Long-Short
    longshort_validation(df, ic_df)

    # 最終結論
    sig = ic_df[ic_df["significant"]]
    print(f"\n{'='*80}")
    print(f"  研究結論")
    print(f"{'='*80}")
    if sig.empty:
        print(f"  全部 {N_TESTS} 組測試中，無因子通過 Bonferroni 校正（p < {BONFERRONI_P:.5f}）")
        relaxed = ic_df[ic_df["p_value"] < 0.05]
        if not relaxed.empty:
            print(f"  但有 {len(relaxed)} 個因子未校正 p < 0.05，可做進一步研究")
        else:
            print(f"  K 線型態對 5d/10d/20d 均無顯著預測力，建議結案")
    else:
        print(f"  {len(sig)} 個因子通過 Bonferroni 校正：")
        for _, r in sig.iterrows():
            print(f"    {r['factor']:25s} {r['horizon']}  "
                  f"IC={r['ic_mean']:+.4f}  p(Bonf)={r['p_bonf']:.6f}")
        print(f"\n  下一步：Partial IC 檢驗（與現有 12 因子的獨立性）")


if __name__ == "__main__":
    main()

"""
Alpha Research — 三條路線聯合研究
Track A: 流動性異象 (Liquidity Anomaly)
Track B: Beta 異象 (Beta Anomaly)
Track E: 盈餘動量 (Earnings Momentum / Post-Earnings Drift)

Methodology:
1. 因子建構（嚴格避免前視偏差）
2. 截面 Spearman Rank IC（每日）
3. Long-Short Q5 vs Q1 驗證
4. Partial IC vs 現有 13 因子
5. 分年穩定性分析

Usage:
    cd backend
    ./.venv/bin/python scripts/research_liquidity_beta_earnings.py
"""
import os
import sys
import warnings
from datetime import date, timedelta
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

# ── 研究參數 ──
STUDY_START = "2023-03-01"  # stock_features 有效起始
STUDY_END = "2026-04-08"
MIN_DAILY_VOLUME = 500  # 張，活躍股過濾
HORIZONS = [1, 2, 3, 5, 10, 20]  # 報酬維度（交易日）
N_QUANTILES = 5  # Long-Short 五分位

# 台灣季報公告截止日（無前視偏差）
# Q1 → 5/15, Q2 → 8/14, Q3 → 11/14, Q4 → 次年 3/31
EPS_AVAIL = {1: (0, 5, 15), 2: (0, 8, 14), 3: (0, 11, 14), 4: (1, 3, 31)}

# 現有 13 訓練因子（用於 Partial IC）
EXISTING_FACTORS = [
    "roe", "yield_rate", "pb_ratio", "revenue_yoy",
    "rev_surprise", "rev_accel",
    "foreign_hold_chg_5d", "dealer_buy_20d", "vol_ratio",
    "ivol_20d",
    "trust_net_buy",  # neg_ prefix handled later
    "short_chg_5d",
    "divergence_avg",  # neg_ prefix handled later
]


# ════════════════════════════════════════
# 1. 資料載入
# ════════════════════════════════════════
def load_prices() -> pd.DataFrame:
    """載入每日 OHLCV（含 stock_features 的 volume 和 close）"""
    print("[1/6] 載入價格資料...")
    query = text("""
        SELECT sp.stock_id, sp.date, sp.open, sp.high, sp.low, sp.close, sp.volume
        FROM stock_prices sp
        WHERE sp.date >= :start AND sp.date <= :end
        ORDER BY sp.stock_id, sp.date
    """)
    df = pd.read_sql(query, engine, params={"start": STUDY_START, "end": STUDY_END})
    df["date"] = pd.to_datetime(df["date"])
    print(f"  → {len(df):,} rows, {df['stock_id'].nunique()} stocks")
    return df


def load_features() -> pd.DataFrame:
    """載入 stock_features 現有因子（用於 Partial IC）"""
    print("[2/6] 載入特徵資料...")
    cols = ["stock_id", "date", "close", "volume"] + [
        f for f in EXISTING_FACTORS
    ]
    col_str = ", ".join(cols)
    query = text(f"""
        SELECT {col_str} FROM stock_features
        WHERE date >= :start AND date <= :end
    """)
    df = pd.read_sql(query, engine, params={"start": STUDY_START, "end": STUDY_END})
    df["date"] = pd.to_datetime(df["date"])
    print(f"  → {len(df):,} rows")
    return df


def load_eps() -> pd.DataFrame:
    """載入季度 EPS 並計算可用日期（避免前視偏差）"""
    print("[3/6] 載入 EPS 資料...")
    query = text("SELECT stock_id, year, quarter, eps FROM stock_eps_history")
    df = pd.read_sql(query, engine)

    # 計算每筆 EPS 對市場可用的日期
    avail_dates = []
    for _, row in df.iterrows():
        year_offset, month, day = EPS_AVAIL[row["quarter"]]
        avail_year = row["year"] + year_offset
        avail_dates.append(pd.Timestamp(avail_year, month, day))
    df["avail_date"] = avail_dates

    print(f"  → {len(df):,} rows, {df['stock_id'].nunique()} stocks")
    return df


def load_industry() -> pd.DataFrame:
    """載入產業分類"""
    query = text("SELECT stock_id, industry FROM stocks WHERE industry IS NOT NULL")
    return pd.read_sql(query, engine)


# ════════════════════════════════════════
# 2. 因子建構
# ════════════════════════════════════════
def build_track_a_factors(prices: pd.DataFrame) -> pd.DataFrame:
    """Track A: 流動性異象因子"""
    print("\n[4/6] 建構因子...")
    print("  Track A: 流動性異象...")

    df = prices.copy()
    df = df.sort_values(["stock_id", "date"])

    # 日報酬率
    df["ret"] = df.groupby("stock_id")["close"].pct_change()

    # Dollar volume（成交金額近似）
    df["dollar_vol"] = df["close"] * df["volume"]

    # ── A1: Amihud 非流動性 (20d) ──
    # |return| / dollar_volume 的 20 日均值
    df["abs_ret_over_dvol"] = df["ret"].abs() / df["dollar_vol"].replace(0, np.nan)
    df["amihud_20d"] = (
        df.groupby("stock_id")["abs_ret_over_dvol"]
        .transform(lambda x: x.rolling(20, min_periods=15).mean())
    )
    # 取 log 避免極端值, 且方向設為負（低流動性 = 高 amihud = 正溢酬 → neg 讓排序方向一致）
    df["log_amihud_20d"] = np.log1p(df["amihud_20d"] * 1e8)  # scale up

    # ── A2: 換手率變化 (20d vs 60d) ──
    df["vol_ma20"] = df.groupby("stock_id")["volume"].transform(
        lambda x: x.rolling(20, min_periods=15).mean()
    )
    df["vol_ma60"] = df.groupby("stock_id")["volume"].transform(
        lambda x: x.rolling(60, min_periods=40).mean()
    )
    df["turnover_chg"] = df["vol_ma20"] / df["vol_ma60"].replace(0, np.nan) - 1

    # ── A3: 成交量變異係數 (20d) ──
    vol_std = df.groupby("stock_id")["volume"].transform(
        lambda x: x.rolling(20, min_periods=15).std()
    )
    df["vol_cv_20d"] = vol_std / df["vol_ma20"].replace(0, np.nan)

    # ── A4: 零成交日比率 (20d) ──
    df["is_zero_vol"] = (df["volume"] == 0).astype(float)
    df["zero_vol_ratio_20d"] = (
        df.groupby("stock_id")["is_zero_vol"]
        .transform(lambda x: x.rolling(20, min_periods=15).mean())
    )

    # ── A5: 流動性改善 (volume momentum) ──
    # 5d 均量 vs 20d 均量
    df["vol_ma5"] = df.groupby("stock_id")["volume"].transform(
        lambda x: x.rolling(5, min_periods=3).mean()
    )
    df["vol_momentum"] = df["vol_ma5"] / df["vol_ma20"].replace(0, np.nan) - 1

    factor_cols = [
        "log_amihud_20d", "turnover_chg", "vol_cv_20d",
        "zero_vol_ratio_20d", "vol_momentum"
    ]
    result = df[["stock_id", "date", "volume"] + factor_cols].copy()
    print(f"    → A 因子: {factor_cols}")
    return result


def build_track_b_factors(prices: pd.DataFrame) -> pd.DataFrame:
    """Track B: Beta 異象因子"""
    print("  Track B: Beta 異象...")

    df = prices.copy()
    df = df.sort_values(["stock_id", "date"])

    # 日報酬
    df["ret"] = df.groupby("stock_id")["close"].pct_change()

    # 市場報酬 = 每日截面中位數
    market_ret = df.groupby("date")["ret"].median().rename("mkt_ret")
    df = df.merge(market_ret, on="date", how="left")

    # 超額報酬
    df["excess_ret"] = df["ret"] - df["mkt_ret"]

    # ── B1: 60d Rolling Beta ──
    def rolling_beta(group: pd.DataFrame, window: int = 60) -> pd.Series:
        """滾動 OLS beta: Cov(ri, rm) / Var(rm)"""
        ret_s = group["ret"]
        mkt_s = group["mkt_ret"]

        cov = ret_s.rolling(window, min_periods=40).cov(mkt_s)
        var = mkt_s.rolling(window, min_periods=40).var()
        return cov / var.replace(0, np.nan)

    df["beta_60d"] = df.groupby("stock_id", group_keys=False).apply(rolling_beta)

    # ── B2: neg_beta (低 beta 溢酬方向) ──
    df["neg_beta_60d"] = -df["beta_60d"]

    # ── B3: 下行 Beta (Downside Beta) ──
    # 只用市場報酬 < 0 的日子計算
    def rolling_downside_beta(group: pd.DataFrame, window: int = 60) -> pd.Series:
        ret_s = group["ret"].copy()
        mkt_s = group["mkt_ret"].copy()
        # mask: mkt >= 0 的日子設為 NaN
        mask = mkt_s >= 0
        ret_masked = ret_s.where(~mask, np.nan)
        mkt_masked = mkt_s.where(~mask, np.nan)

        cov = ret_masked.rolling(window, min_periods=20).cov(mkt_masked)
        var = mkt_masked.rolling(window, min_periods=20).var()
        return cov / var.replace(0, np.nan)

    df["downside_beta_60d"] = df.groupby("stock_id", group_keys=False).apply(
        rolling_downside_beta
    )
    df["neg_downside_beta_60d"] = -df["downside_beta_60d"]

    # ── B4: Beta dispersion (beta - 1 的絕對值，偏離市場程度) ──
    df["beta_deviation"] = (df["beta_60d"] - 1).abs()

    # ── B5: Idiosyncratic skewness (20d) ──
    df["iskew_20d"] = (
        df.groupby("stock_id")["excess_ret"]
        .transform(lambda x: x.rolling(20, min_periods=15).skew())
    )
    df["neg_iskew_20d"] = -df["iskew_20d"]

    factor_cols = [
        "beta_60d", "neg_beta_60d", "downside_beta_60d",
        "neg_downside_beta_60d", "beta_deviation",
        "iskew_20d", "neg_iskew_20d"
    ]
    result = df[["stock_id", "date"] + factor_cols].copy()
    print(f"    → B 因子: {factor_cols}")
    return result


def build_track_e_factors(
    prices: pd.DataFrame, eps_df: pd.DataFrame
) -> pd.DataFrame:
    """Track E: 盈餘動量因子（嚴格避免前視偏差）"""
    print("  Track E: 盈餘動量...")

    # 取得所有交易日
    trade_dates = prices[["date"]].drop_duplicates().sort_values("date")
    all_stocks = prices["stock_id"].unique()

    # 為每個 stock-date 找到「截至該日已公佈」的最新 EPS
    eps = eps_df.sort_values(["stock_id", "year", "quarter"]).copy()

    # 前四季累計 EPS (trailing 4Q)
    eps["trailing_4q"] = (
        eps.groupby("stock_id")["eps"]
        .transform(lambda x: x.rolling(4, min_periods=4).sum())
    )

    # YoY EPS surprise: 本季 EPS - 去年同季 EPS
    eps["eps_yoy_diff"] = eps.groupby(["stock_id", "quarter"])["eps"].diff(1)

    # EPS acceleration: 本季 YoY diff - 上季 YoY diff
    eps["eps_accel"] = eps.groupby("stock_id")["eps_yoy_diff"].diff(1)

    # 對每個交易日，merge 可用的 EPS
    # Strategy: 對 eps 做 avail_date 排序，用 merge_asof
    eps_for_merge = eps[["stock_id", "avail_date", "eps", "trailing_4q",
                         "eps_yoy_diff", "eps_accel"]].dropna(subset=["avail_date"])
    eps_for_merge = eps_for_merge.sort_values(["stock_id", "avail_date"])
    eps_for_merge = eps_for_merge.rename(columns={"avail_date": "date"})

    # 建立 stock-date 框架
    px = prices[["stock_id", "date", "close"]].copy()
    px = px.sort_values(["stock_id", "date"])

    # merge_asof 需要 on 欄位全局單調遞增，改用逐股 merge
    results_list = []
    eps_grouped = eps_for_merge.groupby("stock_id")
    for sid, px_g in px.groupby("stock_id"):
        px_g = px_g.sort_values("date")
        if sid in eps_grouped.groups:
            eps_g = eps_grouped.get_group(sid).sort_values("date")
            merged = pd.merge_asof(px_g, eps_g, on="date", direction="backward", suffixes=("", "_eps"))
            # drop duplicate stock_id column if any
            if "stock_id_eps" in merged.columns:
                merged = merged.drop(columns=["stock_id_eps"])
        else:
            merged = px_g.copy()
            for col in ["eps", "trailing_4q", "eps_yoy_diff", "eps_accel"]:
                merged[col] = np.nan
        results_list.append(merged)
    result = pd.concat(results_list, ignore_index=True)

    # ── E1: Trailing 4Q EPS / Price = Earnings Yield ──
    result["earnings_yield"] = result["trailing_4q"] / result["close"].replace(0, np.nan)

    # ── E2: EPS YoY surprise (最新可用季) ──
    # 已在 eps_yoy_diff 中

    # ── E3: EPS acceleration ──
    # 已在 eps_accel 中

    # ── E4: EPS momentum (trailing 4Q 的 2 季變化) ──
    # 需要前一期 trailing_4q → 用 eps 表做
    eps["prev_trailing_4q"] = eps.groupby("stock_id")["trailing_4q"].shift(1)
    eps["eps_momentum"] = (
        (eps["trailing_4q"] - eps["prev_trailing_4q"])
        / eps["prev_trailing_4q"].abs().replace(0, np.nan)
    )
    eps_mom = eps[["stock_id", "avail_date", "eps_momentum"]].dropna(subset=["avail_date"])
    eps_mom = eps_mom.rename(columns={"avail_date": "date"}).sort_values(["stock_id", "date"])

    # 逐股 merge eps_momentum
    eps_mom_grouped = eps_mom.groupby("stock_id")
    results_list2 = []
    for sid, r_g in result.groupby("stock_id"):
        r_g = r_g.sort_values("date")
        if sid in eps_mom_grouped.groups:
            em_g = eps_mom_grouped.get_group(sid).sort_values("date")
            m = pd.merge_asof(r_g, em_g[["date", "eps_momentum"]], on="date", direction="backward")
        else:
            m = r_g.copy()
            m["eps_momentum"] = np.nan
        results_list2.append(m)
    result = pd.concat(results_list2, ignore_index=True)

    factor_cols = [
        "earnings_yield", "eps_yoy_diff", "eps_accel", "eps_momentum"
    ]
    result = result[["stock_id", "date"] + factor_cols].copy()
    print(f"    → E 因子: {factor_cols}")
    return result


# ════════════════════════════════════════
# 3. 前向報酬計算
# ════════════════════════════════════════
def compute_forward_returns(prices: pd.DataFrame) -> pd.DataFrame:
    """計算各維度前向報酬"""
    print("  計算前向報酬...")
    df = prices[["stock_id", "date", "close"]].copy()
    df = df.sort_values(["stock_id", "date"])

    for h in HORIZONS:
        df[f"fwd_ret_{h}d"] = (
            df.groupby("stock_id")["close"]
            .transform(lambda x: x.shift(-h) / x - 1)
        )

    # 市場中位數報酬（用於超額報酬）
    for h in HORIZONS:
        mkt = df.groupby("date")[f"fwd_ret_{h}d"].median().rename(f"mkt_ret_{h}d")
        df = df.merge(mkt, on="date", how="left")
        df[f"fwd_excess_{h}d"] = df[f"fwd_ret_{h}d"] - df[f"mkt_ret_{h}d"]

    return df


# ════════════════════════════════════════
# 4. 截面 IC 分析
# ════════════════════════════════════════
def cross_sectional_ic(
    merged: pd.DataFrame, factor: str, horizons: List[int] = HORIZONS
) -> Dict:
    """每日截面 Spearman Rank IC"""
    results = {}
    for h in horizons:
        ret_col = f"fwd_ret_{h}d"
        daily_ic = (
            merged.dropna(subset=[factor, ret_col])
            .groupby("date")
            .apply(
                lambda g: g[factor].corr(g[ret_col], method="spearman")
                if len(g) > 30 else np.nan,
                include_groups=False,
            )
        )
        daily_ic = daily_ic.dropna()

        if len(daily_ic) < 30:
            results[h] = {
                "ic": np.nan, "ic_std": np.nan, "ir": np.nan,
                "ic_pos_pct": np.nan, "t_stat": np.nan, "p_value": np.nan,
                "n_days": 0
            }
            continue

        ic_mean = daily_ic.mean()
        ic_std = daily_ic.std()
        ir = ic_mean / ic_std if ic_std > 0 else 0
        t_stat = ic_mean / (ic_std / np.sqrt(len(daily_ic)))
        p_value = 2 * (1 - stats.t.cdf(abs(t_stat), len(daily_ic) - 1))
        ic_pos = (daily_ic > 0).mean()

        results[h] = {
            "ic": ic_mean, "ic_std": ic_std, "ir": ir,
            "ic_pos_pct": ic_pos, "t_stat": t_stat, "p_value": p_value,
            "n_days": len(daily_ic), "daily_ic": daily_ic
        }
    return results


def annual_stability(daily_ic: pd.Series) -> Dict[int, float]:
    """分年 IC 均值"""
    daily_ic.index = pd.to_datetime(daily_ic.index)
    return daily_ic.groupby(daily_ic.index.year).mean().to_dict()


# ════════════════════════════════════════
# 5. Long-Short 驗證
# ════════════════════════════════════════
def long_short_test(
    merged: pd.DataFrame, factor: str, horizons: List[int] = HORIZONS
) -> Dict:
    """五分位 Long-Short 測試"""
    results = {}
    for h in horizons:
        ret_col = f"fwd_ret_{h}d"
        sub = merged.dropna(subset=[factor, ret_col]).copy()

        # 每日截面五分位
        sub["quantile"] = (
            sub.groupby("date")[factor]
            .transform(lambda x: pd.qcut(x, N_QUANTILES, labels=False, duplicates="drop") + 1
                        if len(x.dropna()) >= N_QUANTILES * 10 else np.nan)
        )
        sub = sub.dropna(subset=["quantile"])

        # Q5 (highest) - Q1 (lowest)
        q_rets = sub.groupby(["date", "quantile"])[ret_col].mean().unstack()
        if N_QUANTILES not in q_rets.columns or 1 not in q_rets.columns:
            results[h] = {"ls_mean": np.nan, "ls_pos_pct": np.nan, "sharpe": np.nan}
            continue

        ls = q_rets[N_QUANTILES] - q_rets[1]
        ls = ls.dropna()

        ls_mean = ls.mean()
        ls_pos = (ls > 0).mean()
        ls_std = ls.std()
        sharpe = ls_mean / ls_std * np.sqrt(252 / h) if ls_std > 0 else 0

        # 分位報酬
        q_means = {}
        for q in range(1, N_QUANTILES + 1):
            if q in q_rets.columns:
                q_means[f"Q{q}"] = q_rets[q].mean()

        results[h] = {
            "ls_mean": ls_mean, "ls_pos_pct": ls_pos, "sharpe": sharpe,
            "q_means": q_means, "n_days": len(ls)
        }
    return results


# ════════════════════════════════════════
# 6. Partial IC（控制現有因子）
# ════════════════════════════════════════
def partial_ic(
    merged: pd.DataFrame, new_factor: str,
    control_factors: List[str], horizon: int = 20
) -> Dict:
    """
    Partial IC: 新因子對報酬的 IC，控制現有因子後。
    方法：新因子 & 報酬分別對控制因子做截面回歸，取殘差的 Spearman 相關。
    """
    ret_col = f"fwd_ret_{horizon}d"
    all_cols = [new_factor] + control_factors + [ret_col]

    sub = merged.dropna(subset=all_cols).copy()

    daily_partial_ic = []
    dates = []

    for dt, group in sub.groupby("date"):
        if len(group) < 50:
            continue

        # rank transform
        X = group[control_factors].rank(pct=True).values
        y_factor = group[new_factor].rank(pct=True).values
        y_ret = group[ret_col].rank(pct=True).values

        # OLS 殘差
        try:
            X_with_const = np.column_stack([np.ones(len(X)), X])

            # factor residual
            beta_f = np.linalg.lstsq(X_with_const, y_factor, rcond=None)[0]
            resid_factor = y_factor - X_with_const @ beta_f

            # return residual
            beta_r = np.linalg.lstsq(X_with_const, y_ret, rcond=None)[0]
            resid_ret = y_ret - X_with_const @ beta_r

            # Spearman corr of residuals
            corr, _ = stats.spearmanr(resid_factor, resid_ret)
            daily_partial_ic.append(corr)
            dates.append(dt)
        except Exception:
            continue

    if len(daily_partial_ic) < 30:
        return {"partial_ic": np.nan, "raw_ic": np.nan, "retention": np.nan}

    pic = pd.Series(daily_partial_ic, index=dates)

    # raw IC for comparison
    raw = cross_sectional_ic(merged, new_factor, [horizon])
    raw_ic = raw[horizon]["ic"]

    pic_mean = pic.mean()
    pic_std = pic.std()
    t_stat = pic_mean / (pic_std / np.sqrt(len(pic)))
    p_value = 2 * (1 - stats.t.cdf(abs(t_stat), len(pic) - 1))

    return {
        "partial_ic": pic_mean,
        "raw_ic": raw_ic,
        "retention": pic_mean / raw_ic if raw_ic != 0 else np.nan,
        "t_stat": t_stat,
        "p_value": p_value,
        "n_days": len(pic)
    }


# ════════════════════════════════════════
# 7. 活躍股過濾
# ════════════════════════════════════════
def filter_active(df: pd.DataFrame, min_vol: int = MIN_DAILY_VOLUME) -> pd.DataFrame:
    """過濾低成交量股票"""
    if "volume" not in df.columns:
        return df
    before = len(df)
    df = df[df["volume"] >= min_vol * 1000]  # volume 單位是股, 1張=1000股
    print(f"  活躍股過濾: {before:,} → {len(df):,} ({len(df)/before*100:.1f}%)")
    return df


# ════════════════════════════════════════
# MAIN
# ════════════════════════════════════════
def main():
    print("=" * 70)
    print("AlphaForge Alpha Research — 流動性 / Beta / 盈餘動量")
    print("=" * 70)

    # 載入資料
    prices = load_prices()
    features = load_features()
    eps_raw = load_eps()

    # 過濾活躍股
    prices = filter_active(prices)

    # 建構因子
    fa = build_track_a_factors(prices)
    fb = build_track_b_factors(prices)
    fe = build_track_e_factors(prices, eps_raw)

    # 前向報酬
    fwd = compute_forward_returns(prices)

    # 合併
    base = fwd[["stock_id", "date"] + [f"fwd_ret_{h}d" for h in HORIZONS] +
               [f"fwd_excess_{h}d" for h in HORIZONS]]

    merged_a = base.merge(fa, on=["stock_id", "date"], how="inner")
    merged_b = base.merge(fb, on=["stock_id", "date"], how="inner")
    merged_e = base.merge(fe, on=["stock_id", "date"], how="inner")

    # 加入現有因子用於 Partial IC
    feat_slim = features[["stock_id", "date"] + [
        f for f in EXISTING_FACTORS if f in features.columns
    ]].copy()
    feat_slim["date"] = pd.to_datetime(feat_slim["date"])

    all_factors = {}

    # ════════════════════════════════════════
    # Track A: 流動性異象
    # ════════════════════════════════════════
    print("\n" + "=" * 70)
    print("Track A: 流動性異象 (Liquidity Anomaly)")
    print("=" * 70)

    track_a_factors = [
        "log_amihud_20d", "turnover_chg", "vol_cv_20d",
        "zero_vol_ratio_20d", "vol_momentum"
    ]

    for factor in track_a_factors:
        print(f"\n--- {factor} ---")
        ic_results = cross_sectional_ic(merged_a, factor)
        all_factors[factor] = {"track": "A", "ic": ic_results}

        for h in HORIZONS:
            r = ic_results[h]
            if r["n_days"] == 0:
                continue
            sig = "***" if r["p_value"] < 0.001 else "**" if r["p_value"] < 0.01 else "*" if r["p_value"] < 0.05 else ""
            print(f"  {h:2d}d: IC={r['ic']:+.4f} IC+={r['ic_pos_pct']:.1%} t={r['t_stat']:+.2f} p={r['p_value']:.4f}{sig}")

            if "daily_ic" in r and r["n_days"] > 100:
                yearly = annual_stability(r["daily_ic"])
                yr_str = " | ".join(f"{y}:{v:+.4f}" for y, v in sorted(yearly.items()))
                print(f"        年度: {yr_str}")

    # ════════════════════════════════════════
    # Track B: Beta 異象
    # ════════════════════════════════════════
    print("\n" + "=" * 70)
    print("Track B: Beta 異象 (Beta Anomaly)")
    print("=" * 70)

    track_b_factors = [
        "beta_60d", "neg_beta_60d", "downside_beta_60d",
        "neg_downside_beta_60d", "beta_deviation",
        "iskew_20d", "neg_iskew_20d"
    ]

    for factor in track_b_factors:
        print(f"\n--- {factor} ---")
        ic_results = cross_sectional_ic(merged_b, factor)
        all_factors[factor] = {"track": "B", "ic": ic_results}

        for h in HORIZONS:
            r = ic_results[h]
            if r["n_days"] == 0:
                continue
            sig = "***" if r["p_value"] < 0.001 else "**" if r["p_value"] < 0.01 else "*" if r["p_value"] < 0.05 else ""
            print(f"  {h:2d}d: IC={r['ic']:+.4f} IC+={r['ic_pos_pct']:.1%} t={r['t_stat']:+.2f} p={r['p_value']:.4f}{sig}")

            if "daily_ic" in r and r["n_days"] > 100:
                yearly = annual_stability(r["daily_ic"])
                yr_str = " | ".join(f"{y}:{v:+.4f}" for y, v in sorted(yearly.items()))
                print(f"        年度: {yr_str}")

    # ════════════════════════════════════════
    # Track E: 盈餘動量
    # ════════════════════════════════════════
    print("\n" + "=" * 70)
    print("Track E: 盈餘動量 (Earnings Momentum)")
    print("=" * 70)

    track_e_factors = [
        "earnings_yield", "eps_yoy_diff", "eps_accel", "eps_momentum"
    ]

    for factor in track_e_factors:
        print(f"\n--- {factor} ---")
        ic_results = cross_sectional_ic(merged_e, factor)
        all_factors[factor] = {"track": "E", "ic": ic_results}

        for h in HORIZONS:
            r = ic_results[h]
            if r["n_days"] == 0:
                continue
            sig = "***" if r["p_value"] < 0.001 else "**" if r["p_value"] < 0.01 else "*" if r["p_value"] < 0.05 else ""
            print(f"  {h:2d}d: IC={r['ic']:+.4f} IC+={r['ic_pos_pct']:.1%} t={r['t_stat']:+.2f} p={r['p_value']:.4f}{sig}")

            if "daily_ic" in r and r["n_days"] > 100:
                yearly = annual_stability(r["daily_ic"])
                yr_str = " | ".join(f"{y}:{v:+.4f}" for y, v in sorted(yearly.items()))
                print(f"        年度: {yr_str}")

    # ════════════════════════════════════════
    # Long-Short 驗證（僅顯著因子）
    # ════════════════════════════════════════
    print("\n" + "=" * 70)
    print("Long-Short 五分位驗證（IC 顯著的因子）")
    print("=" * 70)

    significant_factors = []
    for factor, data in all_factors.items():
        for h in HORIZONS:
            r = data["ic"].get(h, {})
            if r.get("p_value", 1) < 0.05:
                significant_factors.append(factor)
                break

    print(f"\n通過 p<0.05 篩選的因子: {significant_factors}")

    factor_to_merged = {}
    for f in track_a_factors:
        factor_to_merged[f] = merged_a
    for f in track_b_factors:
        factor_to_merged[f] = merged_b
    for f in track_e_factors:
        factor_to_merged[f] = merged_e

    ls_results = {}
    for factor in significant_factors:
        merged_df = factor_to_merged[factor]
        print(f"\n--- {factor} L-S ---")
        ls = long_short_test(merged_df, factor)
        ls_results[factor] = ls

        for h in HORIZONS:
            r = ls[h]
            if np.isnan(r.get("ls_mean", np.nan)):
                continue
            status = "PASS" if r["ls_pos_pct"] > 0.55 and r["sharpe"] > 0.1 else "FAIL"
            print(f"  {h:2d}d: L-S={r['ls_mean']:+.3%} 正比率={r['ls_pos_pct']:.1%} Sharpe={r['sharpe']:.2f} [{status}]")
            if "q_means" in r:
                q_str = " | ".join(f"{k}:{v:+.3%}" for k, v in r["q_means"].items())
                print(f"        分位: {q_str}")

    # ════════════════════════════════════════
    # Partial IC（僅 L-S PASS 的因子）
    # ════════════════════════════════════════
    print("\n" + "=" * 70)
    print("Partial IC 檢驗（控制現有 13 因子）")
    print("=" * 70)

    # 找 L-S pass 的因子
    ls_pass_factors = []
    for factor, ls_data in ls_results.items():
        for h in [20, 10, 5]:
            r = ls_data.get(h, {})
            if r.get("ls_pos_pct", 0) > 0.55 and r.get("sharpe", 0) > 0.1:
                ls_pass_factors.append((factor, h))
                break

    print(f"\nL-S PASS 因子: {ls_pass_factors}")

    # 準備 Partial IC 的控制因子
    control_cols = []
    for f in EXISTING_FACTORS:
        if f in feat_slim.columns:
            control_cols.append(f)

    for factor, best_h in ls_pass_factors:
        merged_df = factor_to_merged[factor]
        # merge with features
        merged_with_ctrl = merged_df.merge(feat_slim, on=["stock_id", "date"], how="inner", suffixes=("", "_ctrl"))

        # drop duplicate columns
        for col in merged_with_ctrl.columns:
            if col.endswith("_ctrl"):
                merged_with_ctrl.drop(col, axis=1, inplace=True)

        available_ctrl = [c for c in control_cols if c in merged_with_ctrl.columns]

        print(f"\n--- {factor} (vs {len(available_ctrl)} 控制因子, {best_h}d) ---")
        pic = partial_ic(merged_with_ctrl, factor, available_ctrl, best_h)

        if not np.isnan(pic.get("partial_ic", np.nan)):
            ret_str = f"{pic['retention']:.0%}" if not np.isnan(pic.get("retention", np.nan)) else "N/A"
            sig = "***" if pic["p_value"] < 0.001 else "**" if pic["p_value"] < 0.01 else "*" if pic["p_value"] < 0.05 else ""
            print(f"  Raw IC:     {pic['raw_ic']:+.4f}")
            print(f"  Partial IC: {pic['partial_ic']:+.4f} (保留率 {ret_str})")
            print(f"  t={pic['t_stat']:+.2f} p={pic['p_value']:.4f}{sig}")

    # ════════════════════════════════════════
    # 總結
    # ════════════════════════════════════════
    print("\n" + "=" * 70)
    print("研究總結")
    print("=" * 70)

    print("\n[所有因子 20d IC 排名]")
    summary = []
    for factor, data in all_factors.items():
        r20 = data["ic"].get(20, {})
        ic20 = r20.get("ic", np.nan)
        p20 = r20.get("p_value", np.nan)
        pos20 = r20.get("ic_pos_pct", np.nan)
        summary.append((factor, data["track"], ic20, p20, pos20))

    summary.sort(key=lambda x: abs(x[2]) if not np.isnan(x[2]) else 0, reverse=True)

    print(f"{'因子':<30s} {'Track':>5s} {'20d IC':>8s} {'p':>8s} {'IC+%':>6s}")
    print("-" * 60)
    for name, track, ic, p, pos in summary:
        sig = "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else ""
        ic_str = f"{ic:+.4f}" if not np.isnan(ic) else "N/A"
        p_str = f"{p:.4f}" if not np.isnan(p) else "N/A"
        pos_str = f"{pos:.1%}" if not np.isnan(pos) else "N/A"
        print(f"{name:<30s} {track:>5s} {ic_str:>8s} {p_str:>8s}{sig} {pos_str:>6s}")

    print("\n[顯著因子最佳維度 IC]")
    for factor in significant_factors:
        data = all_factors[factor]
        best_h = max(HORIZONS, key=lambda h: abs(data["ic"][h].get("ic", 0)))
        r = data["ic"][best_h]
        print(f"  {factor}: {best_h}d IC={r['ic']:+.4f} p={r['p_value']:.4f}")

    print("\nDone.")


if __name__ == "__main__":
    main()

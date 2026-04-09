"""
背離因子 (Divergence) Alpha 研究

ECF 背離偵測邏輯：20 日窗口內找兩個高/低點，比較價格與 RSI/MACD/KD 的方向一致性。
頂背離：價格創新高但 RSI 未創新高 → 看跌
底背離：價格創新低但 RSI 未創新低 → 看漲

候選因子（連續型 + 事件型）：
  Layer 1 連續型（每日有值，適合截面 IC）：
    - rsi_price_corr_20d: 20 日 RSI 變化與價格變化的相關性（負 = 背離）
    - macd_price_corr_20d: 同上用 MACD DIF
    - rsi_divergence_score: (價格距20d高點%) - (RSI距20d高點%) 的差異
    - momentum_exhaustion: 價格動量 vs RSI 動量的差距

  Layer 2 事件型（事件研究 + 波動率校正）：
    - rsi_bull_div: RSI 底背離 0/1
    - rsi_bear_div: RSI 頂背離 0/1
    - multi_div: 多指標同時背離 0/1
"""
from __future__ import annotations

import os
import warnings
from typing import List, Tuple

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

HORIZONS = [1, 2, 3, 5, 10, 20]


def _ttest(arr: np.ndarray):
    if len(arr) < 20:
        return np.nan, np.nan
    t, p = stats.ttest_1samp(arr, 0)
    return float(t), float(p)


def _stars(p: float) -> str:
    if np.isnan(p):
        return ""
    return "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else ""


# ═══════════════════════════════════════════════════════════════════
# 資料載入 + 指標計算
# ═══════════════════════════════════════════════════════════════════
def load_and_prepare() -> pd.DataFrame:
    sql = text("""
        SELECT stock_id, date, open, high, low, close, volume
        FROM stock_prices
        WHERE date >= '2022-09-01' AND close > 0
        ORDER BY stock_id, date
    """)
    df = pd.read_sql(sql, engine)
    df["date"] = pd.to_datetime(df["date"])

    grp = df.groupby("stock_id")

    # 流動性過濾
    df["vol_ma20"] = grp["volume"].transform(lambda x: x.rolling(20, min_periods=5).mean())
    df = df[df["vol_ma20"] >= 500_000].copy()
    df = df[df["stock_id"].str.match(r"^[1-9]\d{3}$")].copy()

    grp = df.groupby("stock_id")

    # ─── 技術指標 ─────────────────────────────────────────────────
    # RSI 14
    delta = grp["close"].diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = grp["close"].transform(
        lambda x: pd.Series(np.where(x.index == x.index, np.nan, np.nan), index=x.index)
    )
    # 用 ewm 計算 RSI
    avg_gain = gain.groupby(df["stock_id"]).transform(lambda x: x.ewm(span=14, adjust=False).mean())
    avg_loss = loss.groupby(df["stock_id"]).transform(lambda x: x.ewm(span=14, adjust=False).mean())
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["rsi"] = 100 - (100 / (1 + rs))

    # MACD DIF
    ema12 = grp["close"].transform(lambda x: x.ewm(span=12, adjust=False).mean())
    ema26 = grp["close"].transform(lambda x: x.ewm(span=26, adjust=False).mean())
    df["macd_dif"] = ema12 - ema26

    # KD (9,3,3)
    low9 = grp["low"].transform(lambda x: x.rolling(9, min_periods=5).min())
    high9 = grp["high"].transform(lambda x: x.rolling(9, min_periods=5).max())
    rsv = (df["close"] - low9) / (high9 - low9).replace(0, np.nan) * 100
    df["k_val"] = rsv.groupby(df["stock_id"]).transform(
        lambda x: x.ewm(span=3, adjust=False).mean()
    )

    # 日報酬
    df["daily_ret"] = grp["close"].pct_change()

    # 波動率
    df["volatility"] = grp["daily_ret"].transform(lambda x: x.rolling(20, min_periods=10).std())
    df["vol_quintile"] = df.groupby("date")["volatility"].transform(
        lambda x: pd.qcut(x, 5, labels=False, duplicates="drop")
    )

    # Forward returns + excess
    grp = df.groupby("stock_id")
    for h in HORIZONS:
        entry = grp["close"].shift(-1)
        exit_ = grp["close"].shift(-(1 + h))
        df[f"fwd_{h}d"] = (exit_ - entry) / entry
        df[f"mkt_{h}d"] = df.groupby("date")[f"fwd_{h}d"].transform("median")
        df[f"excess_{h}d"] = df[f"fwd_{h}d"] - df[f"mkt_{h}d"]

    # 只保留 2023 以後（前面是暖機期）
    df = df[df["date"] >= "2023-01-01"].copy()

    print(f"[Data] {len(df):,} 筆，{df['stock_id'].nunique()} 檔")
    return df


# ═══════════════════════════════════════════════════════════════════
# Layer 1: 連續型背離因子
# ═══════════════════════════════════════════════════════════════════
def compute_continuous_factors(df: pd.DataFrame) -> pd.DataFrame:
    grp = df.groupby("stock_id")

    # 1. RSI-價格相關性（20d 滾動）
    df["_rsi_chg"] = grp["rsi"].diff()
    df["_price_chg"] = df["daily_ret"]

    df["rsi_price_corr_20d"] = df.groupby("stock_id").apply(
        lambda g: g["_rsi_chg"].rolling(20, min_periods=10).corr(g["_price_chg"])
    ).reset_index(level=0, drop=True)

    # 2. MACD-價格相關性
    df["_dif_chg"] = grp["macd_dif"].diff()
    df["macd_price_corr_20d"] = df.groupby("stock_id").apply(
        lambda g: g["_dif_chg"].rolling(20, min_periods=10).corr(g["_price_chg"])
    ).reset_index(level=0, drop=True)

    # 3. RSI 背離分數：價格距 20d 高點% vs RSI 距 20d 高點%
    df["_price_high20"] = grp["close"].transform(lambda x: x.rolling(20, min_periods=10).max())
    df["_rsi_high20"] = grp["rsi"].transform(lambda x: x.rolling(20, min_periods=10).max())
    df["_price_low20"] = grp["close"].transform(lambda x: x.rolling(20, min_periods=10).min())
    df["_rsi_low20"] = grp["rsi"].transform(lambda x: x.rolling(20, min_periods=10).min())

    price_pct_high = (df["close"] - df["_price_high20"]) / df["_price_high20"]
    rsi_pct_high = (df["rsi"] - df["_rsi_high20"]) / df["_rsi_high20"].replace(0, np.nan)
    # 頂背離分數：價格接近高點但 RSI 遠離高點 → 正值
    df["div_score_top"] = price_pct_high - rsi_pct_high

    price_pct_low = (df["close"] - df["_price_low20"]) / df["_price_low20"].replace(0, np.nan)
    rsi_pct_low = (df["rsi"] - df["_rsi_low20"]) / df["_rsi_low20"].replace(0, np.nan)
    # 底背離分數：價格接近低點但 RSI 遠離低點 → 負值
    df["div_score_bot"] = price_pct_low - rsi_pct_low

    # 4. 動量衰竭指標：5d 價格動量 vs 5d RSI 動量
    df["_price_mom5"] = grp["close"].pct_change(5)
    df["_rsi_mom5"] = grp["rsi"].diff(5)
    # 動量差距：價格動量正但 RSI 動量負 → 動量衰竭（正值 = 頂背離方向）
    df["momentum_exhaust"] = df["_price_mom5"] * 100 - df["_rsi_mom5"]

    # 5. 綜合背離指標（RSI + MACD 相關性平均，取負 → 負相關越強 = 背離越嚴重）
    df["neg_divergence_avg"] = -(df["rsi_price_corr_20d"].fillna(0) +
                                  df["macd_price_corr_20d"].fillna(0)) / 2

    # 清理暫存
    drop_cols = [c for c in df.columns if c.startswith("_")]
    df.drop(columns=drop_cols, inplace=True)

    print(f"[Layer 1] 6 個連續型背離因子計算完成")
    return df


# ═══════════════════════════════════════════════════════════════════
# Layer 2: 事件型背離偵測（ECF 邏輯）
# ═══════════════════════════════════════════════════════════════════
def detect_divergence_events(df: pd.DataFrame) -> pd.DataFrame:
    """向量化偵測 RSI/MACD/KD 背離事件"""
    grp = df.groupby("stock_id")

    for indicator, col in [("rsi", "rsi"), ("dif", "macd_dif"), ("kd", "k_val")]:
        # 20 日滾動高低點
        high20 = grp["high"].transform(lambda x: x.rolling(20, min_periods=10).max())
        low20 = grp["low"].transform(lambda x: x.rolling(20, min_periods=10).min())
        ind_at_high = grp.apply(
            lambda g: g[col].where(g["high"] == g["high"].rolling(20, min_periods=10).max())
                            .ffill(limit=5)
        ).reset_index(level=0, drop=True)
        ind_at_low = grp.apply(
            lambda g: g[col].where(g["low"] == g["low"].rolling(20, min_periods=10).min())
                            .ffill(limit=5)
        ).reset_index(level=0, drop=True)

        # 前一個高/低點的指標值（shift 5 天）
        prev_ind_high = grp[col].transform(lambda x: x.rolling(20, min_periods=10).max()).shift(5)
        prev_ind_low = grp[col].transform(lambda x: x.rolling(20, min_periods=10).min()).shift(5)
        prev_price_high = grp["high"].transform(lambda x: x.rolling(20, min_periods=10).max()).shift(5)
        prev_price_low = grp["low"].transform(lambda x: x.rolling(20, min_periods=10).min()).shift(5)

        # 簡化版背離偵測：
        # 頂背離：當前價格 >= 前期高點 * 0.99 但指標 < 前期指標高點 * 0.95
        near_price_high = df["close"] >= prev_price_high * 0.99
        indicator_lower = df[col] < prev_ind_high * 0.95
        df[f"{indicator}_bear_div"] = (near_price_high & indicator_lower).astype(np.int8)

        # 底背離：當前價格 <= 前期低點 * 1.01 但指標 > 前期指標低點 * 1.05
        near_price_low = df["close"] <= prev_price_low * 1.01
        indicator_higher = df[col] > prev_ind_low * 1.05
        df[f"{indicator}_bull_div"] = (near_price_low & indicator_higher).astype(np.int8)

    # 多指標背離
    df["multi_bear_div"] = (
        (df["rsi_bear_div"] + df["dif_bear_div"] + df["kd_bear_div"]) >= 2
    ).astype(np.int8)
    df["multi_bull_div"] = (
        (df["rsi_bull_div"] + df["dif_bull_div"] + df["kd_bull_div"]) >= 2
    ).astype(np.int8)

    # 統計
    for div_type in ["rsi_bear_div", "rsi_bull_div", "dif_bear_div", "dif_bull_div",
                     "kd_bear_div", "kd_bull_div", "multi_bear_div", "multi_bull_div"]:
        n = df[div_type].sum()
        print(f"  {div_type:20s}: {n:>7,} ({n/len(df)*100:.2f}%)")

    return df


# ═══════════════════════════════════════════════════════════════════
# 截面 IC 測試（連續型因子）
# ═══════════════════════════════════════════════════════════════════
CONTINUOUS_FACTORS = [
    "rsi_price_corr_20d", "macd_price_corr_20d",
    "div_score_top", "div_score_bot",
    "momentum_exhaust", "neg_divergence_avg",
]


def test_continuous_ic(df: pd.DataFrame) -> pd.DataFrame:
    print(f"\n{'='*90}")
    print(f"  截面 IC 測試（連續型背離因子 × 6 維度）")
    print(f"{'='*90}")

    rows = []
    n_tests = len(CONTINUOUS_FACTORS) * len(HORIZONS)

    for horizon in HORIZONS:
        fwd_col = f"fwd_{horizon}d"
        for factor in CONTINUOUS_FACTORS:
            daily_ics = []
            for d in sorted(df["date"].unique()):
                day = df.loc[df["date"] == d, [factor, fwd_col]].dropna()
                if len(day) < 30 or day[factor].nunique() < 3:
                    continue
                ic, _ = stats.spearmanr(day[factor], day[fwd_col])
                if not np.isnan(ic):
                    daily_ics.append(ic)

            if len(daily_ics) < 20:
                rows.append({"horizon": f"{horizon}d", "factor": factor,
                            "ic": np.nan, "p_bonf": np.nan})
                continue

            ics = np.array(daily_ics)
            ic_mean = np.mean(ics)
            ic_std = np.std(ics, ddof=1)
            ic_pos = np.mean(ics > 0)
            _, p = stats.ttest_1samp(ics, 0)
            p_bonf = min(float(p) * n_tests, 1.0)

            rows.append({
                "horizon": f"{horizon}d", "factor": factor,
                "ic": round(ic_mean, 5), "ic_std": round(ic_std, 5),
                "ic_pos": round(ic_pos * 100, 1),
                "p_bonf": round(p_bonf, 6), "n_days": len(daily_ics),
                "sig": p_bonf < 0.05,
            })

    result = pd.DataFrame(rows)

    for horizon in HORIZONS:
        subset = result[result["horizon"] == f"{horizon}d"].sort_values(
            "ic", ascending=False, key=abs, na_position="last"
        )
        print(f"\n  {horizon}d:")
        for _, r in subset.iterrows():
            if pd.isna(r.get("ic")):
                continue
            sig = "***" if r.get("sig") else ""
            print(f"    {r['factor']:<25s} IC={r['ic']:>+.4f} ±{r['ic_std']:.4f}  "
                  f"IC+={r['ic_pos']:>5.1f}%  p(Bonf)={r['p_bonf']:.5f} {sig}")

    return result


# ═══════════════════════════════════════════════════════════════════
# 事件研究（事件型因子，波動率校正）
# ═══════════════════════════════════════════════════════════════════
def test_event_study(df: pd.DataFrame) -> None:
    print(f"\n{'='*90}")
    print(f"  事件研究：背離事件的波動率校正後超額報酬")
    print(f"{'='*90}")

    # 預算各五分位基準
    baselines = {}
    ctrl = df[
        (df["rsi_bear_div"] == 0) & (df["rsi_bull_div"] == 0)
        & (df["dif_bear_div"] == 0) & (df["dif_bull_div"] == 0)
    ]
    for q in range(5):
        q_ctrl = ctrl[ctrl["vol_quintile"] == q]
        for h in HORIZONS:
            baselines[(q, h)] = q_ctrl[f"excess_{h}d"].dropna().mean()

    events_list = [
        ("rsi_bull_div", "RSI 底背離（看漲）"),
        ("rsi_bear_div", "RSI 頂背離（看跌）"),
        ("dif_bull_div", "MACD 底背離（看漲）"),
        ("dif_bear_div", "MACD 頂背離（看跌）"),
        ("kd_bull_div", "KD 底背離（看漲）"),
        ("kd_bear_div", "KD 頂背離（看跌）"),
        ("multi_bull_div", "多指標底背離（看漲）"),
        ("multi_bear_div", "多指標頂背離（看跌）"),
    ]

    for col, label in events_list:
        events = df[df[col] == 1]
        n = len(events)
        if n < 50:
            print(f"\n  {label}: N={n} (樣本不足)")
            continue

        parts = [f"{label:25s} N={n:>6,} |"]
        for h in HORIZONS:
            adj_vals = []
            for q in range(5):
                q_ev = events[events["vol_quintile"] == q][f"excess_{h}d"].dropna()
                bl = baselines.get((q, h), 0)
                if len(q_ev) > 3:
                    adj_vals.extend((q_ev.values - bl).tolist())
            arr = np.array(adj_vals)
            if len(arr) < 20:
                parts.append(f" {h}d:  N/A  ")
                continue
            m = np.mean(arr) * 100
            _, p = _ttest(arr)
            parts.append(f" {h}d:{m:>+6.2f}%{_stars(p):3s}")
        print("  " + "  ".join(parts))


# ═══════════════════════════════════════════════════════════════════
# 分年度穩定性（連續型因子）
# ═══════════════════════════════════════════════════════════════════
def test_yearly_stability(df: pd.DataFrame, ic_df: pd.DataFrame) -> None:
    sig_factors = ic_df[ic_df.get("sig", False) == True]
    if sig_factors.empty:
        # 退而求其次：列出 raw p < 0.05 的
        relaxed = ic_df[ic_df["p_bonf"] < 1.0].sort_values("p_bonf")
        if relaxed.empty:
            return
        sig_factors = relaxed.head(5)

    print(f"\n{'='*90}")
    print(f"  分年度 IC 穩定性（前 5 強因子）")
    print(f"{'='*90}")

    df["year"] = df["date"].dt.year
    years = sorted(df["year"].unique())

    for _, r in sig_factors.iterrows():
        factor = r["factor"]
        horizon = r["horizon"]
        h = int(horizon.replace("d", ""))
        fwd_col = f"fwd_{h}d"

        print(f"\n  {factor} ({horizon}), 全期 IC={r['ic']:+.4f}:")
        for yr in years:
            yr_data = df[df["year"] == yr]
            daily_ics = []
            for d in sorted(yr_data["date"].unique()):
                day = yr_data.loc[yr_data["date"] == d, [factor, fwd_col]].dropna()
                if len(day) < 30 or day[factor].nunique() < 3:
                    continue
                ic, _ = stats.spearmanr(day[factor], day[fwd_col])
                if not np.isnan(ic):
                    daily_ics.append(ic)
            if daily_ics:
                print(f"    {yr}: IC={np.mean(daily_ics):+.4f}  "
                      f"IC+={np.mean(np.array(daily_ics)>0)*100:.0f}%  N={len(daily_ics)}")

    df.drop(columns=["year"], inplace=True)


# ═══════════════════════════════════════════════════════════════════
# L-S 驗證（通過因子）
# ═══════════════════════════════════════════════════════════════════
def test_longshort(df: pd.DataFrame, ic_df: pd.DataFrame) -> None:
    sig = ic_df[(ic_df.get("sig", False) == True) | (ic_df["p_bonf"] < 0.5)]
    if sig.empty:
        print(f"\n[L-S] 無足夠顯著因子，跳過")
        return

    print(f"\n{'='*90}")
    print(f"  Long-Short 驗證（Top 10% vs Bottom 10%）")
    print(f"{'='*90}")

    for _, r in sig.iterrows():
        factor = r["factor"]
        horizon = r["horizon"]
        h = int(horizon.replace("d", ""))
        fwd_col = f"fwd_{h}d"

        ls_spreads = []
        for d in sorted(df["date"].unique()):
            day = df.loc[df["date"] == d, [factor, fwd_col]].dropna()
            if len(day) < 50 or day[factor].nunique() < 3:
                continue
            day["rank"] = day[factor].rank(pct=True)
            top = day[day["rank"] >= 0.9][fwd_col]
            bot = day[day["rank"] <= 0.1][fwd_col]
            if len(top) < 3 or len(bot) < 3:
                continue
            ls_spreads.append(top.mean() - bot.mean())

        if len(ls_spreads) < 30:
            print(f"  {factor} ({horizon}): insufficient data")
            continue

        ls_arr = np.array(ls_spreads)
        mean_ls = np.mean(ls_arr) * 100
        ls_pos = np.mean(ls_arr > 0) * 100
        sharpe = np.mean(ls_arr) / np.std(ls_arr, ddof=1) if np.std(ls_arr) > 0 else 0

        verdict = "PASS" if mean_ls > 0.15 and ls_pos > 55 else "FAIL"
        print(f"  {factor:25s} ({horizon})  L-S={mean_ls:+.3f}%  "
              f"正比={ls_pos:.0f}%  Sharpe={sharpe:.2f}  {verdict}")


def main() -> None:
    print("=" * 90)
    print("  背離因子 (Divergence) Alpha 研究")
    print("=" * 90)

    df = load_and_prepare()

    # Layer 1: 連續型
    df = compute_continuous_factors(df)

    # Layer 2: 事件型
    print(f"\n[Layer 2] 背離事件偵測:")
    df = detect_divergence_events(df)

    # 截面 IC
    ic_df = test_continuous_ic(df)

    # 事件研究
    test_event_study(df)

    # 年度穩定性
    test_yearly_stability(df, ic_df)

    # L-S 驗證
    test_longshort(df, ic_df)

    # 結論
    print(f"\n{'='*90}")
    print(f"  研究結論")
    print(f"{'='*90}")
    sig = ic_df[ic_df.get("sig", False) == True]
    if not sig.empty:
        print(f"  {len(sig)} 個因子通過 Bonferroni:")
        for _, r in sig.iterrows():
            print(f"    {r['factor']:25s} {r['horizon']}  IC={r['ic']:+.4f}  "
                  f"p(Bonf)={r['p_bonf']:.5f}")
    else:
        print(f"  無因子通過 Bonferroni 校正")
        relaxed = ic_df[ic_df["p_bonf"] < 1.0].sort_values("p_bonf")
        if not relaxed.empty:
            print(f"  但有因子未校正 p < 0.05：")
            for _, r in relaxed.head(5).iterrows():
                print(f"    {r['factor']:25s} {r['horizon']}  IC={r['ic']:+.4f}  "
                      f"p(Bonf)={r['p_bonf']:.5f}")


if __name__ == "__main__":
    main()

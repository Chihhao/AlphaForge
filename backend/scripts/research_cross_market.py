"""
跨市場連動研究
==============
假說：美股（SPY/QQQ/SOX）前一交易日走勢能預測台股次日/未來 20 日報酬。
     因台股散戶多、外資同步交易，隔夜連動效應可能特別強。

研究分三部分：
  Part 1: 市場層級 — 美股隔夜 → 台股次日聚合報酬（相關性 + 回歸）
  Part 2: 橫截面因子 — 個股 US beta / interaction → cross-sectional IC
  Part 3: Partial IC — 確認與現有 11 因子不冗餘

使用: cd backend && ./.venv/bin/python scripts/research_cross_market.py
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

# 20d 主力維度
HOLD = 20
GAP = 1


# ═══════════════════════════════════════════════════════════════════════════════
# 資料載入
# ═══════════════════════════════════════════════════════════════════════════════

def load_tw_prices() -> pd.DataFrame:
    """載入台股價格"""
    print("載入台股價格 ...", flush=True)
    sql = text("""
        SELECT stock_id, date, close, volume
        FROM stock_prices
        WHERE date >= '2023-04-01' AND close > 0 AND volume > 0
        ORDER BY stock_id, date
    """)
    df = pd.read_sql(sql, engine)
    df["date"] = pd.to_datetime(df["date"])
    print(f"  {len(df):,} 筆 ({df['stock_id'].nunique()} 檔)")
    return df


def load_global_index() -> pd.DataFrame:
    """載入全球指數"""
    print("載入全球指數 ...", flush=True)
    sql = text("""
        SELECT index_id, date, close, change_pct
        FROM global_index
        ORDER BY index_id, date
    """)
    df = pd.read_sql(sql, engine)
    df["date"] = pd.to_datetime(df["date"])
    print(f"  {len(df):,} 筆 ({df['index_id'].nunique()} 個指數)")
    return df


def load_features() -> pd.DataFrame:
    """載入 stock_features（用於 partial IC）"""
    print("載入 stock_features ...", flush=True)
    cols = [
        "stock_id", "date", "roe", "yield_rate", "pb_ratio", "revenue_yoy",
        "rev_surprise", "rev_accel", "foreign_hold_chg_5d", "dealer_buy_20d",
        "vol_ratio", "ivol_20d", "trust_net_buy",
    ]
    col_str = ", ".join(cols)
    sql = text(f"""
        SELECT {col_str}
        FROM stock_features
        WHERE date >= '2023-06-01'
        ORDER BY stock_id, date
    """)
    df = pd.read_sql(sql, engine)
    df["date"] = pd.to_datetime(df["date"])
    print(f"  {len(df):,} 筆")
    return df


# ═══════════════════════════════════════════════════════════════════════════════
# 日期對齊：台股日期 T → 最近一個美股交易日（T 或之前）
# ═══════════════════════════════════════════════════════════════════════════════

def align_us_to_tw(tw_dates: pd.Series, us_df: pd.DataFrame) -> pd.DataFrame:
    """
    對於每個台股交易日，找到最近的美股交易日。
    美股 T-1 收盤 → 台股 T 開盤前已知。
    回傳 DataFrame: tw_date, us_date, sp500_ret, nasdaq_ret, sox_ret, vix_close, vix_chg, dxy_chg
    """
    # Pivot: index=date, columns=index_id
    pivot = us_df.pivot_table(index="date", columns="index_id", values="change_pct")
    close_pivot = us_df.pivot_table(index="date", columns="index_id", values="close")

    us_dates = sorted(pivot.index)
    tw_dates_unique = sorted(tw_dates.unique())

    mapping = []
    us_idx = 0
    for tw_d in tw_dates_unique:
        # 找到 < tw_d 的最近美股日期（美股前一天收盤）
        while us_idx < len(us_dates) - 1 and us_dates[us_idx + 1] < tw_d:
            us_idx += 1
        if us_dates[us_idx] >= tw_d:
            # 往回退到 < tw_d
            tmp = us_idx
            while tmp > 0 and us_dates[tmp] >= tw_d:
                tmp -= 1
            if us_dates[tmp] >= tw_d:
                continue  # 沒有更早的美股日
            us_idx = tmp

        us_d = us_dates[us_idx]
        row = {"tw_date": tw_d, "us_date": us_d}
        for idx_id in ["sp500", "nasdaq", "sox", "vix", "dxy"]:
            if idx_id in pivot.columns:
                row[f"{idx_id}_ret"] = pivot.loc[us_d, idx_id] if us_d in pivot.index else np.nan
            if idx_id in close_pivot.columns:
                row[f"{idx_id}_close"] = close_pivot.loc[us_d, idx_id] if us_d in close_pivot.index else np.nan
        mapping.append(row)

    return pd.DataFrame(mapping)


# ═══════════════════════════════════════════════════════════════════════════════
# Part 1: 市場層級測試
# ═══════════════════════════════════════════════════════════════════════════════

def part1_market_level(tw_df: pd.DataFrame, us_map: pd.DataFrame):
    """測試美股隔夜報酬 → 台股次日聚合報酬"""
    print("\n" + "=" * 70)
    print("Part 1: 市場層級 — 美股隔夜 → 台股次日聚合報酬")
    print("=" * 70)

    # 台股每日市場報酬（等權平均）
    tw_daily = tw_df.groupby("date").apply(
        lambda g: pd.Series({
            "tw_ret": g["ret"].mean(),
            "tw_ret_median": g["ret"].median(),
            "n_stocks": len(g),
        })
    ).reset_index()
    tw_daily.columns = ["date", "tw_ret", "tw_ret_median", "n_stocks"]

    # 合併
    merged = tw_daily.merge(
        us_map.rename(columns={"tw_date": "date"}),
        on="date", how="inner"
    )
    merged = merged.dropna(subset=["tw_ret", "sp500_ret"])
    print(f"\n合併後 {len(merged)} 個交易日")

    # 各指數 vs 台股次日
    us_signals = ["sp500_ret", "nasdaq_ret", "sox_ret", "vix_ret", "dxy_ret"]
    print(f"\n{'訊號':<15s} {'相關係數':>8s} {'p值':>10s} {'R²':>8s} {'上漲日%':>8s} {'下跌日%':>8s}")
    print("-" * 65)

    for sig in us_signals:
        if sig not in merged.columns:
            continue
        valid = merged[[sig, "tw_ret"]].dropna()
        if len(valid) < 30:
            continue

        r, p = stats.pearsonr(valid[sig], valid["tw_ret"])
        # 方向分析
        up_days = valid[valid[sig] > 0]
        dn_days = valid[valid[sig] < 0]
        up_tw = up_days["tw_ret"].mean() * 100 if len(up_days) > 0 else 0
        dn_tw = dn_days["tw_ret"].mean() * 100 if len(dn_days) > 0 else 0
        print(f"{sig:<15s} {r:>+8.4f} {p:>10.4f} {r**2:>8.4f} {up_tw:>+7.3f}% {dn_tw:>+7.3f}%")

    # 多日動量
    print(f"\n--- 美股多日動量 vs 台股次日 ---")
    for idx_id in ["sp500", "nasdaq", "sox"]:
        ret_col = f"{idx_id}_ret"
        if ret_col not in us_map.columns:
            continue

        # 從 us_map 計算 3d/5d 動量
        us_sorted = us_map.sort_values("tw_date").copy()
        for window in [3, 5]:
            col = f"{idx_id}_mom{window}d"
            us_sorted[col] = us_sorted[ret_col].rolling(window, min_periods=window).sum()

        merged2 = tw_daily.merge(
            us_sorted.rename(columns={"tw_date": "date"}),
            on="date", how="inner"
        )

        for window in [3, 5]:
            col = f"{idx_id}_mom{window}d"
            valid = merged2[[col, "tw_ret"]].dropna()
            if len(valid) < 30:
                continue
            r, p = stats.pearsonr(valid[col], valid["tw_ret"])
            print(f"  {col:<20s}  r={r:>+.4f}  p={p:.4f}")

    # VIX 水位分析
    print(f"\n--- VIX 水位 vs 台股報酬 ---")
    if "vix_close" in merged.columns:
        vix_valid = merged[["vix_close", "tw_ret"]].dropna()
        for q_low, q_high, label in [(0, 0.25, "低VIX"), (0.25, 0.75, "中VIX"), (0.75, 1.0, "高VIX")]:
            lo = vix_valid["vix_close"].quantile(q_low)
            hi = vix_valid["vix_close"].quantile(q_high)
            subset = vix_valid[(vix_valid["vix_close"] >= lo) & (vix_valid["vix_close"] < hi)]
            if len(subset) > 10:
                print(f"  {label} (VIX {lo:.1f}~{hi:.1f}): 台股均報酬 {subset['tw_ret'].mean()*100:+.3f}%, n={len(subset)}")


# ═══════════════════════════════════════════════════════════════════════════════
# Part 2: 橫截面因子構建
# ═══════════════════════════════════════════════════════════════════════════════

def compute_cross_sectional_factors(tw_df: pd.DataFrame, us_map: pd.DataFrame) -> pd.DataFrame:
    """
    為每檔股票每日構建跨市場因子：
    1. us_beta_60d: 個股對 SP500 的 60 日滾動 beta
    2. us_overnight_impact: sp500_ret × us_beta_60d
    3. sox_sensitivity: 個股對費半的 beta（科技股效應）
    4. vix_exposure: 個股對 VIX 變化的敏感度（防禦性指標）
    """
    print("\n" + "=" * 70)
    print("Part 2: 橫截面因子構建")
    print("=" * 70)

    # 合併美股訊號到台股
    tw = tw_df.merge(
        us_map.rename(columns={"tw_date": "date"}),
        on="date", how="left"
    )

    # --- Factor 1 & 2: US Beta ---
    print("計算 US beta (60d rolling) ...", flush=True)

    def rolling_beta(group: pd.DataFrame, us_col: str, window: int = 60) -> pd.Series:
        """滾動 OLS beta：stock_ret ~ us_ret"""
        stock_ret = group["ret"].values
        us_ret = group[us_col].values
        betas = np.full(len(stock_ret), np.nan)

        for i in range(window, len(stock_ret)):
            y = stock_ret[i - window:i]
            x = us_ret[i - window:i]
            mask = ~(np.isnan(y) | np.isnan(x))
            if mask.sum() < 20:
                continue
            x_m, y_m = x[mask], y[mask]
            cov = np.mean(x_m * y_m) - np.mean(x_m) * np.mean(y_m)
            var = np.mean(x_m ** 2) - np.mean(x_m) ** 2
            if var > 1e-10:
                betas[i] = cov / var
        return pd.Series(betas, index=group.index)

    factors_list = []

    for idx_id, beta_col in [("sp500", "us_beta_sp500"), ("sox", "us_beta_sox")]:
        ret_col = f"{idx_id}_ret"
        if ret_col not in tw.columns:
            continue

        tw[beta_col] = tw.groupby("stock_id", group_keys=False).apply(
            lambda g: rolling_beta(g, ret_col, 60)
        )
        factors_list.append(beta_col)
        valid = tw[beta_col].dropna()
        print(f"  {beta_col}: {len(valid):,} 筆, 均值={valid.mean():.3f}, std={valid.std():.3f}")

    # Interaction: sp500_ret * beta
    if "us_beta_sp500" in tw.columns:
        tw["us_overnight_impact"] = tw["sp500_ret"] * tw["us_beta_sp500"]
        factors_list.append("us_overnight_impact")

    # --- Factor 3: VIX regime interaction ---
    if "vix_close" in tw.columns:
        # 高 VIX → 偏好低 beta（防禦）
        vix_median = tw["vix_close"].median()
        tw["high_vix"] = (tw["vix_close"] > vix_median).astype(float)
        # neg_beta_in_high_vix: 高 VIX 時低 beta 有利
        tw["neg_beta_x_highvix"] = -tw.get("us_beta_sp500", 0) * tw["high_vix"]
        factors_list.append("neg_beta_x_highvix")

    # --- Factor 4: 美股動量 (market-level, 作為條件) ---
    us_sorted = us_map.sort_values("tw_date").copy()
    for w in [3, 5]:
        us_sorted[f"sp500_mom{w}d"] = us_sorted["sp500_ret"].rolling(w, min_periods=w).sum()
        factors_list.append(f"sp500_mom{w}d")
    tw = tw.merge(
        us_sorted[["tw_date", "sp500_mom3d", "sp500_mom5d"]].rename(columns={"tw_date": "date"}),
        on="date", how="left"
    )

    # --- Factor 5: VIX 變化率 ---
    if "vix_ret" in tw.columns:
        tw["neg_vix_chg"] = -tw["vix_ret"]  # VIX 下降 → 利多
        factors_list.append("neg_vix_chg")

    print(f"\n構建完成，共 {len(factors_list)} 個候選因子: {factors_list}")
    return tw, factors_list


def part2_cross_sectional_ic(tw_df: pd.DataFrame, factors: List[str]):
    """計算每個因子的 20d cross-sectional IC"""
    print("\n--- Cross-Sectional IC (20d forward return) ---")
    print(f"{'因子':<25s} {'IC':>8s} {'t':>8s} {'p':>8s} {'IC>0%':>8s} {'L-S%/mo':>10s}")
    print("-" * 75)

    # 計算 20d forward return
    tw_df = tw_df.sort_values(["stock_id", "date"])
    tw_df["fwd_ret_20d"] = tw_df.groupby("stock_id")["close"].transform(
        lambda x: x.shift(-HOLD - GAP + 1) / x.shift(-GAP + 1) - 1
    )

    dates = sorted(tw_df["date"].dropna().unique())
    results = []

    for factor in factors:
        if factor not in tw_df.columns:
            continue

        monthly_ics = []
        for d in dates:
            day_df = tw_df[(tw_df["date"] == d) & tw_df[factor].notna() & tw_df["fwd_ret_20d"].notna()]
            if len(day_df) < 30:
                continue
            ic, _ = stats.spearmanr(day_df[factor], day_df["fwd_ret_20d"])
            if not np.isnan(ic):
                monthly_ics.append(ic)

        if len(monthly_ics) < 20:
            continue

        ic_mean = np.mean(monthly_ics)
        ic_std = np.std(monthly_ics, ddof=1)
        t_stat = ic_mean / (ic_std / np.sqrt(len(monthly_ics))) if ic_std > 0 else 0
        p_val = 2 * (1 - stats.t.cdf(abs(t_stat), len(monthly_ics) - 1))
        pct_positive = np.mean([1 for ic in monthly_ics if ic > 0]) * 100

        # Long-Short: top/bottom quintile
        ls_rets = []
        for d in dates:
            day_df = tw_df[(tw_df["date"] == d) & tw_df[factor].notna() & tw_df["fwd_ret_20d"].notna()]
            if len(day_df) < 50:
                continue
            q20 = day_df[factor].quantile(0.2)
            q80 = day_df[factor].quantile(0.8)
            top = day_df[day_df[factor] >= q80]["fwd_ret_20d"].mean()
            bot = day_df[day_df[factor] <= q20]["fwd_ret_20d"].mean()
            if not np.isnan(top) and not np.isnan(bot):
                ls_rets.append(top - bot)

        ls_monthly = np.mean(ls_rets) * 100 if ls_rets else 0

        star = " ★★★" if abs(t_stat) > 2.0 else (" ★★" if abs(t_stat) > 1.5 else "")
        print(f"{factor:<25s} {ic_mean:>+8.4f} {t_stat:>8.2f} {p_val:>8.4f} {pct_positive:>7.1f}% {ls_monthly:>+9.3f}%{star}")
        results.append({
            "factor": factor,
            "ic": ic_mean,
            "t": t_stat,
            "p": p_val,
            "pct_pos": pct_positive,
            "ls_monthly": ls_monthly,
            "n_periods": len(monthly_ics),
        })

    return results


# ═══════════════════════════════════════════════════════════════════════════════
# Part 3: Partial IC（控制現有因子後的增量 IC）
# ═══════════════════════════════════════════════════════════════════════════════

def part3_partial_ic(tw_df: pd.DataFrame, feat_df: pd.DataFrame, top_factors: List[str]):
    """計算 partial IC：控制現有 11 因子後，新因子的增量預測力"""
    print("\n" + "=" * 70)
    print("Part 3: Partial IC — 控制現有因子後的增量")
    print("=" * 70)

    existing_factors = [
        "roe", "yield_rate", "pb_ratio", "revenue_yoy",
        "rev_surprise", "rev_accel", "foreign_hold_chg_5d", "dealer_buy_20d",
        "vol_ratio", "ivol_20d", "trust_net_buy",
    ]

    # 合併 features
    merged = tw_df.merge(feat_df, on=["stock_id", "date"], how="inner", suffixes=("", "_feat"))

    # 確保 fwd_ret 存在
    if "fwd_ret_20d" not in merged.columns:
        merged = merged.sort_values(["stock_id", "date"])
        merged["fwd_ret_20d"] = merged.groupby("stock_id")["close"].transform(
            lambda x: x.shift(-HOLD - GAP + 1) / x.shift(-GAP + 1) - 1
        )

    dates = sorted(merged["date"].dropna().unique())

    print(f"\n{'因子':<25s} {'Raw IC':>8s} {'Partial IC':>10s} {'保留率':>8s} {'Δt':>8s}")
    print("-" * 65)

    for factor in top_factors:
        if factor not in merged.columns:
            print(f"  {factor} 不在 merged 中，跳過")
            continue

        raw_ics = []
        partial_ics = []

        for d in dates:
            day = merged[(merged["date"] == d)].copy()
            day = day.dropna(subset=[factor, "fwd_ret_20d"] + existing_factors)
            if len(day) < 50:
                continue

            # Raw IC
            raw_ic, _ = stats.spearmanr(day[factor], day["fwd_ret_20d"])

            # Partial IC: 用 OLS 殘差
            from numpy.linalg import lstsq
            X = day[existing_factors].values
            X = np.column_stack([X, np.ones(len(X))])

            # 殘差 of factor
            y_f = day[factor].values
            coef_f, _, _, _ = lstsq(X, y_f, rcond=None)
            resid_f = y_f - X @ coef_f

            # 殘差 of fwd_ret
            y_r = day["fwd_ret_20d"].values
            coef_r, _, _, _ = lstsq(X, y_r, rcond=None)
            resid_r = y_r - X @ coef_r

            partial_ic, _ = stats.spearmanr(resid_f, resid_r)

            if not np.isnan(raw_ic):
                raw_ics.append(raw_ic)
            if not np.isnan(partial_ic):
                partial_ics.append(partial_ic)

        if len(raw_ics) < 20:
            print(f"  {factor}: 有效期數不足 ({len(raw_ics)})")
            continue

        raw_mean = np.mean(raw_ics)
        partial_mean = np.mean(partial_ics)
        retention = partial_mean / raw_mean * 100 if abs(raw_mean) > 1e-6 else 0
        partial_std = np.std(partial_ics, ddof=1)
        partial_t = partial_mean / (partial_std / np.sqrt(len(partial_ics))) if partial_std > 0 else 0

        star = " ★★★" if abs(partial_t) > 2.0 else (" ★★" if abs(partial_t) > 1.5 else "")
        print(f"{factor:<25s} {raw_mean:>+8.4f} {partial_mean:>+10.4f} {retention:>7.1f}% {partial_t:>+7.2f}{star}")


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    # 載入資料
    tw_df = load_tw_prices()
    us_df = load_global_index()
    feat_df = load_features()

    # 計算台股日報酬
    tw_df = tw_df.sort_values(["stock_id", "date"])
    tw_df["ret"] = tw_df.groupby("stock_id")["close"].pct_change()

    # 日期對齊
    print("\n日期對齊: 台股日期 → 最近美股交易日 ...", flush=True)
    tw_dates = tw_df["date"]
    us_map = align_us_to_tw(tw_dates, us_df)
    print(f"  對齊 {len(us_map)} 個台股交易日")

    # 顯示對齊樣本
    print("\n  日期對齊樣本:")
    sample = us_map.tail(5)
    for _, row in sample.iterrows():
        print(f"    台股 {row['tw_date'].strftime('%Y-%m-%d')} ← 美股 {row['us_date'].strftime('%Y-%m-%d')}"
              f"  SP500={row.get('sp500_ret', 0):+.3f}%")

    # Part 1: 市場層級
    part1_market_level(tw_df, us_map)

    # Part 2: 橫截面因子
    tw_df, factors = compute_cross_sectional_factors(tw_df, us_map)
    ic_results = part2_cross_sectional_ic(tw_df, factors)

    # Part 3: 對有潛力的因子做 Partial IC
    promising = [r["factor"] for r in ic_results if abs(r["t"]) > 1.0]
    if promising:
        part3_partial_ic(tw_df, feat_df, promising)
    else:
        print("\n沒有因子通過 |t| > 1.0 門檻，跳過 Partial IC")

    print("\n" + "=" * 70)
    print("研究完成！")
    print("=" * 70)


if __name__ == "__main__":
    main()

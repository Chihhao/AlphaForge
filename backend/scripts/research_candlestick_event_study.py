"""
K 線型態事件研究 (Event Study)

正確的測試方法：當型態出現時，後續 1d/2d/3d/5d/10d 的超額報酬是多少？
不是截面排序，而是事件觸發 → 條件平均報酬。

研究內容：
1. 各型態的無條件超額報酬（vs 同日市場平均）
2. 情境分組：趨勢（多頭/空頭）× 量能（放量/縮量）
3. 統計檢驗：t-test 檢驗超額報酬是否顯著異於零
4. 反向驗證：看漲型態出現後是漲還是跌？看跌型態呢？
"""
from __future__ import annotations

import os
import warnings
from typing import Dict, List

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

HORIZONS = [1, 2, 3, 5, 10]

# ECF v60 型態權重（僅作為參考分類）
BULLISH_PATTERNS = [
    "three_white_soldiers", "morning_star", "three_inside_up",
    "bullish_engulfing", "piercing_line", "hammer",
    "inverted_hammer", "dragonfly_doji",
]
BEARISH_PATTERNS = [
    "three_black_crows", "evening_star", "three_inside_down",
    "bearish_engulfing", "dark_cloud_cover", "shooting_star",
    "hanging_man", "gravestone_doji",
]
ALL_PATTERNS = BULLISH_PATTERNS + BEARISH_PATTERNS

PATTERN_LABELS: Dict[str, str] = {
    "three_white_soldiers": "紅三兵",
    "morning_star": "晨星",
    "three_inside_up": "三內升",
    "bullish_engulfing": "看漲吞噬",
    "piercing_line": "貫穿線",
    "hammer": "錘子線",
    "inverted_hammer": "倒錘子",
    "dragonfly_doji": "蜻蜓十字",
    "three_black_crows": "三隻烏鴉",
    "evening_star": "夜星",
    "three_inside_down": "三內降",
    "bearish_engulfing": "看跌吞噬",
    "dark_cloud_cover": "烏雲蓋頂",
    "shooting_star": "射擊之星",
    "hanging_man": "上吊線",
    "gravestone_doji": "墓碑十字",
}


# ═══════════════════════════════════════════════════════════════════
# 資料載入
# ═══════════════════════════════════════════════════════════════════
def load_data() -> pd.DataFrame:
    sql = text("""
        SELECT stock_id, date, open, high, low, close, volume
        FROM stock_prices
        WHERE date >= '2023-01-01' AND close > 0
        ORDER BY stock_id, date
    """)
    df = pd.read_sql(sql, engine)
    df["date"] = pd.to_datetime(df["date"])

    # 流動性過濾
    df["vol_ma20"] = df.groupby("stock_id")["volume"].transform(
        lambda x: x.rolling(20, min_periods=5).mean()
    )
    df = df[df["vol_ma20"] >= 500_000].copy()
    df = df[df["stock_id"].str.match(r"^[1-9]\d{3}$")].copy()

    # 量比
    df["vol_ratio"] = df["volume"] / df["vol_ma20"].replace(0, np.nan)

    # 均線與趨勢判斷
    grp = df.groupby("stock_id")
    df["ma20"] = grp["close"].transform(lambda x: x.rolling(20, min_periods=10).mean())
    df["ma60"] = grp["close"].transform(lambda x: x.rolling(60, min_periods=30).mean())
    df["above_ma20"] = (df["close"] > df["ma20"]).astype(int)
    df["trend_up"] = (df["ma20"] > df["ma60"]).astype(int)  # 多頭排列

    # 日報酬
    df["daily_ret"] = grp["close"].pct_change()

    # Forward return: 各天期
    for h in HORIZONS:
        entry = grp["close"].shift(-1)   # 隔日開盤（用收盤價近似）
        exit_ = grp["close"].shift(-(1 + h))
        df[f"fwd_{h}d"] = (exit_ - entry) / entry

    # 市場日均報酬（用來算超額報酬）
    for h in HORIZONS:
        col = f"fwd_{h}d"
        mkt = df.groupby("date")[col].transform("median")
        df[f"excess_{h}d"] = df[col] - mkt

    print(f"[Data] {len(df):,} 筆，"
          f"{df['date'].min().date()} ~ {df['date'].max().date()}，"
          f"{df['stock_id'].nunique()} 檔")
    return df


# ═══════════════════════════════════════════════════════════════════
# 型態偵測（複用上一個腳本的邏輯）
# ═══════════════════════════════════════════════════════════════════
def detect_patterns(df: pd.DataFrame) -> pd.DataFrame:
    grp = df.groupby("stock_id")

    prev1_open = grp["open"].shift(1)
    prev1_close = grp["close"].shift(1)
    prev1_high = grp["high"].shift(1)
    prev1_low = grp["low"].shift(1)
    prev2_open = grp["open"].shift(2)
    prev2_close = grp["close"].shift(2)
    prev2_high = grp["high"].shift(2)
    prev2_low = grp["low"].shift(2)

    body = (df["close"] - df["open"]).abs()
    range_ = df["high"] - df["low"]
    range_safe = range_.replace(0, np.nan)
    upper_shadow = df["high"] - df[["open", "close"]].max(axis=1)
    lower_shadow = df[["open", "close"]].min(axis=1) - df["low"]

    prev1_body = (prev1_close - prev1_open).abs()
    prev2_body = (prev2_close - prev2_open).abs()
    prev2_range = prev2_high - prev2_low

    is_red = df["close"] > df["open"]
    is_green = df["close"] < df["open"]
    prev1_red = prev1_close > prev1_open
    prev1_green = prev1_close < prev1_open
    prev2_red = prev2_close > prev2_open
    prev2_green = prev2_close < prev2_open

    body_ratio = body / range_safe
    upper_ratio = upper_shadow / range_safe
    lower_ratio = lower_shadow / range_safe

    # 單根
    df["hammer"] = (
        (body_ratio < 0.35) & (lower_shadow >= body * 2)
        & (upper_shadow < body * 0.5) & prev1_green
    ).astype(np.int8)

    df["inverted_hammer"] = (
        (body_ratio < 0.35) & (upper_shadow >= body * 2)
        & (lower_shadow < body * 0.5) & prev1_green
    ).astype(np.int8)

    df["hanging_man"] = (
        (body_ratio < 0.35) & (lower_shadow >= body * 2)
        & (upper_shadow < body * 0.5) & prev1_red
    ).astype(np.int8)

    df["shooting_star"] = (
        (body_ratio < 0.35) & (upper_shadow >= body * 2)
        & (lower_shadow < body * 0.5) & prev1_red
    ).astype(np.int8)

    df["dragonfly_doji"] = (
        (body_ratio < 0.1) & (lower_ratio > 0.6) & (upper_ratio < 0.1)
    ).astype(np.int8)

    df["gravestone_doji"] = (
        (body_ratio < 0.1) & (upper_ratio > 0.6) & (lower_ratio < 0.1)
    ).astype(np.int8)

    # 二根
    df["bullish_engulfing"] = (
        prev1_green & is_red
        & (df["open"] <= prev1_close) & (df["close"] >= prev1_open)
        & (body > prev1_body)
    ).astype(np.int8)

    df["bearish_engulfing"] = (
        prev1_red & is_green
        & (df["open"] >= prev1_close) & (df["close"] <= prev1_open)
        & (body > prev1_body)
    ).astype(np.int8)

    mid_prev1 = (prev1_open + prev1_close) / 2
    df["piercing_line"] = (
        prev1_green & is_red
        & (df["open"] < prev1_close) & (df["close"] > mid_prev1)
        & (df["close"] < prev1_open)
    ).astype(np.int8)

    df["dark_cloud_cover"] = (
        prev1_red & is_green
        & (df["open"] > prev1_close) & (df["close"] < mid_prev1)
        & (df["close"] > prev1_open)
    ).astype(np.int8)

    # 三根
    prev1_small = prev1_body < prev2_body * 0.3

    prev2_big_down = prev2_green & (prev2_body > prev2_range.replace(0, np.nan) * 0.5)
    df["morning_star"] = (
        prev2_big_down & prev1_small
        & is_red & (body > prev2_body * 0.5)
        & (df["close"] > (prev2_open + prev2_close) / 2)
    ).astype(np.int8)

    prev2_big_up = prev2_red & (prev2_body > prev2_range.replace(0, np.nan) * 0.5)
    df["evening_star"] = (
        prev2_big_up & prev1_small
        & is_green & (body > prev2_body * 0.5)
        & (df["close"] < (prev2_open + prev2_close) / 2)
    ).astype(np.int8)

    rising = (prev1_close > prev2_close) & (df["close"] > prev1_close)
    open_in1 = (prev1_open >= prev2_open) & (prev1_open <= prev2_close)
    open_in2 = (df["open"] >= prev1_open) & (df["open"] <= prev1_close)
    df["three_white_soldiers"] = (
        prev2_red & prev1_red & is_red & rising & open_in1 & open_in2
    ).astype(np.int8)

    falling = (prev1_close < prev2_close) & (df["close"] < prev1_close)
    open_in1b = (prev1_open <= prev2_open) & (prev1_open >= prev2_close)
    open_in2b = (df["open"] <= prev1_open) & (df["open"] >= prev1_close)
    df["three_black_crows"] = (
        prev2_green & prev1_green & is_green & falling & open_in1b & open_in2b
    ).astype(np.int8)

    first_big_down = prev2_green & (prev2_body > prev2_range.replace(0, np.nan) * 0.5)
    second_inside_up = prev1_red & (prev1_open > prev2_close) & (prev1_close < prev2_open)
    df["three_inside_up"] = (
        first_big_down & second_inside_up & is_red & (df["close"] > prev2_open)
    ).astype(np.int8)

    first_big_up = prev2_red & (prev2_body > prev2_range.replace(0, np.nan) * 0.5)
    second_inside_down = prev1_green & (prev1_open < prev2_close) & (prev1_close > prev2_open)
    df["three_inside_down"] = (
        first_big_up & second_inside_down & is_green & (df["close"] < prev2_open)
    ).astype(np.int8)

    total = sum(df[p].sum() for p in ALL_PATTERNS)
    print(f"[型態] 偵測完成，總事件 {total:,} 次")
    return df


# ═══════════════════════════════════════════════════════════════════
# 事件研究：無條件超額報酬
# ═══════════════════════════════════════════════════════════════════
def event_study_unconditional(df: pd.DataFrame) -> pd.DataFrame:
    """各型態出現後的平均超額報酬 + t-test"""
    rows = []
    for pattern in ALL_PATTERNS:
        events = df[df[pattern] == 1]
        n = len(events)
        if n < 30:
            rows.append({"pattern": pattern, "n_events": n, "skip": True})
            continue

        row = {
            "pattern": pattern,
            "label": PATTERN_LABELS[pattern],
            "type": "看漲" if pattern in BULLISH_PATTERNS else "看跌",
            "n_events": n,
            "skip": False,
        }

        for h in HORIZONS:
            excess = events[f"excess_{h}d"].dropna()
            if len(excess) < 20:
                row[f"ex_{h}d"] = np.nan
                row[f"p_{h}d"] = np.nan
                row[f"wr_{h}d"] = np.nan
                continue
            mean_ex = excess.mean() * 100
            t_stat, p_val = stats.ttest_1samp(excess, 0)
            win_rate = (excess > 0).mean() * 100

            row[f"ex_{h}d"] = round(mean_ex, 3)
            row[f"t_{h}d"] = round(float(t_stat), 2)
            row[f"p_{h}d"] = round(float(p_val), 4)
            row[f"wr_{h}d"] = round(win_rate, 1)

        rows.append(row)

    return pd.DataFrame(rows)


def print_unconditional(result: pd.DataFrame) -> None:
    valid = result[~result.get("skip", False)].copy()
    if valid.empty:
        print("(no results)")
        return

    print(f"\n{'='*100}")
    print(f"  事件研究：型態出現後的平均超額報酬（%）")
    print(f"  超額 = 個股報酬 - 當日市場中位數報酬")
    print(f"{'='*100}")

    for type_label, patterns in [("看漲型態", BULLISH_PATTERNS), ("看跌型態", BEARISH_PATTERNS)]:
        print(f"\n  【{type_label}】")
        print(f"  {'型態':<14s} {'N':>6s} | "
              f"{'1d%':>7s} {'2d%':>7s} {'3d%':>7s} {'5d%':>7s} {'10d%':>7s} | "
              f"{'5d勝率':>7s} {'5d p值':>8s}")
        print(f"  {'-'*90}")

        for p in patterns:
            r = valid[valid["pattern"] == p]
            if r.empty:
                continue
            r = r.iloc[0]
            stars = ""
            p5 = r.get(f"p_5d", np.nan)
            if not np.isnan(p5):
                if p5 < 0.001:
                    stars = "***"
                elif p5 < 0.01:
                    stars = "**"
                elif p5 < 0.05:
                    stars = "*"

            vals = []
            for h in HORIZONS:
                ex = r.get(f"ex_{h}d", np.nan)
                vals.append(f"{ex:>+7.3f}" if not np.isnan(ex) else f"{'N/A':>7s}")

            wr = r.get("wr_5d", np.nan)
            wr_s = f"{wr:>6.1f}%" if not np.isnan(wr) else f"{'N/A':>7s}"
            p5_s = f"{p5:>8.4f}" if not np.isnan(p5) else f"{'N/A':>8s}"

            print(f"  {r['label']:<14s} {r['n_events']:>6,} | "
                  f"{vals[0]} {vals[1]} {vals[2]} {vals[3]} {vals[4]} | "
                  f"{wr_s} {p5_s} {stars}")


# ═══════════════════════════════════════════════════════════════════
# 事件研究：情境分組（趨勢 × 量能）
# ═══════════════════════════════════════════════════════════════════
def event_study_conditional(df: pd.DataFrame) -> None:
    """分情境分析：趨勢（多頭/空頭）× 量能（放量/縮量）"""
    print(f"\n{'='*100}")
    print(f"  情境分組分析（5d 超額報酬）")
    print(f"  趨勢: MA20 > MA60（多頭）vs MA20 < MA60（空頭）")
    print(f"  量能: vol_ratio > 1.5（放量）vs vol_ratio <= 1.5（縮量）")
    print(f"{'='*100}")

    conditions = [
        ("多頭+放量", (df["trend_up"] == 1) & (df["vol_ratio"] > 1.5)),
        ("多頭+縮量", (df["trend_up"] == 1) & (df["vol_ratio"] <= 1.5)),
        ("空頭+放量", (df["trend_up"] == 0) & (df["vol_ratio"] > 1.5)),
        ("空頭+縮量", (df["trend_up"] == 0) & (df["vol_ratio"] <= 1.5)),
    ]

    # 只分析事件數較多的型態
    top_patterns = [p for p in ALL_PATTERNS if df[p].sum() >= 500]
    if not top_patterns:
        top_patterns = ALL_PATTERNS[:8]

    for pattern in top_patterns:
        events = df[df[pattern] == 1]
        if len(events) < 100:
            continue

        label = PATTERN_LABELS[pattern]
        ptype = "漲" if pattern in BULLISH_PATTERNS else "跌"
        print(f"\n  {label}（看{ptype}，N={len(events):,}）")
        print(f"  {'情境':<12s} {'N':>6s} {'5d超額%':>9s} {'勝率':>7s} {'p值':>8s} {'判定':>6s}")
        print(f"  {'-'*55}")

        for cond_name, cond_mask in conditions:
            subset = events[cond_mask]
            n = len(subset)
            if n < 20:
                print(f"  {cond_name:<12s} {n:>6} {'(樣本不足)':>30s}")
                continue

            excess = subset["excess_5d"].dropna()
            if len(excess) < 20:
                continue

            mean_ex = excess.mean() * 100
            t_stat, p_val = stats.ttest_1samp(excess, 0)
            wr = (excess > 0).mean() * 100

            sig = ""
            if p_val < 0.01:
                sig = "**"
            elif p_val < 0.05:
                sig = "*"

            verdict = ""
            if pattern in BULLISH_PATTERNS:
                if mean_ex > 0.3 and p_val < 0.05:
                    verdict = "有效"
                elif mean_ex < -0.3 and p_val < 0.05:
                    verdict = "反向!"
                else:
                    verdict = "—"
            else:
                if mean_ex < -0.3 and p_val < 0.05:
                    verdict = "有效"
                elif mean_ex > 0.3 and p_val < 0.05:
                    verdict = "反向!"
                else:
                    verdict = "—"

            print(f"  {cond_name:<12s} {n:>6} {mean_ex:>+9.3f} {wr:>6.1f}% "
                  f"{p_val:>8.4f} {verdict:>4s} {sig}")


# ═══════════════════════════════════════════════════════════════════
# 年度穩定性
# ═══════════════════════════════════════════════════════════════════
def yearly_stability(df: pd.DataFrame) -> None:
    """分年度看型態的超額報酬是否穩定"""
    print(f"\n{'='*100}")
    print(f"  分年度穩定性（5d 超額報酬 %）")
    print(f"{'='*100}")

    df["year"] = df["date"].dt.year
    years = sorted(df["year"].unique())

    # 只看事件數 > 500 的型態
    top_patterns = [p for p in ALL_PATTERNS if df[p].sum() >= 500]

    print(f"\n  {'型態':<14s}", end="")
    for yr in years:
        print(f" {yr:>12}", end="")
    print(f" {'全期':>12s}")
    print(f"  {'-'*(14 + 13 * (len(years) + 1))}")

    for pattern in top_patterns:
        label = PATTERN_LABELS[pattern]
        print(f"  {label:<14s}", end="")

        for yr in years:
            events = df[(df[pattern] == 1) & (df["year"] == yr)]
            excess = events["excess_5d"].dropna()
            if len(excess) < 10:
                print(f" {'—':>12s}", end="")
            else:
                mean_ex = excess.mean() * 100
                print(f" {mean_ex:>+11.3f}%", end="")

        # 全期
        events = df[df[pattern] == 1]
        excess = events["excess_5d"].dropna()
        mean_ex = excess.mean() * 100
        print(f" {mean_ex:>+11.3f}%")

    df.drop(columns=["year"], inplace=True)


# ═══════════════════════════════════════════════════════════════════
# 反向驗證摘要
# ═══════════════════════════════════════════════════════════════════
def reversal_summary(result: pd.DataFrame) -> None:
    """看漲型態是否真的漲？看跌型態是否真的跌？"""
    valid = result[~result.get("skip", False)].copy()
    if valid.empty:
        return

    print(f"\n{'='*100}")
    print(f"  反向驗證摘要：型態預測方向 vs 實際方向")
    print(f"{'='*100}")

    bull_correct = 0
    bull_total = 0
    bear_correct = 0
    bear_total = 0

    for _, r in valid.iterrows():
        ex5 = r.get("ex_5d", np.nan)
        p5 = r.get("p_5d", np.nan)
        if np.isnan(ex5):
            continue

        label = r["label"]
        is_bull = r["pattern"] in BULLISH_PATTERNS

        if is_bull:
            bull_total += 1
            direction = "符合" if ex5 > 0 else "反向"
            if ex5 > 0:
                bull_correct += 1
        else:
            bear_total += 1
            direction = "符合" if ex5 < 0 else "反向"
            if ex5 < 0:
                bear_correct += 1

        sig = "***" if p5 < 0.001 else "**" if p5 < 0.01 else "*" if p5 < 0.05 else ""
        print(f"  {label:<14s} ({r['type']}) → 5d超額: {ex5:>+.3f}%  "
              f"→ {direction}  {sig}")

    print(f"\n  看漲型態方向正確率: {bull_correct}/{bull_total}")
    print(f"  看跌型態方向正確率: {bear_correct}/{bear_total}")


# ═══════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════
def main() -> None:
    print("=" * 100)
    print("  K 線型態事件研究 (Event Study)")
    print("  方法：型態出現 → 後續 1d/2d/3d/5d/10d 超額報酬")
    print("=" * 100)

    df = load_data()
    df = detect_patterns(df)

    # 1. 無條件超額報酬
    result = event_study_unconditional(df)
    print_unconditional(result)

    # 2. 反向驗證
    reversal_summary(result)

    # 3. 情境分組
    event_study_conditional(df)

    # 4. 年度穩定性
    yearly_stability(df)

    # 最終判斷
    print(f"\n{'='*100}")
    print(f"  最終判斷")
    print(f"{'='*100}")

    # 找出 5d 超額報酬顯著的型態
    valid = result[~result.get("skip", False)].copy()
    sig_patterns = valid[valid["p_5d"] < 0.05] if "p_5d" in valid.columns else pd.DataFrame()

    if sig_patterns.empty:
        print("  無任何型態在 5d 超額報酬達到 p < 0.05 顯著水準")
    else:
        print(f"  {len(sig_patterns)} 個型態在 5d 超額報酬 p < 0.05：")
        for _, r in sig_patterns.iterrows():
            ex5 = r.get("ex_5d", 0)
            p5 = r.get("p_5d", 1)
            wr5 = r.get("wr_5d", 50)
            print(f"    {r['label']:<14s} ({r['type']})  "
                  f"5d超額={ex5:>+.3f}%  勝率={wr5:.1f}%  p={p5:.4f}  "
                  f"N={r['n_events']:,}")

    # 整體方向統計
    bull_rows = valid[valid["pattern"].isin(BULLISH_PATTERNS)]
    bear_rows = valid[valid["pattern"].isin(BEARISH_PATTERNS)]
    if "ex_5d" in valid.columns:
        bull_avg = bull_rows["ex_5d"].mean()
        bear_avg = bear_rows["ex_5d"].mean()
        print(f"\n  看漲型態平均 5d 超額: {bull_avg:+.3f}%")
        print(f"  看跌型態平均 5d 超額: {bear_avg:+.3f}%")
        if bull_avg < 0:
            print(f"  → 看漲型態整體為負超額（均值回歸效應）")
        if bear_avg > 0:
            print(f"  → 看跌型態整體為正超額（均值回歸效應）")


if __name__ == "__main__":
    main()

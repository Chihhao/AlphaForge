"""
研究：營收公布事件 alpha（PEAD 台股版）

假設：rev_surprise 的 alpha 集中在營收公布日附近，而非平均分散在整個月。
若成立 → 可在公布日後短期加碼，提升 alpha 捕捉效率。

方法：
1. 每月營收最晚次月 10 日公布 → announce_date = M+1 月 10 日
2. 找到公布日後最近的交易日作為 event_day (T+0)
3. 計算不同窗口的報酬：T-5, T-3, T-1 (洩漏), T+1, T+3, T+5, T+10, T+20
4. 按 rev_surprise 五分位分組 → 比較各窗口的 Q5-Q1 價差和 IC
5. 關鍵問題：alpha 是否集中在 T+0 ~ T+5？
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


# ── 數據載入 ─────────────────────────────────────────────────────────
def load_revenue() -> pd.DataFrame:
    sql = text("""
        SELECT stock_id, year, month, revenue, revenue_yoy, revenue_mom
        FROM stock_revenue_history
        WHERE revenue > 0
        ORDER BY stock_id, year, month
    """)
    df = pd.read_sql(sql, engine)

    # 正確公布日：M 月營收 → M+1 月 10 日
    next_month = df["month"] + 1
    next_year = df["year"] + (next_month > 12).astype(int)
    next_month = next_month.where(next_month <= 12, next_month - 12)
    df["announce_date"] = pd.to_datetime(
        next_year.astype(str)
        + "-"
        + next_month.astype(str).str.zfill(2)
        + "-10"
    )
    df = df.sort_values(["stock_id", "announce_date"]).reset_index(drop=True)
    return df


def compute_factors(rev: pd.DataFrame) -> pd.DataFrame:
    g = rev.groupby("stock_id")
    rev["rev_ma3"] = g["revenue"].transform(
        lambda x: x.rolling(3, min_periods=2).mean().shift(1)
    )
    rev["rev_surprise"] = (rev["revenue"] - rev["rev_ma3"]) / rev["rev_ma3"] * 100
    rev["rev_accel"] = g["revenue_yoy"].diff()
    return rev


def load_prices() -> pd.DataFrame:
    sql = text("""
        SELECT stock_id, date, close
        FROM stock_prices
        WHERE close > 0 AND date >= '2023-01-01'
        ORDER BY stock_id, date
    """)
    df = pd.read_sql(sql, engine)
    df["date"] = pd.to_datetime(df["date"])
    return df


# ── 事件配對 ─────────────────────────────────────────────────────────
def build_event_table(
    rev: pd.DataFrame, prices: pd.DataFrame
) -> pd.DataFrame:
    """對每個營收公布事件，配對最近交易日並計算多窗口報酬"""

    # 取得全市場交易日列表
    trade_dates = sorted(prices["date"].unique())
    td_arr = np.array(trade_dates)

    # 為每檔建立價格 lookup: stock_id → {date: close}
    price_map: Dict[str, pd.DataFrame] = {}
    for sid, grp in prices.groupby("stock_id"):
        g = grp.set_index("date")["close"].sort_index()
        price_map[sid] = g

    WINDOWS = [-5, -3, -1, 1, 3, 5, 10, 20]
    records: List[dict] = []

    for _, row in rev.iterrows():
        sid = row["stock_id"]
        ann = row["announce_date"]
        rs = row.get("rev_surprise")
        ra = row.get("rev_accel")

        if pd.isna(rs) or sid not in price_map:
            continue

        px = price_map[sid]

        # 找 announce_date 之後最近的交易日 (T+0)
        idx = np.searchsorted(td_arr, np.datetime64(ann))
        if idx >= len(td_arr):
            continue
        t0 = pd.Timestamp(td_arr[idx])

        # T+0 的收盤價
        if t0 not in px.index:
            continue
        p0 = px.loc[t0]

        rec = {
            "stock_id": sid,
            "announce_date": ann,
            "event_date": t0,
            "rev_surprise": rs,
            "rev_accel": ra,
            "revenue_yoy": row.get("revenue_yoy"),
            "close_t0": p0,
        }

        # 計算各窗口報酬
        t0_idx_in_px = px.index.get_loc(t0) if t0 in px.index else None
        if t0_idx_in_px is None:
            continue

        # 用整數索引取得 T+N 的收盤價
        px_vals = px.values
        px_dates = px.index

        for w in WINDOWS:
            target_pos = t0_idx_in_px + w
            if 0 <= target_pos < len(px_vals):
                pw = px_vals[target_pos]
                if w > 0:
                    # T+0 買入 → T+w 賣出
                    rec[f"ret_{w}d"] = (pw - p0) / p0
                else:
                    # T+w ~ T+0（公布前是否有洩漏）
                    rec[f"ret_{w}d"] = (p0 - pw) / pw
            else:
                rec[f"ret_{w}d"] = np.nan

        records.append(rec)

    return pd.DataFrame(records)


# ── 分析 ─────────────────────────────────────────────────────────────
def quintile_analysis(events: pd.DataFrame) -> None:
    """按 rev_surprise 五分位分析各窗口報酬"""

    # 每月排名（避免跨月比較）
    events["ym"] = events["event_date"].dt.to_period("M")
    events["rs_quintile"] = events.groupby("ym")["rev_surprise"].transform(
        lambda x: pd.qcut(x, 5, labels=[1, 2, 3, 4, 5], duplicates="drop")
    )
    events = events.dropna(subset=["rs_quintile"])
    events["rs_quintile"] = events["rs_quintile"].astype(int)

    windows = [-5, -3, -1, 1, 3, 5, 10, 20]
    ret_cols = [f"ret_{w}d" for w in windows]

    print(f"\n{'=' * 100}")
    print(f"  營收公布事件 Alpha 研究 (PEAD)")
    print(f"  事件數: {len(events):,}，期間: {events['event_date'].min().date()} ~ {events['event_date'].max().date()}")
    print(f"{'=' * 100}")

    # ── 1. 五分位平均報酬 ──
    print(f"\n  ── 五分位平均報酬 (%) ──")
    print(f"  {'Q':>4}", end="")
    for w in windows:
        label = f"T{w:+d}" if w != 0 else "T+0"
        print(f" {label:>8}", end="")
    print(f" {'筆數':>7}")
    print("  " + "─" * (6 + 9 * len(windows) + 8))

    q_means: Dict[int, Dict[str, float]] = {}
    for q in range(1, 6):
        qdf = events[events["rs_quintile"] == q]
        q_means[q] = {}
        label = f"Q{q}" + (" 低" if q == 1 else " 高" if q == 5 else "")
        print(f"  {label:>4}", end="")
        for w in windows:
            col = f"ret_{w}d"
            m = qdf[col].mean() * 100
            q_means[q][col] = m
            print(f" {m:>+8.2f}", end="")
        print(f" {len(qdf):>7,}")

    # Q5 - Q1 價差
    print("  " + "─" * (6 + 9 * len(windows) + 8))
    print(f"  {'Q5-Q1':>4}", end="")
    for w in windows:
        col = f"ret_{w}d"
        spread = q_means[5][col] - q_means[1][col]
        print(f" {spread:>+8.2f}", end="")
    print()

    # ── 2. 各窗口 IC ──
    print(f"\n  ── 各窗口 Rank IC (rev_surprise → return) ──")
    print(f"  {'窗口':>6} {'IC':>8} {'t-stat':>8} {'p-val':>8} {'|IC|':>8} {'解讀':>12}")
    print("  " + "─" * 62)

    ic_results: List[Tuple[int, float, float]] = []
    for w in windows:
        col = f"ret_{w}d"
        valid = events.dropna(subset=[col, "rev_surprise"])
        if len(valid) < 100:
            continue

        # 按月算 IC，再取平均（避免月份權重不均）
        monthly_ics = []
        for _, mgrp in valid.groupby("ym"):
            if len(mgrp) < 30:
                continue
            ic, _ = stats.spearmanr(mgrp["rev_surprise"], mgrp[col])
            if not np.isnan(ic):
                monthly_ics.append(ic)

        if not monthly_ics:
            continue

        avg_ic = np.mean(monthly_ics)
        std_ic = np.std(monthly_ics, ddof=1)
        n = len(monthly_ics)
        t_stat = avg_ic / (std_ic / np.sqrt(n)) if std_ic > 0 else 0
        p_val = 2 * (1 - stats.t.cdf(abs(t_stat), n - 1)) if n > 1 else 1.0

        label = f"T{w:+d}"
        if w < 0:
            interp = "洩漏?" if avg_ic > 0.02 else "無洩漏"
        elif w <= 5:
            interp = "★ 集中" if avg_ic > 0.03 else "分散"
        else:
            interp = "衰減" if avg_ic < ic_results[-1][1] * 0.7 else "持續"

        print(f"  {label:>6} {avg_ic:>+8.4f} {t_stat:>8.2f} {p_val:>8.4f} {abs(avg_ic):>8.4f} {interp:>12}")
        ic_results.append((w, avg_ic, t_stat))

    # ── 3. Alpha 集中度分析 ──
    print(f"\n  ── Alpha 集中度分析 ──")
    post_ics = [(w, ic) for w, ic, _ in ic_results if w > 0]
    if len(post_ics) >= 2:
        ic_5d = next((ic for w, ic in post_ics if w == 5), None)
        ic_20d = next((ic for w, ic in post_ics if w == 20), None)
        ic_1d = next((ic for w, ic in post_ics if w == 1), None)

        if ic_5d is not None and ic_20d is not None:
            ratio = ic_5d / ic_20d if ic_20d != 0 else float("inf")
            print(f"  IC(T+5) / IC(T+20) = {ic_5d:.4f} / {ic_20d:.4f} = {ratio:.2f}x")
            if ratio > 1.5:
                print(f"  → Alpha 明顯集中在公布後 5 天內 ★★★")
            elif ratio > 1.0:
                print(f"  → Alpha 在前 5 天略高，但持續到 20 天")
            else:
                print(f"  → Alpha 並非集中在事件附近，靜態因子即可")

        # Q5 的累積報酬曲線
        print(f"\n  ── Q5（高驚喜）累積報酬路徑 (%) ──")
        q5 = events[events["rs_quintile"] == 5]
        q1 = events[events["rs_quintile"] == 1]
        print(f"  {'窗口':>6} {'Q5(高)':>8} {'Q1(低)':>8} {'價差':>8} {'增量':>8}")
        print("  " + "─" * 42)
        prev_q5 = 0.0
        prev_q1 = 0.0
        for w in [1, 3, 5, 10, 20]:
            col = f"ret_{w}d"
            m5 = q5[col].mean() * 100
            m1 = q1[col].mean() * 100
            spread = m5 - m1
            # 和上個窗口比的增量
            incr = spread - (prev_q5 - prev_q1) if w > 1 else spread
            print(f"  T+{w:>3} {m5:>+8.2f} {m1:>+8.2f} {spread:>+8.2f} {incr:>+8.2f}")
            prev_q5 = m5
            prev_q1 = m1

    # ── 4. rev_accel 同樣分析 ──
    print(f"\n  ── rev_accel 各窗口 IC（對比）──")
    for w in windows:
        col = f"ret_{w}d"
        valid = events.dropna(subset=[col, "rev_accel"])
        monthly_ics = []
        for _, mgrp in valid.groupby("ym"):
            if len(mgrp) < 30:
                continue
            ic, _ = stats.spearmanr(mgrp["rev_accel"], mgrp[col])
            if not np.isnan(ic):
                monthly_ics.append(ic)
        if monthly_ics:
            avg_ic = np.mean(monthly_ics)
            label = f"T{w:+d}"
            print(f"  {label:>6} IC={avg_ic:>+.4f}")

    # ── 5. 結論 ──
    print(f"\n{'=' * 100}")
    print(f"  結論")
    print(f"{'=' * 100}")

    if post_ics:
        best_w, best_ic = max(post_ics, key=lambda x: x[1])
        worst_w, worst_ic = min(post_ics, key=lambda x: x[1])
        print(f"  最強窗口: T+{best_w} (IC={best_ic:+.4f})")
        print(f"  最弱窗口: T+{worst_w} (IC={worst_ic:+.4f})")
        print(f"  衰減比: IC(T+{worst_w})/IC(T+{best_w}) = {worst_ic/best_ic:.2f}")

        if best_w <= 5 and best_ic > worst_ic * 1.3:
            print(f"\n  ★ 建議：營收公布後 {best_w} 天內有顯著事件 alpha")
            print(f"    可設計 overlay 策略：公布日後短期加碼做多高 rev_surprise 股票")
            print(f"    與現有 20d 模型互補（靜態選股 + 事件加碼）")
        elif best_ic > 0.03:
            print(f"\n  ◎ rev_surprise alpha 持續性強，無需特別做 event timing")
            print(f"    現有 20d 模型的靜態使用方式已足夠")
        else:
            print(f"\n  ✗ rev_surprise 的事件 alpha 不顯著")
            print(f"    不建議追加 event-driven 策略")


def main() -> None:
    print("=== 營收公布事件 Alpha 研究 ===\n")

    print("Loading revenue data...")
    rev = load_revenue()
    rev = compute_factors(rev)
    print(f"  {len(rev):,} 筆營收 (含因子)")

    print("Loading price data...")
    prices = load_prices()
    print(f"  {len(prices):,} 筆價格")

    print("Building event table...")
    events = build_event_table(rev, prices)
    print(f"  {len(events):,} 個有效事件")

    quintile_analysis(events)


if __name__ == "__main__":
    main()

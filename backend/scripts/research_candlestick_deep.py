"""
K 線型態深度 Alpha 研究

多角度尋找短期(1d/2d/3d) alpha：
  A. 控制組：波動率匹配，排除 selection bias
  B. 差異分析：看漲 vs 看跌型態的超額差異
  C. 反向訊號：看跌型態 → 做多？（均值回歸）
  D. 前置跌幅條件：型態出現在連跌 N 天後
  E. 量能確認：型態日放量 vs 縮量
  F. 型態強度：大實體吞噬 vs 小實體吞噬
  G. 支撐位型態：型態出現在 MA20 附近
  H. 連續型態：多日連續出現看漲/看跌
  I. 1d 即時反轉：極端 K 棒後的隔日報酬
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

HORIZONS = [1, 2, 3, 5]
BULLISH = [
    "three_white_soldiers", "morning_star", "three_inside_up",
    "bullish_engulfing", "piercing_line", "hammer",
    "inverted_hammer", "dragonfly_doji",
]
BEARISH = [
    "three_black_crows", "evening_star", "three_inside_down",
    "bearish_engulfing", "dark_cloud_cover", "shooting_star",
    "hanging_man", "gravestone_doji",
]
ALL_PATTERNS = BULLISH + BEARISH

LABELS: Dict[str, str] = {
    "three_white_soldiers": "紅三兵", "morning_star": "晨星",
    "three_inside_up": "三內升", "bullish_engulfing": "看漲吞噬",
    "piercing_line": "貫穿線", "hammer": "錘子線",
    "inverted_hammer": "倒錘子", "dragonfly_doji": "蜻蜓十字",
    "three_black_crows": "三隻烏鴉", "evening_star": "夜星",
    "three_inside_down": "三內降", "bearish_engulfing": "看跌吞噬",
    "dark_cloud_cover": "烏雲蓋頂", "shooting_star": "射擊之星",
    "hanging_man": "上吊線", "gravestone_doji": "墓碑十字",
}


def _ttest(arr: np.ndarray) -> Tuple[float, float]:
    if len(arr) < 20:
        return np.nan, np.nan
    t, p = stats.ttest_1samp(arr, 0)
    return float(t), float(p)


def _stars(p: float) -> str:
    if np.isnan(p):
        return ""
    if p < 0.001:
        return "***"
    if p < 0.01:
        return "**"
    if p < 0.05:
        return "*"
    return ""


# ═══════════════════════════════════════════════════════════════════
# 資料載入 + 型態偵測 + 特徵工程
# ═══════════════════════════════════════════════════════════════════
def load_and_prepare() -> pd.DataFrame:
    sql = text("""
        SELECT stock_id, date, open, high, low, close, volume
        FROM stock_prices
        WHERE date >= '2023-01-01' AND close > 0
        ORDER BY stock_id, date
    """)
    df = pd.read_sql(sql, engine)
    df["date"] = pd.to_datetime(df["date"])

    grp = df.groupby("stock_id")

    # 流動性過濾
    df["vol_ma20"] = grp["volume"].transform(
        lambda x: x.rolling(20, min_periods=5).mean()
    )
    df = df[df["vol_ma20"] >= 500_000].copy()
    df = df[df["stock_id"].str.match(r"^[1-9]\d{3}$")].copy()

    grp = df.groupby("stock_id")

    # ─── 技術特徵 ─────────────────────────────────────────────────
    df["vol_ratio"] = df["volume"] / df["vol_ma20"].replace(0, np.nan)
    df["ma5"] = grp["close"].transform(lambda x: x.rolling(5, min_periods=3).mean())
    df["ma20"] = grp["close"].transform(lambda x: x.rolling(20, min_periods=10).mean())
    df["ma60"] = grp["close"].transform(lambda x: x.rolling(60, min_periods=30).mean())
    df["daily_ret"] = grp["close"].pct_change()

    # 波動率（20 日日報酬標準差）
    df["volatility"] = grp["daily_ret"].transform(
        lambda x: x.rolling(20, min_periods=10).std()
    )
    # 波動率五分位
    df["vol_quintile"] = df.groupby("date")["volatility"].transform(
        lambda x: pd.qcut(x, 5, labels=False, duplicates="drop")
    )

    # 前 N 日累積報酬（情境條件用）
    df["ret_3d"] = grp["close"].pct_change(3)
    df["ret_5d"] = grp["close"].pct_change(5)

    # 連跌天數
    df["down_day"] = (df["daily_ret"] < 0).astype(int)
    df["consec_down"] = grp["down_day"].transform(
        lambda x: x.groupby((x != x.shift()).cumsum()).cumsum()
    )
    # 連漲天數
    df["up_day"] = (df["daily_ret"] > 0).astype(int)
    df["consec_up"] = grp["up_day"].transform(
        lambda x: x.groupby((x != x.shift()).cumsum()).cumsum()
    )

    # 距 MA20 的距離
    df["dist_ma20"] = (df["close"] - df["ma20"]) / df["ma20"]
    # 在 MA20 附近（±3%）
    df["near_ma20"] = (df["dist_ma20"].abs() <= 0.03).astype(int)
    # 在 MA20 下方
    df["below_ma20"] = (df["close"] < df["ma20"]).astype(int)

    # 趨勢
    df["trend_up"] = (df["ma20"] > df["ma60"]).astype(int)

    # K 棒振幅（用於波動率匹配）
    df["range_pct"] = (df["high"] - df["low"]) / df["close"]

    # ─── Forward returns ─────────────────────────────────────────
    grp = df.groupby("stock_id")
    for h in HORIZONS:
        entry = grp["close"].shift(-1)
        exit_ = grp["close"].shift(-(1 + h))
        df[f"fwd_{h}d"] = (exit_ - entry) / entry

    # 市場日中位數（超額基準）
    for h in HORIZONS:
        col = f"fwd_{h}d"
        df[f"mkt_{h}d"] = df.groupby("date")[col].transform("median")
        df[f"excess_{h}d"] = df[col] - df[f"mkt_{h}d"]

    print(f"[Data] {len(df):,} 筆，{df['stock_id'].nunique()} 檔")

    # ─── 型態偵測 ─────────────────────────────────────────────────
    grp = df.groupby("stock_id")
    p1o, p1c, p1h, p1l = grp["open"].shift(1), grp["close"].shift(1), grp["high"].shift(1), grp["low"].shift(1)
    p2o, p2c, p2h, p2l = grp["open"].shift(2), grp["close"].shift(2), grp["high"].shift(2), grp["low"].shift(2)

    body = (df["close"] - df["open"]).abs()
    rng = df["high"] - df["low"]
    rng_s = rng.replace(0, np.nan)
    ushadow = df["high"] - df[["open", "close"]].max(axis=1)
    lshadow = df[["open", "close"]].min(axis=1) - df["low"]
    p1_body = (p1c - p1o).abs()
    p2_body = (p2c - p2o).abs()
    p2_rng = p2h - p2l

    is_r = df["close"] > df["open"]
    is_g = df["close"] < df["open"]
    p1r = p1c > p1o
    p1g = p1c < p1o
    p2r = p2c > p2o
    p2g = p2c < p2o

    br = body / rng_s
    ur = ushadow / rng_s
    lr = lshadow / rng_s

    # 單根
    df["hammer"] = ((br < 0.35) & (lshadow >= body * 2) & (ushadow < body * 0.5) & p1g).astype(np.int8)
    df["inverted_hammer"] = ((br < 0.35) & (ushadow >= body * 2) & (lshadow < body * 0.5) & p1g).astype(np.int8)
    df["hanging_man"] = ((br < 0.35) & (lshadow >= body * 2) & (ushadow < body * 0.5) & p1r).astype(np.int8)
    df["shooting_star"] = ((br < 0.35) & (ushadow >= body * 2) & (lshadow < body * 0.5) & p1r).astype(np.int8)
    df["dragonfly_doji"] = ((br < 0.1) & (lr > 0.6) & (ur < 0.1)).astype(np.int8)
    df["gravestone_doji"] = ((br < 0.1) & (ur > 0.6) & (lr < 0.1)).astype(np.int8)

    # 二根
    df["bullish_engulfing"] = (p1g & is_r & (df["open"] <= p1c) & (df["close"] >= p1o) & (body > p1_body)).astype(np.int8)
    df["bearish_engulfing"] = (p1r & is_g & (df["open"] >= p1c) & (df["close"] <= p1o) & (body > p1_body)).astype(np.int8)
    mid1 = (p1o + p1c) / 2
    df["piercing_line"] = (p1g & is_r & (df["open"] < p1c) & (df["close"] > mid1) & (df["close"] < p1o)).astype(np.int8)
    df["dark_cloud_cover"] = (p1r & is_g & (df["open"] > p1c) & (df["close"] < mid1) & (df["close"] > p1o)).astype(np.int8)

    # 三根
    p1_small = p1_body < p2_body * 0.3
    p2_big_down = p2g & (p2_body > p2_rng.replace(0, np.nan) * 0.5)
    df["morning_star"] = (p2_big_down & p1_small & is_r & (body > p2_body * 0.5) & (df["close"] > (p2o + p2c) / 2)).astype(np.int8)
    p2_big_up = p2r & (p2_body > p2_rng.replace(0, np.nan) * 0.5)
    df["evening_star"] = (p2_big_up & p1_small & is_g & (body > p2_body * 0.5) & (df["close"] < (p2o + p2c) / 2)).astype(np.int8)

    rising = (p1c > p2c) & (df["close"] > p1c)
    oi1 = (p1o >= p2o) & (p1o <= p2c)
    oi2 = (df["open"] >= p1o) & (df["open"] <= p1c)
    df["three_white_soldiers"] = (p2r & p1r & is_r & rising & oi1 & oi2).astype(np.int8)

    falling = (p1c < p2c) & (df["close"] < p1c)
    oi1b = (p1o <= p2o) & (p1o >= p2c)
    oi2b = (df["open"] <= p1o) & (df["open"] >= p1c)
    df["three_black_crows"] = (p2g & p1g & is_g & falling & oi1b & oi2b).astype(np.int8)

    fbd = p2g & (p2_body > p2_rng.replace(0, np.nan) * 0.5)
    siu = p1r & (p1o > p2c) & (p1c < p2o)
    df["three_inside_up"] = (fbd & siu & is_r & (df["close"] > p2o)).astype(np.int8)

    fbu = p2r & (p2_body > p2_rng.replace(0, np.nan) * 0.5)
    sid = p1g & (p1o < p2c) & (p1c > p2o)
    df["three_inside_down"] = (fbu & sid & is_g & (df["close"] < p2o)).astype(np.int8)

    # 合成標記
    df["any_bull"] = df[BULLISH].max(axis=1)
    df["any_bear"] = df[BEARISH].max(axis=1)
    df["any_pattern"] = (df["any_bull"] | df["any_bear"]).astype(int)
    df["bull_count"] = df[BULLISH].sum(axis=1)
    df["bear_count"] = df[BEARISH].sum(axis=1)

    # 型態日實體大小（強度）
    df["body_pct"] = (body / rng_s).fillna(1.0)

    total = df["any_pattern"].sum()
    print(f"[型態] 偵測完成，{total:,} 事件 ({total / len(df) * 100:.1f}%)")
    return df


# ═══════════════════════════════════════════════════════════════════
# 工具函數
# ═══════════════════════════════════════════════════════════════════
def _report(title: str, events: pd.DataFrame, label: str = "") -> None:
    """印出事件的各天期超額報酬"""
    n = len(events)
    if n < 20:
        return
    parts = [f"{label:35s} N={n:>6,} |"]
    for h in HORIZONS:
        ex = events[f"excess_{h}d"].dropna()
        if len(ex) < 20:
            parts.append(f" {h}d:  N/A  ")
            continue
        m = ex.mean() * 100
        _, p = _ttest(ex.values)
        parts.append(f" {h}d:{m:>+6.2f}%{_stars(p):3s}")
    wr1 = events["excess_1d"].dropna()
    wr_val = (wr1 > 0).mean() * 100 if len(wr1) >= 20 else np.nan
    parts.append(f"| 1d勝率:{wr_val:5.1f}%")
    print("  ".join(parts))


def _compare(title: str, group_a: pd.DataFrame, group_b: pd.DataFrame,
             label_a: str, label_b: str, horizon: int = 1) -> None:
    """比較兩組的超額報酬差異"""
    col = f"excess_{horizon}d"
    a = group_a[col].dropna().values
    b = group_b[col].dropna().values
    if len(a) < 30 or len(b) < 30:
        return
    diff = np.mean(a) - np.mean(b)
    t, p = stats.ttest_ind(a, b, equal_var=False)
    print(f"  {title}: {label_a}({len(a):,}) vs {label_b}({len(b):,}) → "
          f"差異={diff*100:+.3f}%  t={t:.2f}  p={p:.4f} {_stars(p)}")


# ═══════════════════════════════════════════════════════════════════
# A. 控制組：波動率匹配
# ═══════════════════════════════════════════════════════════════════
def test_A_control_group(df: pd.DataFrame) -> None:
    print(f"\n{'='*100}")
    print(f"  A. 控制組測試：排除波動率 selection bias")
    print(f"     比較同一波動率五分位中，有型態 vs 無型態的超額報酬")
    print(f"{'='*100}")

    for q in range(5):
        q_data = df[df["vol_quintile"] == q]
        pattern_events = q_data[q_data["any_pattern"] == 1]
        no_pattern = q_data[q_data["any_pattern"] == 0]

        label_p = f"Q{q+1}波動率 有型態"
        label_n = f"Q{q+1}波動率 無型態"
        _report("", pattern_events, label_p)
        _report("", no_pattern, label_n)
        _compare(f"  Q{q+1} 差異({HORIZONS[0]}d)", pattern_events, no_pattern,
                 "有型態", "無型態", HORIZONS[0])
        print()

    # 全體控制
    print("  --- 全體控制 ---")
    _report("", df[df["any_pattern"] == 1], "全體 有型態")
    _report("", df[df["any_pattern"] == 0], "全體 無型態")
    _compare("全體差異(1d)", df[df["any_pattern"] == 1],
             df[df["any_pattern"] == 0], "有型態", "無型態", 1)


# ═══════════════════════════════════════════════════════════════════
# B. 看漲 vs 看跌型態差異
# ═══════════════════════════════════════════════════════════════════
def test_B_bull_vs_bear(df: pd.DataFrame) -> None:
    print(f"\n{'='*100}")
    print(f"  B. 看漲 vs 看跌型態：超額報酬差異")
    print(f"     如果差異顯著 → 型態方向有區辨力")
    print(f"{'='*100}")

    bull_events = df[df["any_bull"] == 1]
    bear_events = df[df["any_bear"] == 1]

    _report("", bull_events, "看漲型態")
    _report("", bear_events, "看跌型態")

    for h in HORIZONS:
        _compare(f"  看漲 vs 看跌 ({h}d)", bull_events, bear_events,
                 "看漲", "看跌", h)


# ═══════════════════════════════════════════════════════════════════
# C. 反向訊號：看跌型態 → 做多
# ═══════════════════════════════════════════════════════════════════
def test_C_contrarian(df: pd.DataFrame) -> None:
    print(f"\n{'='*100}")
    print(f"  C. 反向訊號測試：看跌型態出現後做多的超額報酬")
    print(f"     波動率校正版（減去同波動率五分位的無型態報酬）")
    print(f"{'='*100}")

    for p in BEARISH:
        events = df[df[p] == 1]
        if len(events) < 50:
            continue

        # 波動率校正：計算同五分位無型態的平均超額
        corrected = {}
        for h in HORIZONS:
            col = f"excess_{h}d"
            adj_vals = []
            for q in range(5):
                q_events = events[events["vol_quintile"] == q][col].dropna()
                q_ctrl = df[(df["any_pattern"] == 0) & (df["vol_quintile"] == q)][col].dropna()
                if len(q_events) > 5 and len(q_ctrl) > 20:
                    adj = q_events.values - q_ctrl.mean()
                    adj_vals.extend(adj)
            corrected[h] = np.array(adj_vals)

        parts = [f"{LABELS[p]:<14s} N={len(events):>6,} |"]
        for h in HORIZONS:
            arr = corrected.get(h, np.array([]))
            if len(arr) < 20:
                parts.append(f" {h}d:  N/A  ")
                continue
            m = np.mean(arr) * 100
            _, pv = _ttest(arr)
            parts.append(f" {h}d:{m:>+6.2f}%{_stars(pv):3s}")
        print("  " + "  ".join(parts))


# ═══════════════════════════════════════════════════════════════════
# D. 前置跌幅條件：連跌後出現看漲型態
# ═══════════════════════════════════════════════════════════════════
def test_D_after_decline(df: pd.DataFrame) -> None:
    print(f"\n{'='*100}")
    print(f"  D. 連跌後型態：跌 N 天後出現看漲型態")
    print(f"     技術分析師看重的「底部反轉」場景")
    print(f"{'='*100}")

    for min_down in [2, 3, 5]:
        events = df[(df["any_bull"] == 1) & (df["consec_down"] >= min_down)]
        ctrl = df[(df["any_bull"] == 0) & (df["consec_down"] >= min_down)]
        _report("", events, f"連跌≥{min_down}日+看漲型態")
        _report("", ctrl, f"連跌≥{min_down}日+無型態  ")
        _compare(f"差異({HORIZONS[0]}d)", events, ctrl,
                 "有型態", "無型態", HORIZONS[0])
        print()

    # 同理：連漲後出現看跌型態
    print("  --- 連漲後看跌型態 ---")
    for min_up in [2, 3, 5]:
        events = df[(df["any_bear"] == 1) & (df["consec_up"] >= min_up)]
        ctrl = df[(df["any_bear"] == 0) & (df["consec_up"] >= min_up)]
        _report("", events, f"連漲≥{min_up}日+看跌型態")
        _report("", ctrl, f"連漲≥{min_up}日+無型態  ")
        _compare(f"差異({HORIZONS[0]}d)", events, ctrl,
                 "有型態", "無型態", HORIZONS[0])
        print()


# ═══════════════════════════════════════════════════════════════════
# E. 量能確認
# ═══════════════════════════════════════════════════════════════════
def test_E_volume_confirm(df: pd.DataFrame) -> None:
    print(f"\n{'='*100}")
    print(f"  E. 量能確認：型態日放量(vol_ratio>1.5) vs 縮量")
    print(f"{'='*100}")

    for ptype, plist, label in [("漲", BULLISH, "看漲"), ("跌", BEARISH, "看跌")]:
        events = df[df[[p for p in plist]].max(axis=1) == 1]
        high_vol = events[events["vol_ratio"] > 1.5]
        low_vol = events[events["vol_ratio"] <= 1.5]
        _report("", high_vol, f"{label}型態+放量")
        _report("", low_vol, f"{label}型態+縮量")
        _compare(f"{label} 放量 vs 縮量 (1d)", high_vol, low_vol,
                 "放量", "縮量", 1)
        print()


# ═══════════════════════════════════════════════════════════════════
# F. 型態強度：大實體 vs 小實體
# ═══════════════════════════════════════════════════════════════════
def test_F_pattern_strength(df: pd.DataFrame) -> None:
    print(f"\n{'='*100}")
    print(f"  F. 型態強度：吞噬型態的實體大小")
    print(f"     body_pct > 0.7（大實體）vs < 0.4（小實體）")
    print(f"{'='*100}")

    for p in ["bullish_engulfing", "bearish_engulfing"]:
        events = df[df[p] == 1]
        big = events[events["body_pct"] > 0.7]
        small = events[events["body_pct"] < 0.4]
        _report("", big, f"{LABELS[p]} 大實體")
        _report("", small, f"{LABELS[p]} 小實體")
        _compare(f"{LABELS[p]} 大 vs 小 (1d)", big, small, "大", "小", 1)
        print()


# ═══════════════════════════════════════════════════════════════════
# G. MA20 支撐位型態
# ═══════════════════════════════════════════════════════════════════
def test_G_support_level(df: pd.DataFrame) -> None:
    print(f"\n{'='*100}")
    print(f"  G. 支撐位型態：型態出現在 MA20 附近(±3%)")
    print(f"     特別看多頭趨勢中回測 MA20 後的看漲型態")
    print(f"{'='*100}")

    # 多頭趨勢 + 接近 MA20 + 看漲型態
    ideal_bull = df[
        (df["any_bull"] == 1)
        & (df["trend_up"] == 1)
        & (df["near_ma20"] == 1)
    ]
    ctrl_bull = df[
        (df["any_bull"] == 0)
        & (df["trend_up"] == 1)
        & (df["near_ma20"] == 1)
    ]
    _report("", ideal_bull, "多頭+MA20附近+看漲型態")
    _report("", ctrl_bull, "多頭+MA20附近+無型態  ")
    _compare("差異(1d)", ideal_bull, ctrl_bull, "有型態", "無型態", 1)
    _compare("差異(3d)", ideal_bull, ctrl_bull, "有型態", "無型態", 3)
    print()

    # 多頭趨勢 + 跌破 MA20 + 看漲型態（「買回」場景）
    buyback = df[
        (df["any_bull"] == 1)
        & (df["trend_up"] == 1)
        & (df["below_ma20"] == 1)
    ]
    ctrl_bb = df[
        (df["any_bull"] == 0)
        & (df["trend_up"] == 1)
        & (df["below_ma20"] == 1)
    ]
    _report("", buyback, "多頭+跌破MA20+看漲型態")
    _report("", ctrl_bb, "多頭+跌破MA20+無型態  ")
    _compare("差異(1d)", buyback, ctrl_bb, "有型態", "無型態", 1)
    _compare("差異(3d)", buyback, ctrl_bb, "有型態", "無型態", 3)
    print()

    # 空頭趨勢 + 接近 MA20 + 看跌型態（「壓力」場景）
    ideal_bear = df[
        (df["any_bear"] == 1)
        & (df["trend_up"] == 0)
        & (df["near_ma20"] == 1)
    ]
    ctrl_bear = df[
        (df["any_bear"] == 0)
        & (df["trend_up"] == 0)
        & (df["near_ma20"] == 1)
    ]
    _report("", ideal_bear, "空頭+MA20附近+看跌型態")
    _report("", ctrl_bear, "空頭+MA20附近+無型態  ")
    _compare("差異(1d)", ideal_bear, ctrl_bear, "有型態", "無型態", 1)


# ═══════════════════════════════════════════════════════════════════
# H. 5 日累積前跌幅 + 看漲型態（跌深反彈）
# ═══════════════════════════════════════════════════════════════════
def test_H_deep_decline_reversal(df: pd.DataFrame) -> None:
    print(f"\n{'='*100}")
    print(f"  H. 跌深反彈：5 日累積跌幅 + 看漲型態")
    print(f"{'='*100}")

    for threshold in [-0.05, -0.08, -0.10]:
        events = df[(df["any_bull"] == 1) & (df["ret_5d"] <= threshold)]
        ctrl = df[(df["any_bull"] == 0) & (df["ret_5d"] <= threshold)]
        pct = int(threshold * 100)
        _report("", events, f"5d跌≥{abs(pct)}%+看漲型態")
        _report("", ctrl, f"5d跌≥{abs(pct)}%+無型態  ")
        _compare(f"差異(1d)", events, ctrl, "有型態", "無型態", 1)
        _compare(f"差異(3d)", events, ctrl, "有型態", "無型態", 3)
        print()

    # 反面：5 日大漲後看跌型態
    print("  --- 漲多回檔：5 日大漲 + 看跌型態 ---")
    for threshold in [0.05, 0.08, 0.10]:
        events = df[(df["any_bear"] == 1) & (df["ret_5d"] >= threshold)]
        ctrl = df[(df["any_bear"] == 0) & (df["ret_5d"] >= threshold)]
        pct = int(threshold * 100)
        _report("", events, f"5d漲≥{pct}%+看跌型態")
        _report("", ctrl, f"5d漲≥{pct}%+無型態  ")
        _compare(f"差異(1d)", events, ctrl, "有型態", "無型態", 1)
        _compare(f"差異(3d)", events, ctrl, "有型態", "無型態", 3)
        print()


# ═══════════════════════════════════════════════════════════════════
# I. 各型態波動率校正後的個別分析
# ═══════════════════════════════════════════════════════════════════
def test_I_individual_corrected(df: pd.DataFrame) -> None:
    print(f"\n{'='*100}")
    print(f"  I. 各型態波動率校正後超額報酬（減去同五分位無型態均值）")
    print(f"     聚焦 1d/2d/3d")
    print(f"{'='*100}")

    # 先算各五分位 × 各天期的無型態基準
    baselines = {}
    for q in range(5):
        q_ctrl = df[(df["any_pattern"] == 0) & (df["vol_quintile"] == q)]
        for h in HORIZONS:
            baselines[(q, h)] = q_ctrl[f"excess_{h}d"].dropna().mean()

    for p in ALL_PATTERNS:
        events = df[df[p] == 1]
        n = len(events)
        if n < 50:
            continue

        parts = [f"{'[漲]' if p in BULLISH else '[跌]'} {LABELS[p]:<12s} N={n:>6,} |"]
        for h in HORIZONS:
            col = f"excess_{h}d"
            adj_vals = []
            for q in range(5):
                q_ev = events[events["vol_quintile"] == q][col].dropna()
                bl = baselines.get((q, h), 0)
                if len(q_ev) > 3:
                    adj_vals.extend((q_ev.values - bl).tolist())
            arr = np.array(adj_vals)
            if len(arr) < 20:
                parts.append(f" {h}d:  N/A  ")
                continue
            m = np.mean(arr) * 100
            _, pv = _ttest(arr)
            parts.append(f" {h}d:{m:>+6.2f}%{_stars(pv):3s}")
        print("  " + "  ".join(parts))


# ═══════════════════════════════════════════════════════════════════
# J. 極端 K 棒 1d 反轉
# ═══════════════════════════════════════════════════════════════════
def test_J_extreme_reversal(df: pd.DataFrame) -> None:
    print(f"\n{'='*100}")
    print(f"  J. 極端 K 棒後 1d 反轉")
    print(f"     日跌幅 < -5% 後隔日 / 日漲幅 > +5% 後隔日")
    print(f"{'='*100}")

    # 大跌後
    for thresh in [-0.03, -0.05, -0.07]:
        pct = int(thresh * 100)
        big_drop = df[df["daily_ret"] <= thresh]
        big_drop_bull = big_drop[big_drop["any_bull"] == 1]
        big_drop_none = big_drop[big_drop["any_pattern"] == 0]
        _report("", big_drop, f"日跌≥{abs(pct)}% 全體")
        _report("", big_drop_bull, f"日跌≥{abs(pct)}%+看漲型態")
        _report("", big_drop_none, f"日跌≥{abs(pct)}%+無型態  ")
        if len(big_drop_bull) >= 30 and len(big_drop_none) >= 30:
            _compare(f"差異(1d)", big_drop_bull, big_drop_none, "有型態", "無型態", 1)
        print()

    # 大漲後
    print("  --- 大漲後 ---")
    for thresh in [0.03, 0.05, 0.07]:
        pct = int(thresh * 100)
        big_up = df[df["daily_ret"] >= thresh]
        big_up_bear = big_up[big_up["any_bear"] == 1]
        big_up_none = big_up[big_up["any_pattern"] == 0]
        _report("", big_up, f"日漲≥{pct}% 全體")
        _report("", big_up_bear, f"日漲≥{pct}%+看跌型態")
        _report("", big_up_none, f"日漲≥{pct}%+無型態  ")
        if len(big_up_bear) >= 30 and len(big_up_none) >= 30:
            _compare(f"差異(1d)", big_up_bear, big_up_none, "有型態", "無型態", 1)
        print()


# ═══════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════
def main() -> None:
    print("=" * 100)
    print("  K 線型態深度 Alpha 研究（多角度，聚焦 1d/2d/3d）")
    print("=" * 100)

    df = load_and_prepare()

    test_A_control_group(df)
    test_B_bull_vs_bear(df)
    test_C_contrarian(df)
    test_D_after_decline(df)
    test_E_volume_confirm(df)
    test_F_pattern_strength(df)
    test_G_support_level(df)
    test_H_deep_decline_reversal(df)
    test_I_individual_corrected(df)
    test_J_extreme_reversal(df)

    print(f"\n{'='*100}")
    print(f"  研究完成 — 請根據各角度結果綜合判斷")
    print(f"{'='*100}")


if __name__ == "__main__":
    main()

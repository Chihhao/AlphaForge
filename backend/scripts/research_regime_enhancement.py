"""
Regime Filter 增強研究

目標：把 MaxDD 從 -33% 降到 -15% 以內

方法：
1. 下載 VIX、NASDAQ、USD/TWD、SOX 歷史數據
2. 檢驗這些指標是否能提前偵測 2025-03 等級的崩盤
3. 測試多指標 regime filter 組合
4. Walk-forward 驗證改善效果

關鍵事件回顧（需要 regime filter 攔截的月份）：
- 2024-07: Baseline -6.04%（台股大跌）
- 2024-12: Baseline -1.51%
- 2025-03: Baseline -24.62%（最嚴重，必須攔截）
- 2025-09: Baseline -0.53%
- 2025-10: Baseline -1.58%
- 2026-01: Baseline -2.45%
"""
from __future__ import annotations

import os
import warnings
from datetime import datetime, timedelta

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


# ── 下載全球指標 ──────────────────────────────────────────────────────
def download_global_data() -> pd.DataFrame:
    """用 yfinance 下載 VIX, NASDAQ, SOX, USD/TWD"""
    import yfinance as yf

    tickers = {
        "^VIX": "vix",
        "^IXIC": "nasdaq",
        "^SOX": "sox",
        "TWD=X": "usdtwd",  # USD/TWD
    }

    frames = []
    for ticker, name in tickers.items():
        print(f"  Downloading {ticker} ({name})...")
        try:
            data = yf.download(ticker, start="2023-01-01", end="2026-04-10",
                               progress=False, auto_adjust=True)
            if data.empty:
                print(f"    WARNING: empty data for {ticker}")
                continue
            # yfinance 回傳的可能是 MultiIndex
            if isinstance(data.columns, pd.MultiIndex):
                data.columns = data.columns.get_level_values(0)
            s = data["Close"].rename(name)
            frames.append(s)
            print(f"    {len(s)} rows, {s.index[0].date()} ~ {s.index[-1].date()}")
        except Exception as e:
            print(f"    ERROR: {e}")

    if not frames:
        raise RuntimeError("No global data downloaded")

    gdf = pd.concat(frames, axis=1)
    gdf.index = pd.to_datetime(gdf.index)
    # forward fill holidays
    gdf = gdf.ffill()
    return gdf


def load_tw_market() -> pd.DataFrame:
    """載入 0050 和大盤數據"""
    sql = text("""
        SELECT date, stock_id, close
        FROM stock_prices
        WHERE stock_id IN ('0050', '2330')
          AND close > 0 AND date >= '2023-01-01'
        ORDER BY date
    """)
    df = pd.read_sql(sql, engine)
    df["date"] = pd.to_datetime(df["date"])

    pivot = df.pivot_table(index="date", columns="stock_id", values="close")
    pivot.columns = [f"tw_{c}" for c in pivot.columns]
    return pivot


def load_strategy_returns() -> pd.DataFrame:
    """載入現有 20d 策略的逐月報酬（用 stock_features 重建）"""
    # 簡化：用 0050 的月度報酬作為台股 proxy
    sql = text("""
        SELECT date, close FROM stock_prices
        WHERE stock_id = '0050' AND close > 0 AND date >= '2023-01-01'
        ORDER BY date
    """)
    df = pd.read_sql(sql, engine)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")["close"]
    # 月度報酬
    monthly = df.resample("M").last().pct_change().dropna()
    monthly.name = "tw_monthly_ret"
    return monthly


# ── 指標計算 ──────────────────────────────────────────────────────────
def compute_indicators(gdf: pd.DataFrame, twdf: pd.DataFrame) -> pd.DataFrame:
    """計算各種 regime 指標"""
    # 合併
    df = gdf.join(twdf, how="outer").ffill()

    # VIX 指標
    df["vix_ma20"] = df["vix"].rolling(20).mean()
    df["vix_above_20"] = (df["vix"] > 20).astype(int)
    df["vix_above_25"] = (df["vix"] > 25).astype(int)
    df["vix_above_30"] = (df["vix"] > 30).astype(int)
    df["vix_spike"] = (df["vix"] > df["vix_ma20"] * 1.3).astype(int)

    # NASDAQ 趨勢
    df["nasdaq_ma20"] = df["nasdaq"].rolling(20).mean()
    df["nasdaq_ma60"] = df["nasdaq"].rolling(60).mean()
    df["nasdaq_above_ma20"] = (df["nasdaq"] > df["nasdaq_ma20"]).astype(int)
    df["nasdaq_above_ma60"] = (df["nasdaq"] > df["nasdaq_ma60"]).astype(int)
    df["nasdaq_ret_20d"] = df["nasdaq"].pct_change(20)

    # SOX（半導體指數）趨勢
    if "sox" in df.columns:
        df["sox_ma20"] = df["sox"].rolling(20).mean()
        df["sox_above_ma20"] = (df["sox"] > df["sox_ma20"]).astype(int)
        df["sox_ret_20d"] = df["sox"].pct_change(20)

    # USD/TWD（台幣貶值 = 外資撤退）
    if "usdtwd" in df.columns:
        df["usdtwd_ma20"] = df["usdtwd"].rolling(20).mean()
        df["twd_weakening"] = (df["usdtwd"] > df["usdtwd_ma20"]).astype(int)
        df["usdtwd_chg_20d"] = df["usdtwd"].pct_change(20)

    # 0050 指標（現有 regime filter 的基礎）
    if "tw_0050" in df.columns:
        df["tw0050_ma20"] = df["tw_0050"].rolling(20).mean()
        df["tw0050_above_ma20"] = (df["tw_0050"] > df["tw0050_ma20"]).astype(int)
        df["tw0050_ret_20d"] = df["tw_0050"].pct_change(20)

    return df


# ── 分析 ──────────────────────────────────────────────────────────────
def analyze_crash_signals(df: pd.DataFrame) -> None:
    """分析每個崩盤事件前，各指標的狀態"""

    # 定義崩盤月份（從 Baseline_20d walk-forward 結果）
    crash_months = {
        "2024-07": -6.04,
        "2024-12": -1.51,
        "2025-01": -0.51,  # 其實只是小虧
        "2025-03": -24.62,  # 最嚴重
        "2025-09": -0.53,
        "2025-10": -1.58,
        "2026-01": -2.45,
    }

    # 好的月份
    good_months = {
        "2024-01": +8.30,
        "2024-05": +8.04,
        "2024-06": +9.13,
        "2025-04": +13.77,
        "2025-08": +6.35,
    }

    indicators = [
        ("vix", "VIX 水準"),
        ("vix_above_20", "VIX > 20"),
        ("vix_above_25", "VIX > 25"),
        ("vix_spike", "VIX 飆升(>MA20*1.3)"),
        ("nasdaq_above_ma20", "NASDAQ > MA20"),
        ("nasdaq_above_ma60", "NASDAQ > MA60"),
        ("nasdaq_ret_20d", "NASDAQ 20d 報酬"),
        ("tw0050_above_ma20", "0050 > MA20 (現有)"),
        ("tw0050_ret_20d", "0050 20d 報酬"),
    ]

    if "sox_above_ma20" in df.columns:
        indicators.append(("sox_above_ma20", "SOX > MA20"))
        indicators.append(("sox_ret_20d", "SOX 20d 報酬"))
    if "twd_weakening" in df.columns:
        indicators.append(("twd_weakening", "台幣走弱"))
        indicators.append(("usdtwd_chg_20d", "USD/TWD 20d 變化"))

    print(f"\n{'=' * 130}")
    print(f"  崩盤事件前各指標狀態（進場日 = 每月 11 日）")
    print(f"{'=' * 130}")

    # 取每月 11 日（或最近交易日）的指標值
    def get_value_at(indicator: str, year: int, month: int) -> float:
        target = pd.Timestamp(year, month, 11)
        # 找 target 前最近的日期
        valid = df.index[df.index <= target]
        if valid.empty:
            return np.nan
        nearest = valid[-1]
        return df.loc[nearest, indicator] if indicator in df.columns else np.nan

    all_events = {**{k: (v, "CRASH") for k, v in crash_months.items()},
                  **{k: (v, "GOOD") for k, v in good_months.items()}}

    print(f"\n  {'月份':>8} {'報酬':>7} {'類型':>6}", end="")
    for _, label in indicators:
        short = label[:10]
        print(f" {short:>11}", end="")
    print()
    print("  " + "─" * (24 + 12 * len(indicators)))

    for month_str in sorted(all_events.keys()):
        ret, event_type = all_events[month_str]
        y, m = int(month_str[:4]), int(month_str[5:7])

        color = "🔴" if event_type == "CRASH" else "🟢"
        print(f"  {month_str:>8} {ret:>+6.1f}% {color:>4}", end="")

        for ind, _ in indicators:
            val = get_value_at(ind, y, m)
            if np.isnan(val):
                print(f" {'N/A':>11}", end="")
            elif isinstance(val, (int, np.integer)) or val in (0, 1):
                print(f" {'✓' if val else '✗':>11}", end="")
            elif abs(val) < 1:
                print(f" {val:>+11.3f}", end="")
            else:
                print(f" {val:>11.1f}", end="")
        print()

    # ── 各指標的「崩盤預警」效果 ──
    print(f"\n{'=' * 130}")
    print(f"  各指標做 Regime Filter 的效果")
    print(f"{'=' * 130}")

    # 用 0050 的月度報酬作為台股 proxy
    if "tw_0050" not in df.columns:
        print("  (No 0050 data)")
        return

    # 建立月度報酬
    monthly_close = df["tw_0050"].resample("M").last().dropna()
    monthly_ret = monthly_close.pct_change().dropna()

    # 取每月初（11日）的指標值
    regime_indicators = [
        ("tw0050_above_ma20", "0050>MA20 (現有)", lambda x: x == 1),
        ("nasdaq_above_ma20", "NASDAQ>MA20", lambda x: x == 1),
        ("nasdaq_above_ma60", "NASDAQ>MA60", lambda x: x == 1),
        ("vix_above_20", "VIX<20", lambda x: x == 0),  # VIX < 20 才做多
        ("vix_above_25", "VIX<25", lambda x: x == 0),
        ("vix_spike", "VIX不飆升", lambda x: x == 0),
    ]
    if "sox_above_ma20" in df.columns:
        regime_indicators.append(("sox_above_ma20", "SOX>MA20", lambda x: x == 1))
    if "twd_weakening" in df.columns:
        regime_indicators.append(("twd_weakening", "台幣不弱", lambda x: x == 0))

    print(f"\n  {'指標':>20} {'開啟月數':>8} {'月均報酬':>8} {'勝率':>6}"
          f" {'Sharpe':>8} {'MaxDD':>8} {'避開最大跌':>10}")
    print("  " + "─" * 80)

    # Baseline: 每月都做
    n_all = len(monthly_ret)
    avg_all = monthly_ret.mean() * 100
    wr_all = (monthly_ret > 0).mean()
    sh_all = monthly_ret.mean() / monthly_ret.std() * np.sqrt(12) if monthly_ret.std() > 0 else 0
    cum_all = (1 + monthly_ret).cumprod()
    dd_all = ((cum_all - cum_all.cummax()) / cum_all.cummax()).min() * 100
    print(f"  {'(無filter)':>20} {n_all:>8} {avg_all:>+8.2f} {wr_all:>5.0%}"
          f" {sh_all:>8.2f} {dd_all:>7.1f}%")

    # 0050>MA20 baseline
    for ind, label, condition in regime_indicators:
        monthly_signals = []
        for dt in monthly_ret.index:
            # 取該月 11 日的指標
            target = dt.replace(day=11) if dt.day >= 11 else (dt - pd.DateOffset(months=1)).replace(day=11)
            # 更精確：用月初的值
            month_start = dt.replace(day=1)
            valid = df.index[(df.index >= month_start - pd.Timedelta(days=5)) & (df.index <= dt)]
            if valid.empty or ind not in df.columns:
                monthly_signals.append(np.nan)
                continue
            val = df.loc[valid[-1], ind]
            monthly_signals.append(1 if condition(val) else 0)

        signals = pd.Series(monthly_signals, index=monthly_ret.index)
        active = monthly_ret[signals == 1].dropna()

        if len(active) < 3:
            continue

        n = len(active)
        avg = active.mean() * 100
        wr = (active > 0).mean()
        sh = active.mean() / active.std() * np.sqrt(12) if active.std() > 0 else 0
        cum = (1 + active).cumprod()
        dd = ((cum - cum.cummax()) / cum.cummax()).min() * 100

        # 檢查是否避開了 2025-03
        avoided_2503 = "✓" if signals.get(pd.Timestamp("2025-03-31"), 1) == 0 else "✗"

        print(f"  {label:>20} {n:>8} {avg:>+8.2f} {wr:>5.0%}"
              f" {sh:>8.2f} {dd:>7.1f}% {avoided_2503:>10}")

    # ── 組合 Regime Filter ──
    print(f"\n  ── 組合 Regime Filter ──")
    combos = [
        ("0050>MA20 + NASDAQ>MA20",
         ["tw0050_above_ma20", "nasdaq_above_ma20"],
         [lambda x: x == 1, lambda x: x == 1]),
        ("0050>MA20 + VIX<25",
         ["tw0050_above_ma20", "vix_above_25"],
         [lambda x: x == 1, lambda x: x == 0]),
        ("0050>MA20 + NASDAQ>MA20 + VIX<25",
         ["tw0050_above_ma20", "nasdaq_above_ma20", "vix_above_25"],
         [lambda x: x == 1, lambda x: x == 1, lambda x: x == 0]),
        ("NASDAQ>MA60 + VIX<25",
         ["nasdaq_above_ma60", "vix_above_25"],
         [lambda x: x == 1, lambda x: x == 0]),
    ]
    if "sox_above_ma20" in df.columns:
        combos.append(
            ("0050>MA20 + SOX>MA20 + VIX<25",
             ["tw0050_above_ma20", "sox_above_ma20", "vix_above_25"],
             [lambda x: x == 1, lambda x: x == 1, lambda x: x == 0])
        )

    print(f"\n  {'組合':>40} {'開啟':>5} {'月均':>7} {'勝率':>5}"
          f" {'Sharpe':>7} {'MaxDD':>7} {'避2503':>7}")
    print("  " + "─" * 85)

    for name, inds, conditions in combos:
        monthly_signals = []
        for dt in monthly_ret.index:
            month_start = dt.replace(day=1)
            valid = df.index[(df.index >= month_start - pd.Timedelta(days=5)) & (df.index <= dt)]
            if valid.empty:
                monthly_signals.append(np.nan)
                continue

            all_pass = True
            for ind, cond in zip(inds, conditions):
                if ind not in df.columns:
                    all_pass = False
                    break
                val = df.loc[valid[-1], ind]
                if not cond(val):
                    all_pass = False
                    break

            monthly_signals.append(1 if all_pass else 0)

        signals = pd.Series(monthly_signals, index=monthly_ret.index)
        active = monthly_ret[signals == 1].dropna()

        if len(active) < 3:
            continue

        n = len(active)
        avg = active.mean() * 100
        wr = (active > 0).mean()
        sh = active.mean() / active.std() * np.sqrt(12) if active.std() > 0 else 0
        cum = (1 + active).cumprod()
        dd = ((cum - cum.cummax()) / cum.cummax()).min() * 100
        avoided_2503 = "✓" if signals.get(pd.Timestamp("2025-03-31"), 1) == 0 else "✗"

        print(f"  {name:>40} {n:>5} {avg:>+6.2f}% {wr:>4.0%}"
              f" {sh:>7.2f} {dd:>6.1f}% {avoided_2503:>7}")

    print(f"\n{'=' * 130}")
    print(f"  結論")
    print(f"{'=' * 130}")
    print(f"  目標：MaxDD > -15%, 同時不犧牲太多開啟月數")
    print(f"  如果有組合能避開 2025-03 且 MaxDD < 15%，就值得採用")


def main() -> None:
    print("=== Regime Filter 增強研究 ===\n")

    print("下載全球指標...")
    gdf = download_global_data()

    print("\n載入台股數據...")
    twdf = load_tw_market()

    print("\n計算指標...")
    df = compute_indicators(gdf, twdf)
    print(f"  {len(df)} 天，{df.index[0].date()} ~ {df.index[-1].date()}")

    analyze_crash_signals(df)


if __name__ == "__main__":
    main()

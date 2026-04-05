"""
美股連動短線 Alpha 研究

假設：美股前一日表現影響台股隔日走勢。
測試因子：
1. S&P500 前日漲跌幅
2. NASDAQ 前日漲跌幅
3. 費半(SOX) 前日漲跌幅
4. VIX 前日變化
5. 美股與台股的連動差（某日美股大漲但台股沒跟 → 補漲機會）
6. 分群：電子股對費半敏感，傳產對 S&P 敏感

用法：直接跑，從 yfinance 抓美股歷史，與台股 stock_features 合併分析。
"""
from __future__ import annotations
import os, warnings
import numpy as np
import pandas as pd
from scipy import stats
from sqlalchemy import create_engine, text

warnings.filterwarnings("ignore")
PG_URL = os.getenv("PG_URL", "postgresql://alphaforge:alphaforge_secret@10.0.4.3:5433/alphaforge")
engine = create_engine(PG_URL)


def load_us_data() -> pd.DataFrame:
    """從 yfinance 抓美股指數歷史"""
    import yfinance as yf

    tickers = {
        "^GSPC": "sp500",     # S&P 500
        "^IXIC": "nasdaq",    # NASDAQ
        "^SOX": "sox",        # 費城半導體
        "^VIX": "vix",        # VIX
    }

    frames = []
    for ticker, name in tickers.items():
        print(f"  Fetching {name} ({ticker})...")
        data = yf.download(ticker, start="2023-06-01", progress=False)
        if data.empty:
            continue
        # yfinance 可能回傳 MultiIndex columns
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)
        s = data["Close"].pct_change() * 100
        s.name = f"{name}_ret"
        frames.append(s)

    us = pd.concat(frames, axis=1)
    us.index = pd.to_datetime(us.index)
    # VIX 用變化量而非報酬率
    if "vix_ret" in us.columns:
        us["vix_chg"] = us["vix_ret"]  # VIX 的 pct_change 就是變化率
    return us


def load_tw_data() -> pd.DataFrame:
    """載入台股 features + forward returns"""
    sql = text("""
        SELECT stock_id, date, close, change_pct, vol_ratio,
               foreign_net_buy, ivol_20d, roe, pb_ratio,
               sector_rs, ma20, ma60
        FROM stock_features
        WHERE close > 0 AND date >= '2023-06-01'
        ORDER BY date, stock_id
    """)
    df = pd.read_sql(sql, engine)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["stock_id", "date"])

    for hold in [5, 10]:
        entry = df.groupby("stock_id")["close"].shift(-1)
        exit_ = df.groupby("stock_id")["close"].shift(-(1 + hold))
        df[f"fwd_{hold}d"] = (exit_ - entry) / entry

    # 個股類別（用 stock_id 前兩碼粗分）
    # 2xxx=電子, 1xxx=水泥/食品/塑膠, 3xxx=電子, 4xxx=電子, 5xxx=電子, 6xxx=電子/生技
    df["is_tech"] = df["stock_id"].str[:1].isin(["2", "3", "4", "5", "6"]).astype(int)

    return df


def merge_data(tw: pd.DataFrame, us: pd.DataFrame) -> pd.DataFrame:
    """合併美股與台股：美股 T-1 日對應台股 T 日"""
    # 台股交易日列表
    tw_dates = sorted(tw["date"].unique())

    # 建立台股日期 → 前一美股交易日的映射
    us_dates = sorted(us.index)
    date_map = {}
    for td in tw_dates:
        # 找 td 之前最近的美股交易日
        prev_us = [d for d in us_dates if d < td]
        if prev_us:
            date_map[td] = prev_us[-1]

    # 建立 lookup
    rows = []
    for tw_date, us_date in date_map.items():
        if us_date in us.index:
            row = us.loc[us_date].to_dict()
            row["tw_date"] = tw_date
            rows.append(row)

    us_mapped = pd.DataFrame(rows)
    if us_mapped.empty:
        return tw

    tw = tw.merge(us_mapped, left_on="date", right_on="tw_date", how="left")
    return tw


def analyze_signal(df: pd.DataFrame, signal_col: str, hold: int,
                    direction: str = "top", quantile: float = 0.2,
                    subset_col: str = None, subset_val: int = None) -> list:
    """分析美股訊號對台股的預測力"""
    fwd_col = f"fwd_{hold}d"
    months = sorted(df["ym"].unique())
    results = []

    for ym in months:
        mdata = df[df["ym"] == ym]
        dates = sorted(mdata["date"].unique())
        daily_excess = []

        for d in dates:
            dd = mdata[mdata["date"] == d].dropna(subset=[signal_col, fwd_col])
            if subset_col and subset_val is not None:
                dd = dd[dd[subset_col] == subset_val]
            if len(dd) < 30:
                continue

            mkt_ret = dd[fwd_col].mean()

            if direction == "top":
                thr = dd[signal_col].quantile(1 - quantile)
                selected = dd[dd[signal_col] >= thr]
            elif direction == "bot":
                thr = dd[signal_col].quantile(quantile)
                selected = dd[dd[signal_col] <= thr]
            elif direction == "all":
                selected = dd
            else:
                continue

            if len(selected) < 5:
                continue

            daily_excess.append(selected[fwd_col].mean() - mkt_ret)

        if daily_excess:
            results.append({
                "ym": str(ym),
                "excess": np.mean(daily_excess),
                "n_days": len(daily_excess),
            })

    return results


def main():
    print("=" * 80)
    print("  美股連動短線 Alpha 研究")
    print("=" * 80)

    us = load_us_data()
    print(f"  US data: {us.index.min().date()} ~ {us.index.max().date()}")

    tw = load_tw_data()
    print(f"  TW data: {len(tw):,} rows")

    df = merge_data(tw, us)
    df["ym"] = df["date"].dt.to_period("M")
    print(f"  Merged: {len(df):,} rows\n")

    # 檢查美股資料覆蓋率
    for col in ["sp500_ret", "nasdaq_ret", "sox_ret", "vix_chg"]:
        if col in df.columns:
            n = df[col].notna().sum()
            print(f"  {col}: {n:,} non-null ({n/len(df)*100:.0f}%)")
    print()

    # ═══════════════════════════════════════════════════════
    # 分析 1：美股大漲/大跌日，台股全體隔日表現
    # ═══════════════════════════════════════════════════════
    print("=" * 80)
    print("  分析 1：美股前日漲跌 vs 台股隔日全體報酬")
    print("=" * 80)

    for us_col, us_name in [("sp500_ret", "S&P500"), ("nasdaq_ret", "NASDAQ"), ("sox_ret", "費半")]:
        if us_col not in df.columns:
            continue
        # 取每日一筆（市場層級）
        daily = df.groupby("date").agg(
            tw_ret_5d=("fwd_5d", "mean"),
            tw_ret_10d=("fwd_10d", "mean"),
            us_ret=(us_col, "first"),
        ).dropna()

        if len(daily) < 50:
            continue

        # 相關性
        corr_5, p5 = stats.spearmanr(daily["us_ret"], daily["tw_ret_5d"])
        corr_10, p10 = stats.spearmanr(daily["us_ret"], daily["tw_ret_10d"])

        # 分組
        daily["us_group"] = pd.cut(daily["us_ret"], bins=[-999, -1, 0, 1, 999],
                                    labels=["大跌(<-1%)", "小跌", "小漲", "大漲(>1%)"])
        grp = daily.groupby("us_group")[["tw_ret_5d", "tw_ret_10d"]].agg(["mean", "count"])

        print(f"\n  {us_name}:")
        print(f"    Spearman 相關: 5d={corr_5:.3f}(p={p5:.3f}), 10d={corr_10:.3f}(p={p10:.3f})")
        print(f"    {'美股分組':>15} {'N':>5} {'台股5d':>10} {'台股10d':>10}")
        for idx, row in grp.iterrows():
            n = int(row[("tw_ret_5d", "count")])
            r5 = row[("tw_ret_5d", "mean")] * 100
            r10 = row[("tw_ret_10d", "mean")] * 100
            print(f"    {str(idx):>15} {n:>5} {r5:>+9.2f}% {r10:>+9.2f}%")

    # ═══════════════════════════════════════════════════════
    # 分析 2：美股訊號 × 個股特徵 交互作用
    # ═══════════════════════════════════════════════════════
    print(f"\n{'=' * 80}")
    print("  分析 2：美股大跌後，哪類台股反彈最強？")
    print("=" * 80)

    if "sox_ret" in df.columns:
        # 費半大跌日（<-1.5%）
        df["sox_crash"] = (df["sox_ret"].fillna(0) < -1.5).astype(int)

        for hold in [5, 10]:
            fwd_col = f"fwd_{hold}d"
            crash_days = df[df["sox_crash"] == 1]
            normal_days = df[df["sox_crash"] == 0]

            if len(crash_days) < 100:
                continue

            # 電子 vs 非電子
            tech_crash = crash_days[crash_days["is_tech"] == 1][fwd_col].mean() * 100
            non_tech_crash = crash_days[crash_days["is_tech"] == 0][fwd_col].mean() * 100
            tech_normal = normal_days[normal_days["is_tech"] == 1][fwd_col].mean() * 100
            non_tech_normal = normal_days[normal_days["is_tech"] == 0][fwd_col].mean() * 100

            print(f"\n  費半大跌日（<-1.5%）後 {hold}d:")
            print(f"    電子股: 大跌後={tech_crash:+.2f}%, 正常日={tech_normal:+.2f}%, 差異={tech_crash-tech_normal:+.2f}%")
            print(f"    非電子: 大跌後={non_tech_crash:+.2f}%, 正常日={non_tech_normal:+.2f}%, 差異={non_tech_crash-non_tech_normal:+.2f}%")

    # ═══════════════════════════════════════════════════════
    # 分析 3：美股連動因子的截面預測力
    # ═══════════════════════════════════════════════════════
    print(f"\n{'=' * 80}")
    print("  分析 3：美股訊號作為因子的截面預測力（IC）")
    print("=" * 80)

    # 構造交互因子：個股 beta × 美股報酬
    # 用過去20日個股報酬與費半報酬的相關性作為 beta 代理
    if "sox_ret" in df.columns:
        # 個股對費半的敏感度 = 過去20日 change_pct 與 sox_ret 的協方差
        df["stock_sox_sensitivity"] = df.groupby("stock_id").apply(
            lambda g: g["change_pct"].rolling(20).corr(g["sox_ret"])
        ).reset_index(level=0, drop=True)

        # 交互因子：敏感度 × 美股報酬（美股漲時買高 beta，跌時買低 beta）
        df["sox_interaction"] = df["stock_sox_sensitivity"] * df["sox_ret"]

        for hold in [5, 10]:
            fwd_col = f"fwd_{hold}d"
            months = sorted(df["ym"].unique())
            ics = []
            for ym in months:
                mdata = df[df["ym"] == ym]
                for d in sorted(mdata["date"].unique()):
                    dd = mdata[mdata["date"] == d].dropna(subset=["sox_interaction", fwd_col])
                    if len(dd) < 50:
                        continue
                    ic, _ = stats.spearmanr(dd["sox_interaction"], dd[fwd_col])
                    if not np.isnan(ic):
                        ics.append(ic)

            if ics:
                avg_ic = np.mean(ics)
                ic_pos = np.mean([1 for x in ics if x > 0])
                t, p = stats.ttest_1samp(ics, 0)
                marker = " ★★" if avg_ic > 0.01 and p < 0.05 else (" ★" if avg_ic > 0.005 else "")
                print(f"  費半交互因子 → {hold}d: IC={avg_ic:+.4f}, IC正={ic_pos:.0%}, t={t:.2f}, p={p:.4f}{marker}")

    # VIX 變化作為 timing
    if "vix_chg" in df.columns:
        for hold in [5, 10]:
            fwd_col = f"fwd_{hold}d"
            daily = df.groupby("date").agg(
                tw_ret=(fwd_col, "mean"),
                vix=(("vix_chg"), "first"),
            ).dropna()

            # VIX 大漲（恐慌）後台股表現
            vix_spike = daily[daily["vix"] > 10]
            vix_normal = daily[daily["vix"] <= 10]
            if len(vix_spike) >= 5:
                print(f"  VIX暴漲(>10%)後 {hold}d: 台股={vix_spike['tw_ret'].mean()*100:+.2f}% (N={len(vix_spike)}), 正常={vix_normal['tw_ret'].mean()*100:+.2f}%")

    # ═══════════════════════════════════════════════════════
    # 分析 4：可操作的訊號測試
    # ═══════════════════════════════════════════════════════
    print(f"\n{'=' * 80}")
    print("  分析 4：可操作的美股連動訊號")
    print("=" * 80)

    if "sox_ret" in df.columns:
        # 策略：費半前日大跌 → 隔日買台股電子股 Top20%（按外資買超排序）
        for hold in [5, 10]:
            fwd_col = f"fwd_{hold}d"
            crash_mask = df["sox_ret"].fillna(0) < -1.5
            crash_tech = df[crash_mask & (df["is_tech"] == 1)].copy()

            if len(crash_tech) < 100:
                continue

            # 在大跌日，按外資買超排序取 Top20%
            daily_rets = []
            daily_mkts = []
            for d in sorted(crash_tech["date"].unique()):
                dd = crash_tech[crash_tech["date"] == d].dropna(subset=["foreign_net_buy", fwd_col])
                if len(dd) < 20:
                    continue
                top = dd.nlargest(max(len(dd) // 5, 5), "foreign_net_buy")
                daily_rets.append(top[fwd_col].mean())
                daily_mkts.append(dd[fwd_col].mean())

            if daily_rets:
                avg = np.mean(daily_rets) * 100
                mkt = np.mean(daily_mkts) * 100
                excess = avg - mkt
                n = len(daily_rets)
                wr = np.mean([1 for r in daily_rets if r > 0]) * 100
                print(f"\n  費半大跌→買外資買超電子Top20% ({hold}d):")
                print(f"    報酬={avg:+.2f}%, 市場={mkt:+.2f}%, 超額={excess:+.2f}%, 勝率={wr:.0f}%, N={n}天")

        # 策略：VIX 暴漲 → 隔日買低波動股
        if "vix_chg" in df.columns:
            for hold in [5, 10]:
                fwd_col = f"fwd_{hold}d"
                vix_spike_mask = df["vix_chg"].fillna(0) > 10
                spike_data = df[vix_spike_mask].copy()

                if len(spike_data) < 50:
                    continue

                daily_rets = []
                daily_mkts = []
                for d in sorted(spike_data["date"].unique()):
                    dd = spike_data[spike_data["date"] == d].dropna(subset=["ivol_20d", fwd_col])
                    if len(dd) < 20:
                        continue
                    # 買低波動股
                    low_vol = dd.nsmallest(max(len(dd) // 5, 5), "ivol_20d")
                    daily_rets.append(low_vol[fwd_col].mean())
                    daily_mkts.append(dd[fwd_col].mean())

                if daily_rets:
                    avg = np.mean(daily_rets) * 100
                    mkt = np.mean(daily_mkts) * 100
                    excess = avg - mkt
                    n = len(daily_rets)
                    print(f"\n  VIX暴漲→買低波動股 ({hold}d):")
                    print(f"    報酬={avg:+.2f}%, 市場={mkt:+.2f}%, 超額={excess:+.2f}%, N={n}天")

    print(f"\n{'=' * 80}")
    print("  完成")
    print("=" * 80)


if __name__ == "__main__":
    main()

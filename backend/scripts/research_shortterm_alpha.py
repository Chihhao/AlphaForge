"""
5d / 10d 短線 Alpha 研究：全新方法

之前失敗的原因：用 20d 的慢因子（基本面+籌碼水位）預測短線，沒有預測力。
本次嘗試完全不同的訊號類型：

Track 1: 法人動能突變（外資/投信單日買超 vs 5日均量的比值）
Track 2: 量價背離（放量不漲 = 出貨，縮量不跌 = 吸籌）
Track 3: 極端反轉（RSI2<5 且 bias5<-5% 的超跌反彈）
Track 4: 籌碼轉折（外資從連賣轉買的第一天）
Track 5: 波動率收縮後突破（ivol_20d 低 + 今日量比>2）
Track 6: 純截面動量（過去 5 日漲幅排名 → 預測未來 5/10 日）

每個 Track 用簡單的條件篩選，不用 ML 模型。
先確認訊號本身有沒有 alpha，有的話再考慮用 ML 加強。
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


def load_data() -> pd.DataFrame:
    sql = text("""
        SELECT stock_id, date, close, volume, change_pct,
               rsi2, rsi14, bias5, bias10, bias20, bb_pctb, vol_ratio,
               k, d, macd_osc,
               foreign_net_buy, trust_net_buy, dealer_net_buy,
               foreign_buy_5d, trust_buy_5d, dealer_buy_5d,
               foreign_hold_chg_5d, ivol_20d, atr_pct,
               roe, yield_rate, pb_ratio, revenue_yoy,
               ma5, ma10, ma20, ma60, price_vs_high20
        FROM stock_features
        WHERE close > 0 AND date >= '2023-06-01'
        ORDER BY date, stock_id
    """)
    print("  Loading...")
    df = pd.read_sql(sql, engine)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["stock_id", "date"])

    # 衍生特徵
    # 法人買超相對量（今日 vs 5日均）
    df["foreign_surge"] = df["foreign_net_buy"] / (df["foreign_buy_5d"].abs() / 5 + 1)
    df["trust_surge"] = df["trust_net_buy"] / (df["trust_buy_5d"].abs() / 5 + 1)

    # 過去 N 日報酬
    df["ret5"] = df.groupby("stock_id")["close"].pct_change(5) * 100
    df["ret3"] = df.groupby("stock_id")["close"].pct_change(3) * 100
    df["ret1"] = df["change_pct"]

    # 量價背離：放量（vol_ratio>1.5）但漲跌幅小（|change_pct|<1%）
    df["vol_price_div"] = ((df["vol_ratio"] > 1.5) & (df["change_pct"].abs() < 1)).astype(int)

    # 外資轉折：昨天賣今天買（或反過來）
    df["foreign_prev"] = df.groupby("stock_id")["foreign_net_buy"].shift(1)
    df["foreign_reversal_buy"] = ((df["foreign_prev"] < 0) & (df["foreign_net_buy"] > 0)).astype(int)
    df["foreign_reversal_sell"] = ((df["foreign_prev"] > 0) & (df["foreign_net_buy"] < 0)).astype(int)

    # 波動率收縮 + 量能爆發
    df["low_vol_breakout"] = ((df["ivol_20d"] < df.groupby("date")["ivol_20d"].transform("median")) &
                               (df["vol_ratio"] > 2)).astype(int)

    # Forward returns
    for hold in [5, 10]:
        gap = 1
        entry = df.groupby("stock_id")["close"].shift(-gap)
        exit_ = df.groupby("stock_id")["close"].shift(-(gap + hold))
        df[f"fwd_{hold}d"] = (exit_ - entry) / entry

    df["ym"] = df["date"].dt.to_period("M")
    return df


def evaluate_signal(df: pd.DataFrame, signal_col: str, hold: int,
                     condition: str = "top", quantile: float = 0.1,
                     min_stocks: int = 5) -> dict:
    """
    評估某個訊號的預測力。
    condition: "top"=取最高分, "bot"=取最低分, "flag"=布林值為True
    """
    fwd_col = f"fwd_{hold}d"
    results = []

    months = sorted(df["ym"].unique())
    for ym in months:
        day_data = df[df["ym"] == ym]
        dates = sorted(day_data["date"].unique())

        daily_rets = []
        daily_mkt = []

        for d in dates:
            dd = day_data[day_data["date"] == d].dropna(subset=[signal_col, fwd_col])
            if len(dd) < 50:
                continue

            if condition == "flag":
                selected = dd[dd[signal_col] == 1]
                if len(selected) < min_stocks:
                    continue
            elif condition == "top":
                threshold = dd[signal_col].quantile(1 - quantile)
                selected = dd[dd[signal_col] >= threshold]
            else:  # bot
                threshold = dd[signal_col].quantile(quantile)
                selected = dd[dd[signal_col] <= threshold]

            if len(selected) < min_stocks:
                continue

            daily_rets.append(selected[fwd_col].mean())
            daily_mkt.append(dd[fwd_col].mean())

        if not daily_rets:
            continue

        results.append({
            "ym": str(ym),
            "signal_ret": np.mean(daily_rets),
            "market_ret": np.mean(daily_mkt),
            "excess": np.mean(daily_rets) - np.mean(daily_mkt),
            "win_rate": np.mean([1 for r in daily_rets if r > 0]),
            "n_days": len(daily_rets),
        })

    return results


def print_signal_results(name: str, results: list, hold: int):
    if not results:
        print(f"  {name}: 無結果")
        return

    rdf = pd.DataFrame(results)
    avg_ret = rdf["signal_ret"].mean() * 100
    avg_excess = rdf["excess"].mean() * 100
    avg_wr = np.mean([1 for _, r in rdf.iterrows() if r["signal_ret"] > 0]) / len(rdf) * 100
    ic_pos = (rdf["excess"] > 0).mean() * 100

    # 扣成本
    cost = 0.6
    net = avg_ret - cost

    marker = ""
    if avg_excess > 0.5 and ic_pos > 60:
        marker = " ★★"
    elif avg_excess > 0.2 and ic_pos > 55:
        marker = " ★"

    print(f"  {name:>35} | {hold}d | 報酬={avg_ret:>+6.2f}% 超額={avg_excess:>+6.2f}% "
          f"淨利={net:>+6.2f}% 月勝率={avg_wr:>4.0f}% 超額正月={ic_pos:>4.0f}%{marker}")


def main():
    print("=" * 90)
    print("  5d / 10d 短線 Alpha 研究：全新方法")
    print("=" * 90)

    df = load_data()
    print(f"  {len(df):,} rows, {df['date'].min().date()} ~ {df['date'].max().date()}\n")

    # ═══════════════════════════════════════════════════════
    print("Track 1: 法人動能突變")
    print("─" * 70)
    for hold in [5, 10]:
        r = evaluate_signal(df, "foreign_surge", hold, "top", 0.05)
        print_signal_results("外資爆量買（Top5%）", r, hold)
        r = evaluate_signal(df, "foreign_surge", hold, "bot", 0.05)
        print_signal_results("外資爆量賣（Bot5%）", r, hold)
        r = evaluate_signal(df, "trust_surge", hold, "top", 0.05)
        print_signal_results("投信爆量買（Top5%）", r, hold)

    # ═══════════════════════════════════════════════════════
    print(f"\nTrack 2: 量價背離")
    print("─" * 70)
    for hold in [5, 10]:
        r = evaluate_signal(df, "vol_price_div", hold, "flag")
        print_signal_results("放量不漲（flag）", r, hold)

    # ═══════════════════════════════════════════════════════
    print(f"\nTrack 3: 極端反轉")
    print("─" * 70)
    # RSI2 極端
    for hold in [5, 10]:
        r = evaluate_signal(df, "rsi2", hold, "bot", 0.05)
        print_signal_results("RSI2 極低（Bot5%）做多", r, hold)
        r = evaluate_signal(df, "rsi2", hold, "top", 0.05)
        print_signal_results("RSI2 極高（Top5%）做空", r, hold)
        r = evaluate_signal(df, "bias5", hold, "bot", 0.05)
        print_signal_results("5日乖離極低（Bot5%）做多", r, hold)

    # ═══════════════════════════════════════════════════════
    print(f"\nTrack 4: 籌碼轉折")
    print("─" * 70)
    for hold in [5, 10]:
        r = evaluate_signal(df, "foreign_reversal_buy", hold, "flag")
        print_signal_results("外資轉買（flag）", r, hold)
        r = evaluate_signal(df, "foreign_reversal_sell", hold, "flag")
        print_signal_results("外資轉賣（flag）", r, hold)

    # ═══════════════════════════════════════════════════════
    print(f"\nTrack 5: 低波動突破")
    print("─" * 70)
    for hold in [5, 10]:
        r = evaluate_signal(df, "low_vol_breakout", hold, "flag")
        print_signal_results("低波動+量能爆發（flag）", r, hold)

    # ═══════════════════════════════════════════════════════
    print(f"\nTrack 6: 截面動量")
    print("─" * 70)
    for hold in [5, 10]:
        r = evaluate_signal(df, "ret5", hold, "top", 0.05)
        print_signal_results("過去5日漲幅Top5%（動量）", r, hold)
        r = evaluate_signal(df, "ret5", hold, "bot", 0.05)
        print_signal_results("過去5日跌幅Top5%（反轉）", r, hold)
        r = evaluate_signal(df, "ret1", hold, "bot", 0.05)
        print_signal_results("今日跌幅最大5%（日反轉）", r, hold)
        r = evaluate_signal(df, "ret1", hold, "top", 0.05)
        print_signal_results("今日漲幅最大5%（追漲）", r, hold)

    # ═══════════════════════════════════════════════════════
    print(f"\nTrack 7: 組合訊號")
    print("─" * 70)

    # 外資轉買 + RSI低
    df["combo_reversal_oversold"] = ((df["foreign_reversal_buy"] == 1) &
                                      (df["rsi2"] < 30)).astype(int)
    # 外資爆買 + 低波動
    df["combo_smart_breakout"] = ((df["foreign_surge"] > 3) &
                                   (df["ivol_20d"] < df.groupby("date")["ivol_20d"].transform("median"))).astype(int)
    # 超跌 + 量縮（吸籌後反彈）
    df["combo_oversold_quiet"] = ((df["rsi2"] < 20) &
                                   (df["vol_ratio"] < 0.5)).astype(int)
    # 強勢突破：近高點 + 放量
    df["combo_breakout"] = ((df["price_vs_high20"].fillna(-1) > -0.02) &
                             (df["vol_ratio"] > 2)).astype(int)

    for hold in [5, 10]:
        r = evaluate_signal(df, "combo_reversal_oversold", hold, "flag", min_stocks=3)
        print_signal_results("外資轉買+RSI<30（flag）", r, hold)
        r = evaluate_signal(df, "combo_smart_breakout", hold, "flag", min_stocks=3)
        print_signal_results("外資爆買+低波動（flag）", r, hold)
        r = evaluate_signal(df, "combo_oversold_quiet", hold, "flag", min_stocks=3)
        print_signal_results("超跌+量縮（flag）", r, hold)
        r = evaluate_signal(df, "combo_breakout", hold, "flag", min_stocks=3)
        print_signal_results("近高點+放量突破（flag）", r, hold)

    print(f"\n{'=' * 90}")
    print("  以上標 ★★ = 超額>0.5% 且正月>60%，★ = 超額>0.2% 且正月>55%")
    print("  淨利 = 報酬 - 0.6% 交易成本")
    print("=" * 90)


if __name__ == "__main__":
    main()

"""
多維度多空 Alpha 研究：5d / 10d / 20d

目標：找到每個時間維度的最佳因子組合，驗證做多+做空推薦的可行性。
- 5d：短線專用因子（均值回歸 + 微結構），之前用 20d 因子失敗
- 10d：已知 L-S 分辨力最強（Bot10% -0.06%），需獨立模型
- 20d：已上線 10 因子 baseline

每個維度測試多個因子組合，用 walk-forward 每月訓練/測試。
特別關注做空端表現（Bot10% 是否為負）。
"""
from __future__ import annotations

import os
import sys
import warnings
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sqlalchemy import create_engine, text

warnings.filterwarnings("ignore")

PG_URL = os.getenv(
    "PG_URL",
    "postgresql://alphaforge:alphaforge_secret@10.0.4.3:5433/alphaforge",
)
engine = create_engine(PG_URL)

TRAIN_MONTHS = 12
COST = 0.006  # 單程 0.3%（買賣各一次）

# ════════════════════════════════════════════════════════════
#  因子定義：每個維度使用不同因子集
# ════════════════════════════════════════════════════════════

# 已驗證的 10 因子 baseline（20d 最佳）
BASE_10 = [
    "roe", "yield_rate", "pb_ratio", "revenue_yoy",
    "rev_surprise", "rev_accel",
    "foreign_hold_chg_5d", "dealer_buy_20d", "vol_ratio",
    "neg_ivol_20d",
]

# 基本面核心（適用所有維度）
FUNDAMENTAL_CORE = ["roe", "yield_rate", "pb_ratio", "revenue_yoy"]

# 短線因子（5d/10d 專用）
SHORT_TERM = ["rsi2", "neg_bias5", "neg_bias10", "bb_pctb", "vol_ratio"]

# 中期因子
MID_TERM = ["rev_surprise", "rev_accel", "foreign_hold_chg_5d", "dealer_buy_20d"]

# 波動率因子
VOLATILITY = ["neg_ivol_20d", "neg_atr_pct"]

# 籌碼面
CHIP_SHORT = ["foreign_net_buy", "neg_trust_net_buy", "vol_ratio"]
CHIP_MID = ["foreign_hold_chg_5d", "dealer_buy_20d", "foreign_buy_5d"]

# ── 各維度策略 ──
STRATEGIES_5D: Dict[str, List[str]] = {
    # A: 短線均值回歸（oversold bounce）
    "5d_A_reversal": ["rsi2", "neg_bias5", "bb_pctb", "vol_ratio", "neg_ivol_20d"],
    # B: 短線動量（breakout）
    "5d_B_momentum": ["bias5", "vol_ratio", "foreign_net_buy", "neg_trust_net_buy", "neg_ivol_20d"],
    # C: 基本面+短線
    "5d_C_fund_short": FUNDAMENTAL_CORE + ["rsi2", "neg_bias5", "vol_ratio"],
    # D: 籌碼+短線
    "5d_D_chip_short": CHIP_SHORT + ["rsi2", "neg_bias5", "neg_ivol_20d"],
    # E: 全短線（純技術面）
    "5d_E_all_tech": ["rsi2", "neg_bias5", "neg_bias10", "bb_pctb", "vol_ratio",
                       "k", "neg_ivol_20d"],
    # F: 20d baseline 直接套用（對照組）
    "5d_F_base10": BASE_10,
    # G: 精選短線（反向思維：做空高 RSI、做多低 RSI）
    "5d_G_contrarian": ["neg_rsi14", "neg_bias20", "neg_ivol_20d", "yield_rate", "roe"],
    # H: 短線+法人（外資買超+低波動+超跌）
    "5d_H_smart_reversal": ["rsi2", "neg_bias5", "foreign_net_buy", "neg_ivol_20d",
                             "roe", "yield_rate"],
}

STRATEGIES_10D: Dict[str, List[str]] = {
    # A: 20d baseline 直接套用
    "10d_A_base10": BASE_10,
    # B: 基本面+短線混合
    "10d_B_fund_short": FUNDAMENTAL_CORE + SHORT_TERM[:3] + ["neg_ivol_20d"],
    # C: 基本面+籌碼（之前 10d 最佳配方）
    "10d_C_fund_chip": FUNDAMENTAL_CORE + CHIP_MID + ["vol_ratio", "neg_ivol_20d"],
    # D: 全面 12 因子
    "10d_D_full12": FUNDAMENTAL_CORE + MID_TERM + ["rsi2", "neg_bias5", "neg_ivol_20d", "vol_ratio"],
    # E: 反向投信（做空散戶跟風）
    "10d_E_contrarian": FUNDAMENTAL_CORE + ["neg_trust_net_buy", "foreign_hold_chg_5d",
                                              "neg_ivol_20d", "vol_ratio"],
    # F: 精選 8 因子（去除 rev_surprise/rev_accel，看純價量能否做好 10d）
    "10d_F_no_rev": ["roe", "yield_rate", "pb_ratio",
                      "foreign_hold_chg_5d", "dealer_buy_20d", "vol_ratio",
                      "neg_ivol_20d", "rsi2"],
}

STRATEGIES_20D: Dict[str, List[str]] = {
    # A: 現有 10 因子 (baseline)
    "20d_A_base10": BASE_10,
    # B: +rsi2（短線超賣 → 中期反彈）
    "20d_B_+rsi2": BASE_10 + ["rsi2"],
    # C: +neg_bias20（近高點乖離 → 過熱回落）
    "20d_C_+negBias20": BASE_10 + ["neg_bias20"],
    # D: +neg_trust_net_buy（反向投信）
    "20d_D_+negTrust": BASE_10 + ["neg_trust_net_buy"],
    # E: 13 因子全配
    "20d_E_full13": BASE_10 + ["rsi2", "neg_bias20", "neg_trust_net_buy"],
}

ALL_CONFIGS = {
    5: (STRATEGIES_5D, 5, 1),   # (strategies, hold_days, gap)
    10: (STRATEGIES_10D, 10, 1),
    20: (STRATEGIES_20D, 20, 1),
}


def load_data() -> pd.DataFrame:
    """載入所有需要的欄位"""
    needed_factors = set()
    for strats, _, _ in ALL_CONFIGS.values():
        for factors in strats.values():
            for f in factors:
                # 去掉 neg_ prefix 取原始欄位
                raw = f[4:] if f.startswith("neg_") else f
                needed_factors.add(raw)

    # 固定需要的欄位
    fixed = {"stock_id", "date", "close", "ma60", "change_pct",
             "rsi14", "bias5", "bias10", "bias20", "bb_pctb", "k", "d",
             "ivol_20d", "atr_pct", "foreign_net_buy", "trust_net_buy",
             "vol_ratio", "rsi2"}
    all_cols = list(fixed | needed_factors)

    # 去除可能的 neg_ 前綴（DB 裡沒有）
    db_cols = [c for c in all_cols if not c.startswith("neg_")]
    db_cols = list(set(db_cols))

    sql = text(f"""
        SELECT {', '.join(db_cols)}
        FROM stock_features
        WHERE close > 0 AND date >= '2023-03-01'
        ORDER BY date, stock_id
    """)
    print("  Loading data from PostgreSQL...")
    df = pd.read_sql(sql, engine)
    df["date"] = pd.to_datetime(df["date"])
    print(f"  Loaded {len(df):,} rows, {df['date'].min().date()} ~ {df['date'].max().date()}")

    # 衍生反向因子（neg_ prefix = 取負數）
    neg_map = {
        "neg_ivol_20d": "ivol_20d",
        "neg_atr_pct": "atr_pct",
        "neg_bias5": "bias5",
        "neg_bias10": "bias10",
        "neg_bias20": "bias20",
        "neg_rsi14": "rsi14",
        "neg_trust_net_buy": "trust_net_buy",
    }
    for neg_col, src_col in neg_map.items():
        if src_col in df.columns:
            df[neg_col] = -df[src_col]

    # Forward returns（一次計算三個維度）
    df = df.sort_values(["stock_id", "date"])
    for hold in [5, 10, 20]:
        gap = 1
        df[f"entry_{hold}"] = df.groupby("stock_id")["close"].shift(-gap)
        df[f"exit_{hold}"] = df.groupby("stock_id")["close"].shift(-(gap + hold))
        df[f"fwd_ret_{hold}"] = (df[f"exit_{hold}"] - df[f"entry_{hold}"]) / df[f"entry_{hold}"]

    df["ym"] = df["date"].dt.to_period("M")
    return df


def train_ensemble(
    train: pd.DataFrame, factors: List[str], fwd_col: str
) -> Optional[Tuple]:
    """訓練 LightGBM Ensemble（Clf + Reg）"""
    # 只需要 fwd_ret 不為 NaN；因子 NaN 用截面中位數填充後再排名
    t = train.dropna(subset=[fwd_col]).copy()
    if len(t) < 500:
        return None

    rank_cols = []
    for f in factors:
        rc = f"{f}_r"
        # NaN 填充截面中位數 → 排名為 0.5（中性）
        filled = t.groupby("date")[f].transform(lambda x: x.fillna(x.median()))
        t[rc] = t.groupby("date")[filled.name].rank(pct=True)
        # 如果整日都是 NaN，rank 也是 NaN → 填 0.5
        t[rc] = t[rc].fillna(0.5)
        rank_cols.append(rc)

    X = t[rank_cols].values
    y_cls = (t[fwd_col] > t[fwd_col].median()).astype(int).values
    y_reg = t[fwd_col].clip(-0.5, 0.5).values

    clf = HistGradientBoostingClassifier(
        max_iter=150, max_depth=4, random_state=42, class_weight="balanced"
    )
    reg = HistGradientBoostingRegressor(
        max_iter=150, max_depth=4, random_state=42
    )
    clf.fit(X, y_cls)
    reg.fit(X, y_reg)

    return clf, reg, rank_cols


def predict_day(
    clf, reg, rank_cols: List[str], factors: List[str], day_data: pd.DataFrame
) -> Optional[pd.Series]:
    """用已訓練的模型對單日截面預測"""
    # 只需要 close > 0 即可；因子 NaN 用截面中位數填充
    s = day_data.copy()
    if len(s) < 50:
        return None

    for f, rc in zip(factors, rank_cols):
        filled = s[f].fillna(s[f].median())
        s[rc] = filled.rank(pct=True).fillna(0.5)

    X = s[rank_cols].values
    prob = clf.predict_proba(X)[:, 1]
    reg_pred = reg.predict(X)
    reg_rank = pd.Series(reg_pred, index=s.index).rank(pct=True).values
    score = prob * 0.5 + reg_rank * 0.5

    return pd.Series(score, index=s.index)


def run_walkforward_for_dimension(
    df: pd.DataFrame, hold: int, gap: int, strategies: Dict[str, List[str]]
) -> Dict[str, List[dict]]:
    """Walk-forward 驗證某個維度的所有策略"""
    fwd_col = f"fwd_ret_{hold}"
    months = sorted(df["ym"].unique())
    results: Dict[str, List[dict]] = {name: [] for name in strategies}

    test_start = TRAIN_MONTHS
    n_test = len(months) - test_start
    print(f"\n  [{hold}d] 測試窗口: {n_test} 個月")

    for i in range(test_start, len(months)):
        test_month = months[i]
        train_months = months[i - TRAIN_MONTHS:i]

        train = df[df["ym"].isin(train_months)].copy()
        test = df[df["ym"] == test_month].copy()
        test_dates = sorted(test["date"].unique())
        if not test_dates:
            continue

        print(f"    {test_month} ({len(test_dates)}d)", end="", flush=True)

        for strat_name, factors in strategies.items():
            # 檢查因子是否都在 df 中
            missing = [f for f in factors if f not in df.columns]
            if missing:
                print(f"\n    [WARN] {strat_name}: missing {missing}")
                continue

            models = train_ensemble(train, factors, fwd_col)
            if models is None:
                continue
            clf, reg, rank_cols = models

            daily_ics = []
            daily_tops = []
            daily_bots = []
            daily_mkts = []
            daily_top5_rets = []
            daily_bot5_rets = []
            daily_top_wr = []
            daily_bot_wr = []

            for td in test_dates:
                day_data = test[test["date"] == td].copy()
                if len(day_data) < 100:
                    continue

                scores = predict_day(clf, reg, rank_cols, factors, day_data)
                if scores is None:
                    continue

                day_data = day_data.copy()
                day_data.loc[scores.index, "score"] = scores
                valid = day_data.dropna(subset=["score", fwd_col])
                if len(valid) < 50:
                    continue

                # IC
                ic, _ = stats.spearmanr(valid["score"], valid[fwd_col])
                if np.isnan(ic):
                    continue
                daily_ics.append(ic)

                # Top/Bot 10%
                valid = valid.copy()
                valid["rank_pct"] = valid["score"].rank(pct=True)
                top10 = valid[valid["rank_pct"] >= 0.9][fwd_col]
                bot10 = valid[valid["rank_pct"] <= 0.1][fwd_col]
                mkt = valid[fwd_col]

                daily_tops.append(top10.mean())
                daily_bots.append(bot10.mean())
                daily_mkts.append(mkt.mean())

                # Top 5 / Bot 5 股票（模擬推薦清單）
                top5 = valid.nlargest(5, "score")[fwd_col]
                bot5 = valid.nsmallest(5, "score")[fwd_col]
                daily_top5_rets.append(top5.mean())
                daily_bot5_rets.append(bot5.mean())

                # 勝率
                daily_top_wr.append((top10 > 0).mean())
                daily_bot_wr.append((bot10 < 0).mean())

            if not daily_ics:
                continue

            results[strat_name].append({
                "ym": str(test_month),
                "ic_mean": np.mean(daily_ics),
                "ic_pos_pct": np.mean([1 for x in daily_ics if x > 0]),
                "n_days": len(daily_ics),
                "top10": np.mean(daily_tops),
                "bot10": np.mean(daily_bots),
                "mkt": np.mean(daily_mkts),
                "excess": np.mean(daily_tops) - np.mean(daily_mkts),
                "ls": np.mean(daily_tops) - np.mean(daily_bots),
                "top5_ret": np.mean(daily_top5_rets),
                "bot5_ret": np.mean(daily_bot5_rets),
                "top_wr": np.mean(daily_top_wr),
                "bot_neg_wr": np.mean(daily_bot_wr),
            })

        print(" ✓")

    return results


def print_dimension_results(hold: int, strategies: Dict[str, List[str]],
                             results: Dict[str, List[dict]]) -> dict:
    """列印某維度的所有策略結果，回傳最佳策略資訊"""
    cost_per_trade = COST  # 單次來回成本

    print(f"\n{'═' * 160}")
    print(f"  {hold}d 維度結果（成本 {cost_per_trade*100:.1f}%/次）")
    print(f"{'═' * 160}")

    header = (f"  {'策略':>22} {'N因子':>5} {'月數':>4} {'IC':>8} {'IC正':>5}"
              f" {'Top10%':>8} {'Bot10%':>8} {'L-S':>8} {'Top5':>8} {'Bot5':>8}"
              f" {'做多WR':>6} {'做空WR':>6} {'Sharpe':>7} {'MDD':>7}")
    print(header)
    print("  " + "─" * 145)

    all_summaries = []
    for strat_name in strategies:
        ms = results.get(strat_name, [])
        if not ms:
            continue
        mdf = pd.DataFrame(ms)
        n = len(mdf)

        avg_ic = mdf["ic_mean"].mean()
        ic_pos = (mdf["ic_mean"] > 0).mean()
        avg_top10 = mdf["top10"].mean() * 100
        avg_bot10 = mdf["bot10"].mean() * 100
        avg_ls = mdf["ls"].mean() * 100
        avg_top5 = mdf["top5_ret"].mean() * 100
        avg_bot5 = mdf["bot5_ret"].mean() * 100
        avg_top_wr = mdf["top_wr"].mean() * 100
        avg_bot_wr = mdf["bot_neg_wr"].mean() * 100

        me = mdf["excess"].values
        sharpe = np.mean(me) / np.std(me, ddof=1) * np.sqrt(12) if np.std(me, ddof=1) > 0 else 0

        cum_top = (1 + mdf["top10"] - cost_per_trade).cumprod()
        maxdd_top = ((cum_top - cum_top.cummax()) / cum_top.cummax()).min() * 100

        nf = len(strategies[strat_name])
        all_summaries.append({
            "name": strat_name, "nf": nf, "n": n,
            "ic": avg_ic, "ic_pos": ic_pos,
            "top10": avg_top10, "bot10": avg_bot10,
            "ls": avg_ls,
            "top5": avg_top5, "bot5": avg_bot5,
            "top_wr": avg_top_wr, "bot_wr": avg_bot_wr,
            "sharpe": sharpe, "maxdd": maxdd_top,
        })

        print(f"  {strat_name:>22} {nf:>5} {n:>4} {avg_ic:>+8.4f} {ic_pos:>4.0%}"
              f" {avg_top10:>+7.2f}% {avg_bot10:>+7.2f}% {avg_ls:>+7.2f}%"
              f" {avg_top5:>+7.2f}% {avg_bot5:>+7.2f}%"
              f" {avg_top_wr:>5.1f}% {avg_bot_wr:>5.1f}%"
              f" {sharpe:>7.2f} {maxdd_top:>6.1f}%")

    sdf = pd.DataFrame(all_summaries)
    if sdf.empty:
        return {}

    # ── 排名 ──
    print(f"\n  ── {hold}d 排名（按 IC 排序）──")
    ranked = sdf.sort_values("ic", ascending=False)
    best = ranked.iloc[0]
    for rank, (_, r) in enumerate(ranked.iterrows(), 1):
        markers = []
        if r["ic"] > 0.03:
            markers.append("IC強")
        if r["bot10"] < 0:
            markers.append("做空有效✓")
        if r["top_wr"] > 55:
            markers.append("勝率>55%")
        if r["ls"] > 1.0:
            markers.append("L-S>1%")
        tag = " [" + ", ".join(markers) + "]" if markers else ""
        print(f"  {rank}. {r['name']:>22} IC={r['ic']:+.4f} L-S={r['ls']:+.2f}%"
              f" Top5={r['top5']:+.2f}% Bot5={r['bot5']:+.2f}%"
              f" 做多WR={r['top_wr']:.1f}% 做空WR={r['bot_wr']:.1f}%{tag}")

    # ── 做多/做空可行性評估 ──
    print(f"\n  ── {hold}d 做多/做空可行性 ──")
    for _, r in ranked.head(3).iterrows():
        net_top5 = r["top5"] - cost_per_trade * 100
        net_bot5 = -r["bot5"] - cost_per_trade * 100  # 做空: 股票跌=賺
        long_ok = "✓" if net_top5 > 0 and r["top_wr"] > 50 else "✗"
        short_ok = "✓" if net_bot5 > 0 and r["bot_wr"] > 50 else "✗"
        print(f"    {r['name']:>22}:")
        print(f"      做多: Top5 月報酬={r['top5']:+.2f}%, 扣成本={net_top5:+.2f}%,"
              f" 勝率={r['top_wr']:.1f}% → {long_ok}")
        print(f"      做空: Bot5 月報酬={r['bot5']:+.2f}%, 做空淨利={net_bot5:+.2f}%,"
              f" 下跌率={r['bot_wr']:.1f}% → {short_ok}")

    # ── 最佳策略逐年 ──
    best_name = best["name"]
    bdf = pd.DataFrame(results[best_name])
    bdf["year"] = bdf["ym"].apply(lambda x: x[:4])

    print(f"\n  ── {best_name} 逐年表現 ──")
    print(f"  {'年':>6} {'IC':>8} {'IC正':>5} {'Top10':>8} {'Bot10':>8} {'L-S':>8}"
          f" {'Top5':>8} {'Bot5':>8} {'做多WR':>6} {'做空WR':>6}")
    print("  " + "─" * 90)
    for yr, ygrp in bdf.groupby("year"):
        print(f"  {yr:>6} {ygrp['ic_mean'].mean():>+8.4f}"
              f" {(ygrp['ic_mean']>0).mean():>4.0%}"
              f" {ygrp['top10'].mean()*100:>+7.2f}%"
              f" {ygrp['bot10'].mean()*100:>+7.2f}%"
              f" {ygrp['ls'].mean()*100:>+7.2f}%"
              f" {ygrp['top5_ret'].mean()*100:>+7.2f}%"
              f" {ygrp['bot5_ret'].mean()*100:>+7.2f}%"
              f" {ygrp['top_wr'].mean()*100:>5.1f}%"
              f" {ygrp['bot_neg_wr'].mean()*100:>5.1f}%")

    return {
        "hold": hold,
        "best_strategy": best_name,
        "best_factors": strategies[best_name],
        "ic": best["ic"],
        "ls": best["ls"],
        "top5": best["top5"],
        "bot5": best["bot5"],
        "top_wr": best["top_wr"],
        "bot_wr": best["bot_wr"],
        "long_viable": best["top5"] - cost_per_trade * 100 > 0 and best["top_wr"] > 50,
        "short_viable": -best["bot5"] - cost_per_trade * 100 > 0 and best["bot_wr"] > 50,
    }


def main() -> None:
    print("=" * 80)
    print("  多維度多空 Alpha 研究")
    print("  目標：5d/10d/20d 看漲看跌 Top5 推薦清單")
    print("=" * 80)

    df = load_data()

    dimension_results = {}

    for hold in [5, 10, 20]:
        strategies, hold_days, gap = ALL_CONFIGS[hold]
        results = run_walkforward_for_dimension(df, hold_days, gap, strategies)
        best = print_dimension_results(hold_days, strategies, results)
        dimension_results[hold] = best

    # ═══════════════════════════════════���════════════════════════
    #  總結：推薦清單可行性
    # ════════════════════════════════════════════════════════════
    print(f"\n{'═' * 100}")
    print(f"  總結：多維度推薦清單可行性")
    print(f"{'═' * 100}")

    print(f"\n  {'維度':>6} {'最佳策略':>25} {'IC':>8} {'L-S':>8}"
          f" {'Top5月報酬':>10} {'Bot5月報酬':>10} {'做多':>6} {'做空':>6}")
    print("  " + "─" * 85)

    for hold in [5, 10, 20]:
        d = dimension_results.get(hold, {})
        if not d:
            print(f"  {hold}d    (no results)")
            continue
        long_mark = "✓ 可做" if d.get("long_viable") else "✗ 不做"
        short_mark = "✓ 可做" if d.get("short_viable") else "✗ 不做"
        print(f"  {hold}d {d['best_strategy']:>25} {d['ic']:>+8.4f} {d['ls']:>+7.2f}%"
              f" {d['top5']:>+9.2f}% {d['bot5']:>+9.2f}%"
              f" {long_mark:>8} {short_mark:>8}")

    print(f"\n  建議：")
    for hold in [5, 10, 20]:
        d = dimension_results.get(hold, {})
        if not d:
            continue
        if d.get("long_viable"):
            print(f"  ✓ {hold}d 做多推薦可上線 — 最佳因子: {d['best_factors']}")
        else:
            net = d.get("top5", 0) - COST * 100
            print(f"  ✗ {hold}d 做多推薦不可行 — Top5 月報酬 {d.get('top5', 0):+.2f}%, 扣成本 {net:+.2f}%")

        if d.get("short_viable"):
            net = -d.get("bot5", 0) - COST * 100
            print(f"  ✓ {hold}d 做空推薦可上線 — Bot5 月報酬 {d.get('bot5', 0):+.2f}%, 做空淨利 {net:+.2f}%")
        else:
            print(f"  ✗ {hold}d 做空推薦不可行 — Bot5 月報酬 {d.get('bot5', 0):+.2f}%（做空端虧損不足）")


if __name__ == "__main__":
    main()

"""
5d 專用策略實驗 — 短期因子

基本面因子變化太慢，不適合預測 5 天。
嘗試純籌碼/短期動量/量價因子。
"""
from __future__ import annotations
import os, warnings
import numpy as np
import pandas as pd
from scipy import stats
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sqlalchemy import create_engine, text

warnings.filterwarnings("ignore")
PG_URL = os.getenv("PG_URL", "postgresql://alphaforge:alphaforge_secret@10.0.4.3:5433/alphaforge")
engine = create_engine(PG_URL)
COST = 0.006

def load_data():
    sql = text("""SELECT stock_id, date, close, ma5, ma10, ma20, ma60, volume,
        rsi14, rsi2, k, d, macd_osc, bb_pctb, vol_ratio, change_pct,
        foreign_net_buy, foreign_buy_5d, trust_net_buy, trust_buy_5d,
        dealer_net_buy, dealer_buy_5d, margin_chg_5d,
        foreign_hold_chg_5d, price_vs_high20,
        roe, yield_rate, pb_ratio, revenue_yoy
        FROM stock_features WHERE close > 0 AND date >= '2023-03-01'
        ORDER BY date, stock_id""")
    df = pd.read_sql(sql, engine)
    df["date"] = pd.to_datetime(df["date"])

    g = df.groupby("stock_id")
    # 短期動量
    df["mom_1d"] = g["close"].pct_change(1)
    df["mom_3d"] = g["close"].pct_change(3)
    df["mom_5d"] = g["close"].pct_change(5)
    # 量能變化
    df["vol_chg_3d"] = g["volume"].pct_change(3)
    # 反向投信
    df["neg_trust_buy_5d"] = -df["trust_buy_5d"].fillna(0)
    df["neg_trust_net_buy"] = -df["trust_net_buy"].fillna(0)
    # RSI2 超賣
    df["rsi2_oversold"] = (df["rsi2"] < 15).astype(float)
    # 均線位置
    df["price_vs_ma5"] = (df["close"] - df["ma5"]) / df["ma5"].clip(lower=1)
    df["price_vs_ma20"] = (df["close"] - df["ma20"]) / df["ma20"].clip(lower=1)

    print(f"[Data] {len(df):,} 筆，{df['date'].min().date()} ~ {df['date'].max().date()}")
    return df


CONFIGS = {
    # A: 純籌碼短期
    "A: 純籌碼短期": [
        "foreign_net_buy", "foreign_buy_5d", "neg_trust_net_buy", "neg_trust_buy_5d",
        "dealer_net_buy", "dealer_buy_5d", "foreign_hold_chg_5d",
    ],
    # B: 籌碼+量價
    "B: 籌碼+量價": [
        "foreign_net_buy", "foreign_buy_5d", "neg_trust_net_buy", "neg_trust_buy_5d",
        "dealer_buy_5d", "foreign_hold_chg_5d",
        "vol_ratio", "rsi2", "bb_pctb", "price_vs_high20",
    ],
    # C: 短期動量+籌碼
    "C: 動量+籌碼": [
        "mom_1d", "mom_3d", "mom_5d", "vol_chg_3d",
        "foreign_net_buy", "foreign_buy_5d", "neg_trust_buy_5d",
        "rsi2_oversold", "price_vs_ma5",
    ],
    # D: 均值回歸（超跌反彈）
    "D: 均值回歸": [
        "rsi2", "price_vs_ma5", "price_vs_ma20", "price_vs_high20",
        "bb_pctb", "mom_3d", "vol_ratio",
        "foreign_net_buy", "neg_trust_buy_5d",
    ],
    # E: 全短期因子
    "E: 全短期": [
        "mom_1d", "mom_3d", "mom_5d", "vol_chg_3d",
        "foreign_net_buy", "foreign_buy_5d", "neg_trust_net_buy", "neg_trust_buy_5d",
        "dealer_buy_5d", "foreign_hold_chg_5d",
        "vol_ratio", "rsi2", "bb_pctb", "price_vs_high20",
        "rsi2_oversold", "price_vs_ma5", "price_vs_ma20",
    ],
    # F: 15穩定因子（baseline）
    "F: 15穩定(base)": [
        "roe", "yield_rate", "pb_ratio", "revenue_yoy",
        "foreign_hold_chg_5d", "foreign_net_buy", "foreign_buy_5d",
        "vol_ratio", "price_vs_high20",
        "neg_trust_net_buy", "neg_trust_buy_5d",
    ],
    # G: 基本面+短期混合
    "G: 基本面+短期": [
        "roe", "yield_rate", "pb_ratio", "revenue_yoy",
        "foreign_net_buy", "foreign_buy_5d", "neg_trust_buy_5d",
        "mom_1d", "mom_3d", "rsi2", "vol_ratio",
        "price_vs_ma5", "price_vs_high20",
    ],
}


def gen_windows(df, test_months=4, gap_months=1, min_train_months=8):
    mn, mx = df["date"].min(), df["date"].max()
    ts = mn + pd.DateOffset(months=min_train_months + gap_months)
    wins = []
    wid = 1
    while ts + pd.DateOffset(months=2) <= mx:
        te = min(ts + pd.DateOffset(months=test_months), mx)
        tr = ts - pd.DateOffset(months=gap_months)
        wins.append((wid, pd.Timestamp(tr), pd.Timestamp(ts), pd.Timestamp(te)))
        ts += pd.DateOffset(months=test_months)
        wid += 1
    return wins


def run(df_raw, factors, name, forward_days=5, threshold=0.02, ma60_filter=False):
    df = df_raw.sort_values(["stock_id","date"]).copy()
    df["forward_close"] = df.groupby("stock_id")["close"].shift(-forward_days)
    df["forward_return"] = (df["forward_close"] - df["close"]) / df["close"]
    df["label"] = (df["forward_return"] > threshold).astype(float)
    if ma60_filter:
        df = df[df["close"] > df["ma60"]].copy()

    rc = []
    for f in factors:
        if f in df.columns:
            r = f"{f}_rank"
            df[r] = df.groupby("date")[f].rank(pct=True, na_option="keep")
            rc.append(r)

    wins = gen_windows(df)
    all_ics, monthly = [], []

    for wid, tr, ts, te in wins:
        train = df[df["date"]<=tr].dropna(subset=["label"])
        test = df[(df["date"]>=ts)&(df["date"]<=te)].dropna(subset=["label","forward_return"])
        if len(train)<2000 or len(test)<300: continue

        X_tr, y_tr = train[rc].values, train["label"].values
        w = np.clip(1.0-0.2*(tr.year-train["date"].dt.year),0.2,1.0).values

        clf = HistGradientBoostingClassifier(max_iter=200,max_depth=4,max_leaf_nodes=15,
            learning_rate=0.01,min_samples_leaf=100,l2_regularization=1.0,random_state=42,
            verbose=0,class_weight="balanced")
        clf.fit(X_tr,y_tr,sample_weight=w)

        y_reg = train["forward_return"].values.clip(-0.3,0.3)
        reg = HistGradientBoostingRegressor(max_iter=200,max_depth=4,max_leaf_nodes=15,
            learning_rate=0.01,min_samples_leaf=100,l2_regularization=1.0,random_state=42,verbose=0)
        reg.fit(X_tr,y_reg,sample_weight=w)

        p_clf = clf.predict_proba(test[rc].values)[:,1]
        p_reg = reg.predict(test[rc].values)
        rmin,rmax = reg.predict(X_tr).min(),reg.predict(X_tr).max()
        p_reg_n = np.clip((p_reg-rmin)/(rmax-rmin+1e-9),0,1)
        prob = 0.5*p_clf + 0.5*p_reg_n

        test = test.copy()
        test["_p"] = prob
        daily_ics = []
        for _,g in test.groupby("date"):
            if len(g)<50: continue
            p,r = g["_p"].values, g["forward_return"].values
            v = ~np.isnan(r)
            if v.sum()<30: continue
            ic,_ = stats.spearmanr(p[v],r[v])
            if not np.isnan(ic): daily_ics.append(ic)
        ic = np.mean(daily_ics) if daily_ics else 0
        all_ics.append(ic)

        cut = np.percentile(prob,90)
        top = prob>=cut
        test["_top"]=top
        test["_m"]=test["date"].dt.to_period("M")
        for _,g in test[test["_top"]].groupby("_m"):
            monthly.append(float(np.nanmean(g["forward_return"].values))-COST)

    if not all_ics: return None
    net = np.array(monthly)
    ann = np.mean(net)*52  # 5d ≈ weekly
    vol = np.std(net)*np.sqrt(52)
    sh = ann/vol if vol>0 else 0

    return {"name":name,"avg_ic":np.mean(all_ics),"min_ic":np.min(all_ics),
            "ic_pos":sum(1 for x in all_ics if x>0)/len(all_ics),
            "n_pass":sum(1 for x in all_ics if x>0.05),"n_win":len(all_ics),
            "ann":ann,"sharpe":sh}


def main():
    df = load_data()
    results = []
    for name, factors in CONFIGS.items():
        print(f"  跑 {name}...")
        r = run(df, factors, name)
        if r: results.append(r)

    # 也試 MA60
    print(f"  跑 D: 均值回歸+MA60...")
    r = run(df, CONFIGS["D: 均值回歸"], "D2: 均值回歸+MA60", ma60_filter=True)
    if r: results.append(r)

    # 試 threshold=1%
    print(f"  跑 E: 全短期 thr=1%...")
    r = run(df, CONFIGS["E: 全短期"], "E2: 全短期 thr1%", threshold=0.01)
    if r: results.append(r)

    print(f"\n{'='*70}")
    print(f"  5d 策略比較")
    print(f"{'='*70}")
    results.sort(key=lambda x: x["sharpe"], reverse=True)
    print(f"\n  {'策略':>20} {'avgIC':>7} {'minIC':>7} {'IC>0':>5} {'pass':>5} {'年化':>7} {'Sharpe':>7}")
    print("  "+"─"*65)
    for r in results:
        print(f"  {r['name']:>20} {r['avg_ic']:>+7.4f} {r['min_ic']:>+7.4f} "
              f"{r['ic_pos']:>4.0%} {r['n_pass']}/{r['n_win']:>1} "
              f"{r['ann']*100:>+6.1f}% {r['sharpe']:>7.2f}")


if __name__ == "__main__":
    main()

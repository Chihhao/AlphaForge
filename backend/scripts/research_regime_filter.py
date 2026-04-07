"""
Regime Filter 回測研究
=====================
驗證 Strategy Miner 的 0050 < MA20 硬門檻是否有效。

用全維度 long 信號（跨維度合併）計算 10d/20d 前瞻報酬，
比較有/無 regime filter 的推薦績效。
"""

import sys
sys.path.insert(0, '.')

import logging
logging.disable(logging.INFO)

import numpy as np
import pandas as pd
from app.db.database import SessionLocal
from app.models.stock_price import StockPrice
from app.models.alpha_signal_history import AlphaSignalHistory

TOP_N = 5


def load_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    """載入 0050 價格 + 全維度 long 信號"""
    db = SessionLocal()
    try:
        rows = db.query(StockPrice.date, StockPrice.close).filter(
            StockPrice.stock_id == '0050'
        ).order_by(StockPrice.date).all()
        etf = pd.DataFrame(rows, columns=['date', 'close'])
        etf['close'] = etf['close'].astype(float)
        etf['date'] = pd.to_datetime(etf['date'])

        sig_rows = db.query(
            AlphaSignalHistory.signal_date,
            AlphaSignalHistory.stock_id,
            AlphaSignalHistory.trigger_count,
            AlphaSignalHistory.weighted_odds_ratio,
        ).filter(
            AlphaSignalHistory.direction == 'long',
        ).all()

        sig = pd.DataFrame(sig_rows, columns=['date', 'stock_id', 'trigger_count', 'odds_ratio'])
        sig['date'] = pd.to_datetime(sig['date'])
        sig['trigger_count'] = sig['trigger_count'].astype(float)
        sig['odds_ratio'] = sig['odds_ratio'].astype(float).fillna(1.0)
        sig['score'] = sig['trigger_count'] * sig['odds_ratio']

        # 同日同股票保留最高 score
        sig = sig.sort_values('score', ascending=False).drop_duplicates(
            subset=['date', 'stock_id'], keep='first'
        )
        sig = sig.sort_values(['date', 'score'], ascending=[True, False])
        return etf, sig
    finally:
        db.close()


def load_all_prices() -> pd.DataFrame:
    db = SessionLocal()
    try:
        rows = db.query(
            StockPrice.stock_id, StockPrice.date, StockPrice.close
        ).filter(StockPrice.date >= '2025-08-01').all()
        df = pd.DataFrame(rows, columns=['stock_id', 'date', 'close'])
        df['close'] = df['close'].astype(float)
        df['date'] = pd.to_datetime(df['date'])
        return df
    finally:
        db.close()


def calc_regime(etf: pd.DataFrame, window: int) -> pd.Series:
    ma = etf['close'].rolling(window).mean()
    return pd.Series((etf['close'] > ma).values, index=etf['date'])


def calc_fwd_ret(prices: pd.DataFrame, horizon: int) -> pd.DataFrame:
    pivot = prices.pivot_table(index='date', columns='stock_id', values='close').sort_index()
    return pivot.shift(-horizon) / pivot - 1


def backtest(etf, sig, fwd_ret, window, top_n=TOP_N):
    regime = calc_regime(etf, window)
    results = {'pass': [], 'block': []}

    for d in sorted(sig['date'].unique()):
        if d not in regime.index or d not in fwd_ret.index:
            continue
        day_sig = sig[sig['date'] == d].head(top_n)
        rets = []
        for _, row in day_sig.iterrows():
            sid = row['stock_id']
            if sid in fwd_ret.columns:
                r = fwd_ret.loc[d, sid]
                if pd.notna(r):
                    rets.append(r)
        if not rets:
            continue
        label = 'pass' if regime[d] else 'block'
        results[label].append({'date': d, 'ret': np.mean(rets)})

    return results


def stats(rets, horizon):
    if not rets:
        return None
    r = [x['ret'] for x in rets]
    std = np.std(r)
    return {
        'n': len(r),
        'mean': np.mean(r) * 100,
        'median': np.median(r) * 100,
        'winrate': np.mean([1 if x > 0 else 0 for x in r]) * 100,
        'sharpe': np.mean(r) / std * np.sqrt(252 / horizon) if std > 0 else 0,
    }


def fmt(s):
    if s is None:
        return "無資料"
    return (f"n={s['n']}, mean={s['mean']:+.2f}%, median={s['median']:+.2f}%, "
            f"wr={s['winrate']:.0f}%, sharpe={s['sharpe']:.2f}")


def main():
    print("=" * 70)
    print("Regime Filter 回測研究")
    print("=" * 70)

    print("\n載入資料...")
    etf, sig = load_data()
    prices = load_all_prices()
    print(f"  0050: {len(etf)} 天, 信號: {sig['date'].nunique()} 天, {len(sig)} 筆")

    for horizon in [10, 20]:
        print(f"\n{'#' * 70}")
        print(f"# 前瞻 {horizon}d 報酬")
        print(f"{'#' * 70}")

        fwd = calc_fwd_ret(prices, horizon)
        valid_last = fwd.dropna(how='all').index[-1]
        n_valid = sig[sig['date'] <= valid_last]['date'].nunique()
        print(f"  可用信號日: {n_valid} (截至 {valid_last.date()})")

        for window in [5, 10, 20, 60]:
            print(f"\n  --- MA{window} (0050 > MA{window}) ---")
            r = backtest(etf, sig, fwd, window)

            sp = stats(r['pass'], horizon)
            sb = stats(r['block'], horizon)
            sa = stats(r['pass'] + r['block'], horizon)

            print(f"    通過: {fmt(sp)}")
            print(f"    被擋: {fmt(sb)}")
            print(f"    全部: {fmt(sa)}")

            if sp and sb:
                diff = sp['mean'] - sb['mean']
                total = sp['n'] + sb['n']
                block_pct = sb['n'] / total * 100
                print(f"    差異: {diff:+.2f}pp, 被擋比例: {block_pct:.0f}% ({sb['n']}/{total})")

    # ─── MA20 被擋日期明細 ───
    print(f"\n{'=' * 70}")
    print("MA20 被擋日期明細 (10d 前瞻)")
    print(f"{'=' * 70}")

    fwd10 = calc_fwd_ret(prices, 10)
    r20 = backtest(etf, sig, fwd10, 20)
    blocked = sorted(r20['block'], key=lambda x: x['date'])

    for item in blocked:
        d = item['date']
        etf_row = etf[etf['date'] == d]
        close_v = etf_row['close'].values[0] if len(etf_row) > 0 else 0
        ma20_v = etf['close'][etf['date'] <= d].tail(20).mean()
        gap = (close_v / ma20_v - 1) * 100 if ma20_v > 0 else 0
        print(f"  {d.date()}: ret={item['ret']*100:+.2f}%, "
              f"0050={close_v:.1f}, MA20={ma20_v:.1f}, gap={gap:+.1f}%")

    # ─── 月度分析 ───
    print(f"\n{'=' * 70}")
    print("月度績效 (10d, MA20 filter)")
    print(f"{'=' * 70}")

    all_items = sorted(r20['pass'] + r20['block'], key=lambda x: x['date'])
    pass_set = set(id(x) for x in r20['pass'])
    monthly: dict = {}
    for item in all_items:
        m = item['date'].strftime('%Y-%m')
        if m not in monthly:
            monthly[m] = {'all': [], 'pass': [], 'block': []}
        monthly[m]['all'].append(item['ret'])
        lbl = 'pass' if id(item) in pass_set else 'block'
        monthly[m][lbl].append(item['ret'])

    print(f"  {'月份':>7} | {'全部':>8} | {'通過':>8} | {'被擋':>8} | 擋/全")
    print(f"  {'-'*7}-+-{'-'*8}-+-{'-'*8}-+-{'-'*8}-+------")
    for m in sorted(monthly.keys()):
        d = monthly[m]
        a = np.mean(d['all']) * 100 if d['all'] else 0
        p = np.mean(d['pass']) * 100 if d['pass'] else 0
        b = np.mean(d['block']) * 100 if d['block'] else 0
        nb = len(d['block'])
        na = len(d['all'])
        print(f"  {m:>7} | {a:+7.2f}% | {p:+7.2f}% | {b:+7.2f}% | {nb}/{na}")

    # ─── Benchmark ───
    print(f"\n{'=' * 70}")
    print("Benchmark: 0050 本身 10d/20d 報酬")
    print(f"{'=' * 70}")

    regime_20 = calc_regime(etf, 20)
    sig_dates = set(sig['date'].unique())

    for h in [10, 20]:
        etf_c = etf.copy()
        etf_c['fwd'] = etf_c['close'].shift(-h) / etf_c['close'] - 1
        etf_c = etf_c.dropna(subset=['fwd'])
        es = etf_c[etf_c['date'].isin(sig_dates)].copy()
        es['regime'] = es['date'].map(regime_20).fillna(True)

        p = es[es['regime']]['fwd']
        b = es[~es['regime']]['fwd']
        print(f"\n  {h}d:")
        print(f"    全部: mean={es['fwd'].mean()*100:+.2f}%, n={len(es)}")
        if len(p) > 0:
            print(f"    通過: mean={p.mean()*100:+.2f}%, n={len(p)}")
        if len(b) > 0:
            print(f"    被擋: mean={b.mean()*100:+.2f}%, n={len(b)}")

    # ─── 結論 ───
    print(f"\n{'=' * 70}")
    print("結論")
    print(f"{'=' * 70}")

    fwd20 = calc_fwd_ret(prices, 20)
    for h, fwd_h in [(10, fwd10), (20, fwd20)]:
        r = backtest(etf, sig, fwd_h, 20)
        if r['pass'] and r['block']:
            pm = np.mean([x['ret'] for x in r['pass']]) * 100
            bm = np.mean([x['ret'] for x in r['block']]) * 100
            bn = len(r['block'])
            tn = bn + len(r['pass'])
            bp = bn / tn * 100
            print(f"\n  {h}d 前瞻: 通過={pm:+.2f}%, 被擋={bm:+.2f}%, "
                  f"差異={pm-bm:+.2f}pp, 被擋率={bp:.0f}%")


if __name__ == '__main__':
    main()

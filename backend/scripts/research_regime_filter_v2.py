"""
Regime Filter 多角度分析 (v2)
============================
不只看平均報酬，從以下角度驗證：

1. 樣本偏差：2025-09~2026-04 是否為單邊牛市？
2. 尾部風險：被擋日的最大虧損 vs 通過日
3. 下跌保護：被擋日中「真正下跌」的比例
4. 深度分層：0050 離 MA20 越遠，信號品質是否越差？
5. 連續被擋天數：初次跌破 vs 持續跌破行為差異
6. 時序穩定性：前半 vs 後半樣本一致嗎？
7. 0050 自身 regime 效果（排除模型，純大盤擇時）
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


def load_data():
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
        ).filter(AlphaSignalHistory.direction == 'long').all()

        sig = pd.DataFrame(sig_rows, columns=['date', 'stock_id', 'trigger_count', 'odds_ratio'])
        sig['date'] = pd.to_datetime(sig['date'])
        sig['trigger_count'] = sig['trigger_count'].astype(float)
        sig['odds_ratio'] = sig['odds_ratio'].astype(float).fillna(1.0)
        sig['score'] = sig['trigger_count'] * sig['odds_ratio']
        sig = sig.sort_values('score', ascending=False).drop_duplicates(
            subset=['date', 'stock_id'], keep='first'
        ).sort_values(['date', 'score'], ascending=[True, False])

        prices = db.query(
            StockPrice.stock_id, StockPrice.date, StockPrice.close
        ).filter(StockPrice.date >= '2025-08-01').all()
        prices = pd.DataFrame(prices, columns=['stock_id', 'date', 'close'])
        prices['close'] = prices['close'].astype(float)
        prices['date'] = pd.to_datetime(prices['date'])

        return etf, sig, prices
    finally:
        db.close()


def calc_regime(etf, window=20):
    ma = etf['close'].rolling(window).mean()
    return pd.Series((etf['close'] > ma).values, index=etf['date'])


def calc_gap(etf, window=20):
    """0050 相對 MA20 的 gap%"""
    ma = etf['close'].rolling(window).mean()
    gap = (etf['close'] / ma - 1) * 100
    return pd.Series(gap.values, index=etf['date'])


def calc_fwd(prices, horizon):
    pivot = prices.pivot_table(index='date', columns='stock_id', values='close').sort_index()
    return pivot.shift(-horizon) / pivot - 1


def get_daily_ret(sig, fwd, top_n=TOP_N):
    """每日 Top N 的平均前瞻報酬"""
    records = []
    for d in sorted(sig['date'].unique()):
        if d not in fwd.index:
            continue
        day_sig = sig[sig['date'] == d].head(top_n)
        rets = []
        for _, row in day_sig.iterrows():
            sid = row['stock_id']
            if sid in fwd.columns:
                r = fwd.loc[d, sid]
                if pd.notna(r):
                    rets.append(r)
        if rets:
            records.append({'date': d, 'ret': np.mean(rets), 'n': len(rets)})
    return pd.DataFrame(records)


def section(title):
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print(f"{'=' * 70}")


def main():
    print("#" * 70)
    print("# Regime Filter 多角度深入分析")
    print("#" * 70)

    etf, sig, prices = load_data()
    regime = calc_regime(etf, 20)
    gap = calc_gap(etf, 20)

    fwd20 = calc_fwd(prices, 20)
    fwd10 = calc_fwd(prices, 10)

    daily20 = get_daily_ret(sig, fwd20)
    daily10 = get_daily_ret(sig, fwd10)

    # 加 regime / gap 到 daily
    for df in [daily20, daily10]:
        df['regime'] = df['date'].map(regime).fillna(True)
        df['gap'] = df['date'].map(gap).fillna(0)

    # ─── 1. 樣本偏差：這段期間是單邊牛市嗎？ ───
    section("1. 樣本偏差檢查：0050 走勢")

    sig_start = sig['date'].min()
    sig_end = sig['date'].max()
    etf_period = etf[(etf['date'] >= sig_start) & (etf['date'] <= sig_end)]
    start_p = etf_period['close'].iloc[0]
    end_p = etf_period['close'].iloc[-1]
    total_ret = (end_p / start_p - 1) * 100
    max_p = etf_period['close'].max()
    min_p = etf_period['close'].min()
    max_dd = (min_p / max_p - 1) * 100

    print(f"  期間: {sig_start.date()} ~ {sig_end.date()}")
    print(f"  0050: {start_p:.1f} → {end_p:.1f} ({total_ret:+.1f}%)")
    print(f"  最高: {max_p:.1f}, 最低: {min_p:.1f}")
    print(f"  最大回撤: {max_dd:.1f}%")
    print(f"  ⚠️  樣本內 0050 漲幅 {total_ret:+.1f}%，需注意均值回歸偏差")

    # 各季度方向
    print(f"\n  季度走勢:")
    for q_start, q_end, label in [
        ('2025-09-01', '2025-11-30', '2025Q3末~Q4'),
        ('2025-12-01', '2026-02-28', '2025Q4~2026Q1'),
        ('2026-03-01', '2026-04-07', '2026Q1末~Q2'),
    ]:
        qs = etf[(etf['date'] >= q_start) & (etf['date'] <= q_end)]
        if len(qs) >= 2:
            qr = (qs['close'].iloc[-1] / qs['close'].iloc[0] - 1) * 100
            print(f"    {label}: {qs['close'].iloc[0]:.1f}→{qs['close'].iloc[-1]:.1f} ({qr:+.1f}%)")

    # ─── 2. 尾部風險 ───
    section("2. 尾部風險分析 (20d)")

    pass_df = daily20[daily20['regime']]
    block_df = daily20[~daily20['regime']]

    for label, df in [("通過", pass_df), ("被擋", block_df)]:
        if len(df) == 0:
            print(f"  {label}: 無資料")
            continue
        r = df['ret']
        p5 = np.percentile(r, 5) * 100
        p25 = np.percentile(r, 25) * 100
        p75 = np.percentile(r, 75) * 100
        p95 = np.percentile(r, 95) * 100
        worst = r.min() * 100
        best = r.max() * 100
        loss_days = (r < 0).sum()
        big_loss = (r < -0.05).sum()  # > 5% 虧損
        print(f"  {label} (n={len(df)}):")
        print(f"    P5={p5:+.1f}%, P25={p25:+.1f}%, P75={p75:+.1f}%, P95={p95:+.1f}%")
        print(f"    最差={worst:+.1f}%, 最佳={best:+.1f}%")
        print(f"    虧損天: {loss_days}/{len(df)} ({loss_days/len(df)*100:.0f}%)")
        print(f"    大虧(>5%): {big_loss}/{len(df)} ({big_loss/len(df)*100:.0f}%)")

    # ─── 3. 被擋日中的「真正下跌」vs「反彈」 ───
    section("3. 被擋日細分：初期下跌 vs 觸底反彈")

    if len(block_df) > 0:
        # 根據 gap 深度區分
        shallow = block_df[block_df['gap'] > -2]  # 剛跌破
        deep = block_df[block_df['gap'] <= -2]     # 深度跌破

        for label, df in [("淺跌(gap>-2%)", shallow), ("深跌(gap<=-2%)", deep)]:
            if len(df) == 0:
                print(f"  {label}: 無資料")
                continue
            r = df['ret']
            print(f"  {label} (n={len(df)}): mean={r.mean()*100:+.2f}%, "
                  f"wr={( r > 0).mean()*100:.0f}%, worst={r.min()*100:+.1f}%")

    # ─── 4. Gap 分層分析 ───
    section("4. 0050 相對 MA20 的 gap 分層 (20d)")

    bins = [(-999, -3), (-3, -1), (-1, 0), (0, 1), (1, 3), (3, 999)]
    labels = ['<-3%', '-3~-1%', '-1~0%', '0~+1%', '+1~+3%', '>+3%']

    for (lo, hi), lbl in zip(bins, labels):
        subset = daily20[(daily20['gap'] > lo) & (daily20['gap'] <= hi)]
        if len(subset) == 0:
            print(f"  gap {lbl:>8}: 無資料")
            continue
        r = subset['ret']
        print(f"  gap {lbl:>8}: n={len(subset):>3}, mean={r.mean()*100:+.2f}%, "
              f"wr={( r > 0).mean()*100:.0f}%, worst={r.min()*100:+.1f}%")

    # ─── 5. 連續被擋天數分析 ───
    section("5. 連續被擋天數分析 (10d)")

    if len(daily10) > 0:
        daily10_sorted = daily10.sort_values('date')
        # 標記連續 block 的天數
        block_streaks = []
        current_streak = 0
        for _, row in daily10_sorted.iterrows():
            if not row['regime']:
                current_streak += 1
            else:
                current_streak = 0
            block_streaks.append(current_streak)
        daily10_sorted = daily10_sorted.copy()
        daily10_sorted['streak'] = block_streaks

        block_only = daily10_sorted[~daily10_sorted['regime']]
        if len(block_only) > 0:
            early = block_only[block_only['streak'] <= 3]  # 前 3 天
            late = block_only[block_only['streak'] > 3]    # 第 4 天起

            for label, df in [("跌破初期(1-3天)", early), ("持續跌破(>3天)", late)]:
                if len(df) == 0:
                    print(f"  {label}: 無資料")
                    continue
                r = df['ret']
                print(f"  {label}: n={len(df)}, mean={r.mean()*100:+.2f}%, "
                      f"wr={(r > 0).mean()*100:.0f}%, worst={r.min()*100:+.1f}%")

    # ─── 6. 時序穩定性 ───
    section("6. 時序穩定性 (20d，前半 vs 後半)")

    if len(daily20) > 10:
        mid = len(daily20) // 2
        first_half = daily20.iloc[:mid]
        second_half = daily20.iloc[mid:]

        for label, df in [("前半", first_half), ("後半", second_half)]:
            p = df[df['regime']]
            b = df[~df['regime']]
            print(f"  {label} ({df['date'].min().date()} ~ {df['date'].max().date()}):")
            if len(p) > 0:
                print(f"    通過: n={len(p)}, mean={p['ret'].mean()*100:+.2f}%, wr={(p['ret']>0).mean()*100:.0f}%")
            if len(b) > 0:
                print(f"    被擋: n={len(b)}, mean={b['ret'].mean()*100:+.2f}%, wr={(b['ret']>0).mean()*100:.0f}%")
            else:
                print(f"    被擋: 無")

    # ─── 7. 如果用 MA20 做「減碼」而非「停止」 ───
    section("7. 替代方案：regime 影響推薦數量而非停止")

    print("  模擬：0050 > MA20 推 5 檔，< MA20 推 3 檔")
    daily20_full5 = get_daily_ret(sig, fwd20, top_n=5)
    daily20_top3 = get_daily_ret(sig, fwd20, top_n=3)

    daily20_full5['regime'] = daily20_full5['date'].map(regime).fillna(True)
    daily20_top3['regime'] = daily20_top3['date'].map(regime).fillna(True)

    # 混合：pass 用 top5，block 用 top3
    mixed = pd.concat([
        daily20_full5[daily20_full5['regime']],
        daily20_top3[~daily20_top3['regime']],
    ]).sort_values('date')

    for label, df in [
        ("全停(目前)", daily20_full5[daily20_full5['regime']]),
        ("全推(無filter)", daily20_full5),
        ("減碼(pass→5, block→3)", mixed),
    ]:
        if len(df) == 0:
            continue
        r = df['ret']
        cum = (1 + r).prod() - 1
        print(f"  {label:30}: n={len(df)}, mean={r.mean()*100:+.2f}%, "
              f"wr={(r>0).mean()*100:.0f}%, cum={cum*100:+.1f}%")

    # ─── 8. 純大盤擇時效果（排除模型，只看 0050）───
    section("8. 純大盤擇時 (排除模型，只看 0050)")

    etf_c = etf.copy()
    for h in [10, 20]:
        etf_c[f'fwd{h}'] = etf_c['close'].shift(-h) / etf_c['close'] - 1

    etf_c['regime'] = etf_c['date'].map(regime)
    etf_c = etf_c.dropna(subset=['regime'])
    sig_dates = set(sig['date'].unique())
    etf_sig = etf_c[etf_c['date'].isin(sig_dates)]

    for h in [10, 20]:
        col = f'fwd{h}'
        valid = etf_sig.dropna(subset=[col])
        p = valid[valid['regime']]
        b = valid[~valid['regime']]
        print(f"\n  0050 {h}d 前瞻:")
        if len(p) > 0:
            print(f"    通過: n={len(p)}, mean={p[col].mean()*100:+.2f}%, wr={(p[col]>0).mean()*100:.0f}%")
        if len(b) > 0:
            print(f"    被擋: n={len(b)}, mean={b[col].mean()*100:+.2f}%, wr={(b[col]>0).mean()*100:.0f}%")
        if len(p) > 0 and len(b) > 0:
            print(f"    差異: {(p[col].mean()-b[col].mean())*100:+.2f}pp")

    # ─── 9. 如果歷史有真正的熊市呢？(回看更長 0050) ───
    section("9. 0050 長期 regime 統計 (全部歷史)")

    regime_long = calc_regime(etf, 20)
    total_days = len(regime_long.dropna())
    below_days = (~regime_long.dropna()).sum()
    print(f"  0050 全歷史: {total_days} 天, 低於 MA20: {below_days} 天 ({below_days/total_days*100:.0f}%)")

    # 年度統計
    etf_r = etf.copy()
    etf_r['regime'] = etf_r['date'].map(regime_long)
    etf_r['year'] = etf_r['date'].dt.year
    etf_r = etf_r.dropna(subset=['regime'])

    print(f"\n  年度低於 MA20 天數:")
    for year in sorted(etf_r['year'].unique()):
        yr = etf_r[etf_r['year'] == year]
        below = (~yr['regime']).sum()
        total = len(yr)
        print(f"    {year}: {below}/{total} 天 ({below/total*100:.0f}%)")

    # 長期 0050 被擋日的 20d forward return
    etf_r['fwd20'] = etf_r['close'].shift(-20) / etf_r['close'] - 1
    valid_r = etf_r.dropna(subset=['fwd20'])
    p_long = valid_r[valid_r['regime']]
    b_long = valid_r[~valid_r['regime']]

    print(f"\n  0050 全歷史 20d 前瞻 (含熊市):")
    if len(p_long) > 0:
        print(f"    通過: n={len(p_long)}, mean={p_long['fwd20'].mean()*100:+.2f}%, "
              f"wr={(p_long['fwd20']>0).mean()*100:.0f}%")
    if len(b_long) > 0:
        print(f"    被擋: n={len(b_long)}, mean={b_long['fwd20'].mean()*100:+.2f}%, "
              f"wr={(b_long['fwd20']>0).mean()*100:.0f}%")

    # ─── 總結 ───
    section("總結與建議")

    print("""
  發現：
  1. 樣本期間（2025-09~2026-04）0050 漲幅顯著，被擋日多為短暫回調
  2. 需要比較全歷史（含熊市）0050 regime 效果才能公平評估
  3. 關注被擋日的尾部風險和勝率，而非只看平均報酬

  上面的數據會告訴我們應該怎麼做。
""")


if __name__ == '__main__':
    main()

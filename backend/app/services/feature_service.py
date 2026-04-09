"""
原子指標特徵庫服務 (Feature Store Service)

負責預計算全市場技術指標 + 基本面快照，寫入 stock_features 表。
供 Alpha Miner 回測引擎與前端查詢使用。
"""
import logging
from datetime import date, timedelta
from typing import Optional

import pandas as pd
import numpy as np
from sqlalchemy.orm import Session
from sqlalchemy import func, delete

from app.models.stock_price import StockPrice
from app.models.stock_feature import StockFeature
from app.models.stock_fundamental import StockFundamental
from app.models.stock_chip_data import StockChipData
from app.models.etf_flow import ETFFlow
from app.models.user import Stock
from app.services.indicator_service import IndicatorService

logger = logging.getLogger(__name__)

# 技術指標計算所需的暖機天數（MA60 需要至少 60 天）
WARMUP_DAYS = 90


class FeatureService:
    """原子指標特徵庫計算與儲存服務"""

    @staticmethod
    def compute_daily(db: Session, target_date: Optional[date] = None):
        """計算單日全市場特徵快照並寫入 stock_features

        Args:
            db: 資料庫 Session
            target_date: 目標日期，預設為今日
        """
        if target_date is None:
            target_date = date.today()

        logger.info(f"[FeatureService] 開始計算 {target_date} 的特徵快照...")

        # 1. 讀取 target_date 往前 WARMUP_DAYS 的全市場價格
        start_date = target_date - timedelta(days=WARMUP_DAYS + 30)  # 多抓一個月的緩衝（假日 & 週末）
        
        prices = db.query(StockPrice).filter(
            StockPrice.date >= start_date,
            StockPrice.date <= target_date
        ).all()

        if not prices:
            logger.warning(f"[FeatureService] {target_date} 無任何價格資料")
            return 0

        # 2. 轉為 DataFrame
        df = pd.DataFrame([{
            'stock_id': p.stock_id,
            'date': p.date,
            'open': p.open,
            'high': p.high,
            'low': p.low,
            'close': p.close,
            'volume': p.volume or 0,
        } for p in prices])

        if df.empty:
            return 0

        # 3. 計算所有技術指標（復用 IndicatorService）
        df = IndicatorService.attach_indicators(df)

        # 4. 額外計算 bias5, bias10, vol_ma5, vol_ratio, bb_pctb, change_pct
        df['bias5'] = IndicatorService.calculate_bias_vec(df, 5)
        df['bias10'] = IndicatorService.calculate_bias_vec(df, 10)
        df['rsi2'] = IndicatorService.calculate_rsi_vec(df, 2)
        df['vol_ma5'] = IndicatorService.calculate_ma_vec(df, 5, column='volume')
        df['vol_ratio'] = df['volume'] / df['vol_ma5'].replace(0, np.nan)

        # Bollinger %B = (close - bb_lower) / (bb_upper - bb_lower)
        bb_range = df['bb_upper'] - df['bb_lower']
        df['bb_pctb'] = (df['close'] - df['bb_lower']) / bb_range.replace(0, np.nan)

        # 日漲跌幅
        df['change_pct'] = df.groupby('stock_id')['close'].pct_change() * 100

        # 技術面新因子（Phase 5B）
        df['high20'] = df.groupby('stock_id')['high'].transform(lambda x: x.rolling(20).max())
        df['price_vs_high20'] = (df['close'] - df['high20']) / df['high20'].replace(0, np.nan)
        df['ma_trend'] = ((df['ma5'] > df['ma10']) & (df['ma10'] > df['ma20'])).astype(float)
        df.loc[df['ma5'].isna() | df['ma10'].isna() | df['ma20'].isna(), 'ma_trend'] = np.nan

        # ATR（Phase 7）
        df['atr20'] = IndicatorService.calculate_atr_vec(df, 20)
        df['atr_pct'] = df['atr20'] / df['close'].replace(0, np.nan) * 100

        # 特異波動率（Phase 8）：日報酬減去市場中位數後的 20 日標準差
        daily_ret = df.groupby('stock_id')['close'].pct_change()
        market_median_ret = df.groupby('date')['change_pct'].transform('median')
        df['_excess_ret'] = df['change_pct'] - market_median_ret
        df['ivol_20d'] = df.groupby('stock_id')['_excess_ret'].transform(
            lambda x: x.rolling(20, min_periods=10).std()
        )

        # 背離因子（Phase 10）：RSI+MACD 價格相關性平均
        df['divergence_avg'] = IndicatorService.calculate_divergence_avg_vec(df, 20)

        # 流動性因子（Phase 11）：Amihud 非流動性
        # |ret| / dollar_volume 的 20 日均值，取 log1p 壓縮極端值
        df['_dollar_vol'] = df['close'] * df['volume']
        df['_abs_ret_over_dvol'] = daily_ret.abs() / df['_dollar_vol'].replace(0, np.nan)
        df['amihud_20d'] = df.groupby('stock_id')['_abs_ret_over_dvol'].transform(
            lambda x: x.rolling(20, min_periods=15).mean()
        )
        df['log_amihud_20d'] = np.log1p(df['amihud_20d'] * 1e8)

        # 產業相對強度（Phase 6A）：需在全市場 df 上計算再切 target_date
        df['ret20'] = df.groupby('stock_id')['close'].pct_change(20) * 100

        # 5. 只取 target_date 當日的資料
        target_df = df[df['date'] == target_date].copy()

        if target_df.empty:
            logger.warning(f"[FeatureService] {target_date} 非交易日或無資料")
            return 0

        # 計算 sector_rs：個股 20 日報酬 - 同產業中位數
        industry_map = {r.stock_id: r.industry for r in db.query(Stock.stock_id, Stock.industry).all()}
        target_df['industry'] = target_df['stock_id'].map(industry_map)
        target_df['sector_median_ret20'] = target_df.groupby('industry')['ret20'].transform('median')
        target_df['sector_rs'] = target_df['ret20'] - target_df['sector_median_ret20']

        # 市場狀態（Phase 7）
        valid_ma20 = target_df.dropna(subset=['ma20', 'close'])
        if len(valid_ma20) > 0:
            breadth = float((valid_ma20['close'] > valid_ma20['ma20']).mean())
        else:
            breadth = None
        target_df['market_breadth'] = breadth

        median_ret20 = target_df['ret20'].median()
        target_df['market_trend'] = 1.0 if (pd.notna(median_ret20) and median_ret20 > 0) else 0.0

        # 6. Left join 基本面快照
        fundamentals = db.query(StockFundamental).all()
        fund_map = {f.stock_id: f for f in fundamentals}

        target_df['yield_rate'] = target_df['stock_id'].map(
            lambda sid: getattr(fund_map.get(sid), 'yield_rate', None))
        target_df['roe'] = target_df['stock_id'].map(
            lambda sid: getattr(fund_map.get(sid), 'roe_latest', None))
        target_df['pb_ratio'] = target_df['stock_id'].map(
            lambda sid: getattr(fund_map.get(sid), 'pb_ratio', None))
        target_df['revenue_yoy'] = target_df['stock_id'].map(
            lambda sid: getattr(fund_map.get(sid), 'revenue_growth_yoy', None))

        # 6a-2. 營收衍生因子（rev_surprise, rev_accel）
        from app.models.stock_revenue import StockMonthlyRevenue
        rev_rows = db.query(StockMonthlyRevenue).filter(
            StockMonthlyRevenue.revenue > 0
        ).order_by(StockMonthlyRevenue.stock_id, StockMonthlyRevenue.year, StockMonthlyRevenue.month).all()

        if rev_rows:
            rev_data: dict = {}  # {stock_id: [(year, month, revenue, yoy), ...]}
            for r in rev_rows:
                rev_data.setdefault(r.stock_id, []).append((r.year, r.month, r.revenue, r.revenue_yoy))

            surprise_map: dict = {}
            accel_map: dict = {}
            for sid, records in rev_data.items():
                if len(records) < 2:
                    continue
                # 最新一筆營收
                latest = records[-1]
                rev_val = latest[2]
                yoy_val = latest[3]
                # 近3個月平均（不含本月）
                prev_revs = [r[2] for r in records[-4:-1] if r[2] and r[2] > 0]
                if prev_revs:
                    ma3 = sum(prev_revs) / len(prev_revs)
                    if ma3 > 0:
                        surprise_map[sid] = (rev_val - ma3) / ma3 * 100
                # 加速度：本月 YoY - 上月 YoY
                if yoy_val is not None and len(records) >= 2:
                    prev_yoy = records[-2][3]
                    if prev_yoy is not None:
                        accel_map[sid] = yoy_val - prev_yoy

            target_df['rev_surprise'] = target_df['stock_id'].map(surprise_map)
            target_df['rev_accel'] = target_df['stock_id'].map(accel_map)
        else:
            target_df['rev_surprise'] = None
            target_df['rev_accel'] = None

        # 6b. Left join 籌碼面（Phase 4B）
        chip_start = target_date - timedelta(days=30)
        chip_rows = db.query(StockChipData).filter(
            StockChipData.date >= chip_start,
            StockChipData.date <= target_date
        ).all()
        chip_df = FeatureService._build_chip_features(chip_rows, target_date)

        if not chip_df.empty:
            target_df = target_df.merge(chip_df, on='stock_id', how='left')
            # 有收盤價但沒法人資料的股票 → 法人買賣=0（沒有法人交易，非資料缺失）
            # 注意：foreign_hold_pct / foreign_hold_chg_5d 不填 0（持股比率無法推斷）
            chip_zero_fill = [
                'foreign_net_buy', 'foreign_buy_5d', 'foreign_buy_10d', 'foreign_buy_20d',
                'trust_net_buy', 'trust_buy_5d', 'trust_buy_10d', 'trust_buy_20d',
                'dealer_net_buy', 'dealer_buy_5d', 'dealer_buy_10d', 'dealer_buy_20d',
            ]
            for col in chip_zero_fill:
                if col in target_df.columns:
                    target_df[col] = target_df[col].fillna(0)
        else:
            for col in ('foreign_net_buy', 'foreign_buy_5d',
                        'foreign_buy_10d', 'foreign_buy_20d',
                        'trust_net_buy', 'trust_buy_5d',
                        'trust_buy_10d', 'trust_buy_20d',
                        'margin_chg_5d', 'short_chg_5d',
                        'dealer_net_buy', 'dealer_buy_5d',
                        'dealer_buy_10d', 'dealer_buy_20d',
                        'foreign_hold_pct', 'foreign_hold_chg_5d'):
                target_df[col] = None

        # 6c. 帶入近5日 ETF 淨申購（0050，單位：萬張）
        from datetime import timedelta as _td
        etf_start = target_date - _td(days=10)
        etf_rows = (
            db.query(ETFFlow)
            .filter(ETFFlow.etf_id == '0050', ETFFlow.date >= etf_start, ETFFlow.date <= target_date)
            .order_by(ETFFlow.date)
            .all()
        )
        etf_net_5d = sum(r.net_flow for r in etf_rows[-5:]) / 10000 if etf_rows else None
        target_df['etf_net_flow_5d'] = etf_net_5d

        # 7. 去重（同一 stock_id 取最後一筆，避免 UniqueViolation）
        target_df = target_df.drop_duplicates(subset=['stock_id'], keep='last')

        # 8. 刪除當日已存在的記錄（upsert 邏輯）
        db.execute(
            delete(StockFeature).where(StockFeature.date == target_date)
        )

        # 9. 批量寫入
        records = []
        for _, row in target_df.iterrows():
            records.append(StockFeature(
                stock_id=row['stock_id'],
                date=row['date'],
                close=_safe_float(row.get('close')),
                change_pct=_safe_float(row.get('change_pct')),
                ma5=_safe_float(row.get('ma5')),
                ma10=_safe_float(row.get('ma10')),
                ma20=_safe_float(row.get('ma20')),
                ma60=_safe_float(row.get('ma60')),
                bias5=_safe_float(row.get('bias5')),
                bias10=_safe_float(row.get('bias10')),
                bias20=_safe_float(row.get('bias20')),
                rsi14=_safe_float(row.get('rsi14')),
                rsi2=_safe_float(row.get('rsi2')),
                k=_safe_float(row.get('k')),
                d=_safe_float(row.get('d')),
                macd_dif=_safe_float(row.get('macd_dif')),
                macd_dea=_safe_float(row.get('macd_dea')),
                macd_osc=_safe_float(row.get('macd_osc')),
                bb_upper=_safe_float(row.get('bb_upper')),
                bb_lower=_safe_float(row.get('bb_lower')),
                bb_pctb=_safe_float(row.get('bb_pctb')),
                volume=int(row['volume']) if pd.notna(row.get('volume')) else None,
                vol_ma5=_safe_float(row.get('vol_ma5')),
                vol_ratio=_safe_float(row.get('vol_ratio')),
                yield_rate=_safe_float(row.get('yield_rate')),
                roe=_safe_float(row.get('roe')),
                pb_ratio=_safe_float(row.get('pb_ratio')),
                revenue_yoy=_safe_float(row.get('revenue_yoy')),
                rev_surprise=_safe_float(row.get('rev_surprise')),
                rev_accel=_safe_float(row.get('rev_accel')),
                foreign_net_buy=_safe_float(row.get('foreign_net_buy')),
                foreign_buy_5d=_safe_float(row.get('foreign_buy_5d')),
                trust_net_buy=_safe_float(row.get('trust_net_buy')),
                trust_buy_5d=_safe_float(row.get('trust_buy_5d')),
                margin_chg_5d=_safe_float(row.get('margin_chg_5d')),
                short_chg_5d=_safe_float(row.get('short_chg_5d')),
                dealer_net_buy=_safe_float(row.get('dealer_net_buy')),
                dealer_buy_5d=_safe_float(row.get('dealer_buy_5d')),
                price_vs_high20=_safe_float(row.get('price_vs_high20')),
                ma_trend=_safe_float(row.get('ma_trend')),
                sector_rs=_safe_float(row.get('sector_rs')),
                foreign_hold_pct=_safe_float(row.get('foreign_hold_pct')),
                foreign_hold_chg_5d=_safe_float(row.get('foreign_hold_chg_5d')),
                etf_net_flow_5d=_safe_float(row.get('etf_net_flow_5d')),
                foreign_buy_10d=_safe_float(row.get('foreign_buy_10d')),
                foreign_buy_20d=_safe_float(row.get('foreign_buy_20d')),
                trust_buy_10d=_safe_float(row.get('trust_buy_10d')),
                trust_buy_20d=_safe_float(row.get('trust_buy_20d')),
                dealer_buy_10d=_safe_float(row.get('dealer_buy_10d')),
                dealer_buy_20d=_safe_float(row.get('dealer_buy_20d')),
                atr20=_safe_float(row.get('atr20')),
                atr_pct=_safe_float(row.get('atr_pct')),
                ivol_20d=_safe_float(row.get('ivol_20d')),
                log_amihud_20d=_safe_float(row.get('log_amihud_20d')),
                divergence_avg=_safe_float(row.get('divergence_avg')),
                market_breadth=_safe_float(row.get('market_breadth')),
                market_trend=_safe_float(row.get('market_trend')),
            ))

        if records:
            db.bulk_save_objects(records)
            db.commit()

        logger.info(f"[FeatureService] {target_date}: 寫入 {len(records)} 筆特徵")
        return len(records)

    @staticmethod
    def backfill(db: Session, start_date: date, end_date: date):
        """批量回補歷史特徵

        策略：一次性讀取全部價格 → 向量化計算 → 按日分批寫入
        """
        logger.info(f"[FeatureService] 開始回補特徵: {start_date} ~ {end_date}")

        # 讀取需要的所有價格（包含暖機期）
        warmup_start = start_date - timedelta(days=WARMUP_DAYS + 30)

        prices = db.query(StockPrice).filter(
            StockPrice.date >= warmup_start,
            StockPrice.date <= end_date
        ).all()

        if not prices:
            logger.warning("[FeatureService] 回補期間無價格資料")
            return 0

        df = pd.DataFrame([{
            'stock_id': p.stock_id,
            'date': p.date,
            'open': p.open,
            'high': p.high,
            'low': p.low,
            'close': p.close,
            'volume': p.volume or 0,
        } for p in prices])

        # 一次性計算全部指標
        df = IndicatorService.attach_indicators(df)
        df['bias5'] = IndicatorService.calculate_bias_vec(df, 5)
        df['bias10'] = IndicatorService.calculate_bias_vec(df, 10)
        df['rsi2'] = IndicatorService.calculate_rsi_vec(df, 2)
        df['vol_ma5'] = IndicatorService.calculate_ma_vec(df, 5, column='volume')
        df['vol_ratio'] = df['volume'] / df['vol_ma5'].replace(0, np.nan)
        bb_range = df['bb_upper'] - df['bb_lower']
        df['bb_pctb'] = (df['close'] - df['bb_lower']) / bb_range.replace(0, np.nan)
        df['change_pct'] = df.groupby('stock_id')['close'].pct_change() * 100

        # 技術面新因子（Phase 5B）
        df['high20'] = df.groupby('stock_id')['high'].transform(lambda x: x.rolling(20).max())
        df['price_vs_high20'] = (df['close'] - df['high20']) / df['high20'].replace(0, np.nan)
        df['ma_trend'] = ((df['ma5'] > df['ma10']) & (df['ma10'] > df['ma20'])).astype(float)
        df.loc[df['ma5'].isna() | df['ma10'].isna() | df['ma20'].isna(), 'ma_trend'] = np.nan

        # ATR（Phase 7）
        df['atr20'] = IndicatorService.calculate_atr_vec(df, 20)
        df['atr_pct'] = df['atr20'] / df['close'].replace(0, np.nan) * 100

        # 特異波動率（Phase 8）：日報酬減去市場中位數後的 20 日標準差
        market_median_ret = df.groupby('date')['change_pct'].transform('median')
        df['_excess_ret'] = df['change_pct'] - market_median_ret
        df['ivol_20d'] = df.groupby('stock_id')['_excess_ret'].transform(
            lambda x: x.rolling(20, min_periods=10).std()
        )

        # 背離因子（Phase 10）：RSI+MACD 價格相關性平均
        df['divergence_avg'] = IndicatorService.calculate_divergence_avg_vec(df, 20)

        # 流動性因子（Phase 11）：Amihud 非流動性
        _daily_ret = df.groupby('stock_id')['close'].pct_change()
        df['_dollar_vol'] = df['close'] * df['volume']
        df['_abs_ret_over_dvol'] = _daily_ret.abs() / df['_dollar_vol'].replace(0, np.nan)
        df['amihud_20d'] = df.groupby('stock_id')['_abs_ret_over_dvol'].transform(
            lambda x: x.rolling(20, min_periods=15).mean()
        )
        df['log_amihud_20d'] = np.log1p(df['amihud_20d'] * 1e8)

        # 產業相對強度（Phase 6A）：在全市場 df 上向量化計算
        df['ret20'] = df.groupby('stock_id')['close'].pct_change(20) * 100
        industry_map = {r.stock_id: r.industry for r in db.query(Stock.stock_id, Stock.industry).all()}
        df['industry'] = df['stock_id'].map(industry_map)
        df['sector_rs'] = df['ret20'] - df.groupby(['date', 'industry'])['ret20'].transform('median')

        # 只取回補期間的資料
        mask = (df['date'] >= start_date) & (df['date'] <= end_date)
        backfill_df = df[mask].copy()

        # 基本面快照（統一用最新值）
        fundamentals = db.query(StockFundamental).all()
        fund_map = {f.stock_id: f for f in fundamentals}

        backfill_df['yield_rate'] = backfill_df['stock_id'].map(
            lambda sid: getattr(fund_map.get(sid), 'yield_rate', None))
        backfill_df['roe'] = backfill_df['stock_id'].map(
            lambda sid: getattr(fund_map.get(sid), 'roe_latest', None))
        backfill_df['pb_ratio'] = backfill_df['stock_id'].map(
            lambda sid: getattr(fund_map.get(sid), 'pb_ratio', None))
        backfill_df['revenue_yoy'] = backfill_df['stock_id'].map(
            lambda sid: getattr(fund_map.get(sid), 'revenue_growth_yoy', None))

        # 營收衍生因子（rev_surprise, rev_accel）
        from app.models.stock_revenue import StockMonthlyRevenue
        rev_rows = db.query(StockMonthlyRevenue).filter(
            StockMonthlyRevenue.revenue > 0
        ).order_by(StockMonthlyRevenue.stock_id, StockMonthlyRevenue.year, StockMonthlyRevenue.month).all()

        surprise_map: dict = {}
        accel_map: dict = {}
        if rev_rows:
            rev_data: dict = {}
            for r in rev_rows:
                rev_data.setdefault(r.stock_id, []).append((r.year, r.month, r.revenue, r.revenue_yoy))
            for sid, records in rev_data.items():
                if len(records) < 2:
                    continue
                latest = records[-1]
                rev_val = latest[2]
                yoy_val = latest[3]
                prev_revs = [r[2] for r in records[-4:-1] if r[2] and r[2] > 0]
                if prev_revs:
                    ma3 = sum(prev_revs) / len(prev_revs)
                    if ma3 > 0:
                        surprise_map[sid] = (rev_val - ma3) / ma3 * 100
                if yoy_val is not None and len(records) >= 2:
                    prev_yoy = records[-2][3]
                    if prev_yoy is not None:
                        accel_map[sid] = yoy_val - prev_yoy

        backfill_df['rev_surprise'] = backfill_df['stock_id'].map(surprise_map)
        backfill_df['rev_accel'] = backfill_df['stock_id'].map(accel_map)

        # 籌碼面：讀取回補期間 + 前 10 天的籌碼資料
        chip_warmup = start_date - timedelta(days=30)
        chip_rows = db.query(StockChipData).filter(
            StockChipData.date >= chip_warmup,
            StockChipData.date <= end_date
        ).all()

        # 以 date 為 key 建立籌碼特徵 lookup
        # 注意：_build_chip_features 需要前 5 天資料計算累積指標，傳入完整 chip_all
        chip_by_date: dict = {}
        chip_all = pd.DataFrame()
        if chip_rows:
            chip_all = pd.DataFrame([{
                'stock_id': c.stock_id,
                'date': pd.Timestamp(c.date),
                'foreign_net_buy': c.foreign_net_buy,
                'trust_net_buy': c.trust_net_buy,
                'dealer_net_buy': c.dealer_net_buy,
                'margin_balance': c.margin_balance,
                'short_balance': c.short_balance,
                'foreign_hold_pct': getattr(c, 'foreign_hold_pct', None),
            } for c in chip_rows])
            chip_all = chip_all.sort_values(['stock_id', 'date'])
            # 為每個目標日期建立特徵（傳入完整 chip_all，讓函數自行取 5 天窗口）
            for d in chip_all['date'].unique():
                chip_by_date[d] = FeatureService._build_chip_features(None, d.date(), _chip_df=chip_all)

        # 去除重複的 (stock_id, date)（price data 中可能存在重複來源）
        backfill_df = backfill_df.drop_duplicates(subset=['stock_id', 'date'], keep='first')

        # 初始化籌碼欄位
        for col in ('foreign_net_buy', 'foreign_buy_5d',
                    'foreign_buy_10d', 'foreign_buy_20d',
                    'trust_net_buy', 'trust_buy_5d',
                    'trust_buy_10d', 'trust_buy_20d',
                    'margin_chg_5d', 'short_chg_5d',
                    'dealer_net_buy', 'dealer_buy_5d',
                    'dealer_buy_10d', 'dealer_buy_20d',
                    'foreign_hold_pct', 'foreign_hold_chg_5d'):
            backfill_df[col] = None

        # ETF flow lookup: date → net_flow_5d (rolling 5-day sum ÷ 10000)
        etf_warmup = start_date - timedelta(days=10)
        etf_rows_all = (
            db.query(ETFFlow)
            .filter(ETFFlow.etf_id == '0050', ETFFlow.date >= etf_warmup, ETFFlow.date <= end_date)
            .order_by(ETFFlow.date)
            .all()
        )
        etf_net_by_date: dict = {}
        if etf_rows_all:
            import pandas as _pd
            _etf_df = _pd.DataFrame([(r.date, r.net_flow) for r in etf_rows_all], columns=['date', 'nf'])
            _etf_df = _etf_df.drop_duplicates(subset='date', keep='last')
            _etf_df['net5d'] = _etf_df['nf'].rolling(5, min_periods=1).sum() / 10000
            etf_net_by_date = dict(zip(_etf_df['date'], _etf_df['net5d']))

        # 逐日 UPSERT（先刪當日再寫入），避免整批刪除後中途失敗造成資料永久消失
        total_written = 0
        dates = sorted(backfill_df['date'].unique())

        for i, batch_date in enumerate(dates):
            # 刪除當日已存在的記錄（UPSERT 模式：同一 transaction 內先刪再寫）
            db.execute(delete(StockFeature).where(StockFeature.date == batch_date))

            day_df = backfill_df[backfill_df['date'] == batch_date].copy()

            # 合併當日籌碼特徵（若存在）
            # 先移除預先初始化的 None 欄位，避免 merge 後產生 _x/_y 衝突
            chip_cols = ['foreign_net_buy', 'foreign_buy_5d',
                         'foreign_buy_10d', 'foreign_buy_20d',
                         'trust_net_buy', 'trust_buy_5d',
                         'trust_buy_10d', 'trust_buy_20d',
                         'margin_chg_5d', 'short_chg_5d',
                         'dealer_net_buy', 'dealer_buy_5d',
                         'dealer_buy_10d', 'dealer_buy_20d',
                         'foreign_hold_pct', 'foreign_hold_chg_5d']
            day_df = day_df.drop(columns=[c for c in chip_cols if c in day_df.columns])

            ts_key = pd.Timestamp(batch_date)
            day_chip = chip_by_date.get(ts_key, pd.DataFrame())
            if not day_chip.empty:
                day_df = day_df.merge(day_chip, on='stock_id', how='left')
            else:
                for col in chip_cols:
                    day_df[col] = None

            # ETF 申贖（市場層級指標，全體股票共享）
            _batch_d = batch_date if isinstance(batch_date, date) else batch_date.date()
            day_df['etf_net_flow_5d'] = etf_net_by_date.get(_batch_d)

            # 市場狀態（Phase 7）
            valid_ma20 = day_df.dropna(subset=['ma20', 'close'])
            if len(valid_ma20) > 0:
                breadth = float((valid_ma20['close'] > valid_ma20['ma20']).mean())
            else:
                breadth = None
            day_df['market_breadth'] = breadth

            median_ret20 = day_df['ret20'].median() if 'ret20' in day_df.columns else None
            day_df['market_trend'] = 1.0 if (pd.notna(median_ret20) and median_ret20 > 0) else 0.0

            records = []
            for _, row in day_df.iterrows():
                records.append(StockFeature(
                    stock_id=row['stock_id'],
                    date=row['date'],
                    close=_safe_float(row.get('close')),
                    change_pct=_safe_float(row.get('change_pct')),
                    ma5=_safe_float(row.get('ma5')),
                    ma10=_safe_float(row.get('ma10')),
                    ma20=_safe_float(row.get('ma20')),
                    ma60=_safe_float(row.get('ma60')),
                    bias5=_safe_float(row.get('bias5')),
                    bias10=_safe_float(row.get('bias10')),
                    bias20=_safe_float(row.get('bias20')),
                    rsi14=_safe_float(row.get('rsi14')),
                    rsi2=_safe_float(row.get('rsi2')),
                    k=_safe_float(row.get('k')),
                    d=_safe_float(row.get('d')),
                    macd_dif=_safe_float(row.get('macd_dif')),
                    macd_dea=_safe_float(row.get('macd_dea')),
                    macd_osc=_safe_float(row.get('macd_osc')),
                    bb_upper=_safe_float(row.get('bb_upper')),
                    bb_lower=_safe_float(row.get('bb_lower')),
                    bb_pctb=_safe_float(row.get('bb_pctb')),
                    volume=int(row['volume']) if pd.notna(row.get('volume')) else None,
                    vol_ma5=_safe_float(row.get('vol_ma5')),
                    vol_ratio=_safe_float(row.get('vol_ratio')),
                    yield_rate=_safe_float(row.get('yield_rate')),
                    roe=_safe_float(row.get('roe')),
                    pb_ratio=_safe_float(row.get('pb_ratio')),
                    revenue_yoy=_safe_float(row.get('revenue_yoy')),
                    rev_surprise=_safe_float(row.get('rev_surprise')),
                    rev_accel=_safe_float(row.get('rev_accel')),
                    foreign_net_buy=_safe_float(row.get('foreign_net_buy')),
                    foreign_buy_5d=_safe_float(row.get('foreign_buy_5d')),
                    trust_net_buy=_safe_float(row.get('trust_net_buy')),
                    trust_buy_5d=_safe_float(row.get('trust_buy_5d')),
                    margin_chg_5d=_safe_float(row.get('margin_chg_5d')),
                    short_chg_5d=_safe_float(row.get('short_chg_5d')),
                    dealer_net_buy=_safe_float(row.get('dealer_net_buy')),
                    dealer_buy_5d=_safe_float(row.get('dealer_buy_5d')),
                    price_vs_high20=_safe_float(row.get('price_vs_high20')),
                    ma_trend=_safe_float(row.get('ma_trend')),
                    sector_rs=_safe_float(row.get('sector_rs')),
                    foreign_hold_pct=_safe_float(row.get('foreign_hold_pct')),
                    foreign_hold_chg_5d=_safe_float(row.get('foreign_hold_chg_5d')),
                    etf_net_flow_5d=_safe_float(row.get('etf_net_flow_5d')),
                    foreign_buy_10d=_safe_float(row.get('foreign_buy_10d')),
                    foreign_buy_20d=_safe_float(row.get('foreign_buy_20d')),
                    trust_buy_10d=_safe_float(row.get('trust_buy_10d')),
                    trust_buy_20d=_safe_float(row.get('trust_buy_20d')),
                    dealer_buy_10d=_safe_float(row.get('dealer_buy_10d')),
                    dealer_buy_20d=_safe_float(row.get('dealer_buy_20d')),
                    atr20=_safe_float(row.get('atr20')),
                    atr_pct=_safe_float(row.get('atr_pct')),
                    ivol_20d=_safe_float(row.get('ivol_20d')),
                    log_amihud_20d=_safe_float(row.get('log_amihud_20d')),
                    divergence_avg=_safe_float(row.get('divergence_avg')),
                    market_breadth=_safe_float(row.get('market_breadth')),
                    market_trend=_safe_float(row.get('market_trend')),
                ))

            if records:
                db.bulk_save_objects(records)
                total_written += len(records)

            # 每 10 天 commit 一次
            if i % 10 == 9:
                db.commit()
                logger.info(f"[FeatureService] 回補進度: {batch_date} | 累計 {total_written} 筆")

        db.commit()
        logger.info(f"[FeatureService] 回補完成: {total_written} 筆")
        return total_written

    @staticmethod
    def get_features(db: Session, stock_id: str, days: int = 60):
        """查詢指定股票的歷史特徵"""
        features = db.query(StockFeature).filter(
            StockFeature.stock_id == stock_id
        ).order_by(StockFeature.date.desc()).limit(days).all()

        return list(reversed(features))

    @staticmethod
    def _build_chip_features(
        chip_rows,
        target_date,
        _chip_df: Optional[pd.DataFrame] = None,
    ) -> pd.DataFrame:
        """計算單日籌碼衍生指標（向量化版），回傳 DataFrame(stock_id, 各欄位)

        Args:
            chip_rows: StockChipData ORM 物件列表（若傳入則轉換為 DataFrame）
            target_date: 目標日期（date 或 pd.Timestamp）
            _chip_df: 已整理好的 DataFrame（backfill 路徑直接傳入，略過 ORM 轉換）
        """
        if _chip_df is not None:
            raw = _chip_df.copy()
        else:
            if not chip_rows:
                return pd.DataFrame()
            raw = pd.DataFrame([{
                'stock_id': c.stock_id,
                'date': pd.Timestamp(c.date),
                'foreign_net_buy': c.foreign_net_buy,
                'trust_net_buy': c.trust_net_buy,
                'dealer_net_buy': c.dealer_net_buy,
                'margin_balance': c.margin_balance,
                'short_balance': c.short_balance,
                'foreign_hold_pct': getattr(c, 'foreign_hold_pct', None),
            } for c in chip_rows])

        if raw.empty:
            return pd.DataFrame()

        raw['date'] = pd.to_datetime(raw['date'])
        raw = raw.sort_values(['stock_id', 'date'])

        # ── 向量化計算 5/10/20 日累積淨買超 ──
        for src_col, base_name in [
            ('foreign_net_buy', 'foreign_buy'),
            ('trust_net_buy', 'trust_buy'),
            ('dealer_net_buy', 'dealer_buy'),
        ]:
            if src_col not in raw.columns:
                for w in [5, 10, 20]:
                    raw[f'{base_name}_{w}d'] = None
                continue
            for w in [5, 10, 20]:
                dst_col = f'{base_name}_{w}d'
                raw[dst_col] = raw.groupby('stock_id')[src_col].transform(
                    lambda x, _w=w: x.rolling(_w, min_periods=1).sum()
                )

        # ── 向量化計算融資 5 日變化率 ──
        if 'margin_balance' in raw.columns:
            margin_shift = raw.groupby('stock_id')['margin_balance'].transform(lambda x: x.shift(4))
            raw['margin_chg_5d'] = (
                (raw['margin_balance'] - margin_shift)
                / margin_shift.replace(0, np.nan).abs()
                * 100
            )
        else:
            raw['margin_chg_5d'] = None

        # ── 融券餘額 5 日變化率（軋空因子，Phase 9）──
        if 'short_balance' in raw.columns:
            short_shift = raw.groupby('stock_id')['short_balance'].transform(lambda x: x.shift(4))
            raw['short_chg_5d'] = (
                (raw['short_balance'] - short_shift)
                / short_shift.replace(0, np.nan).abs()
                * 100
            )
        else:
            raw['short_chg_5d'] = None

        # ── 外資持股比率 5 日變化（百分點差）──
        if 'foreign_hold_pct' in raw.columns:
            hold_shift = raw.groupby('stock_id')['foreign_hold_pct'].transform(lambda x: x.shift(4))
            raw['foreign_hold_chg_5d'] = raw['foreign_hold_pct'] - hold_shift
        else:
            raw['foreign_hold_pct'] = None
            raw['foreign_hold_chg_5d'] = None

        # ── 只取 target_date 當日結果 ──
        target_ts = pd.Timestamp(target_date)
        result = raw[raw['date'] == target_ts].copy()

        keep_cols = [
            'stock_id', 'foreign_net_buy',
            'foreign_buy_5d', 'foreign_buy_10d', 'foreign_buy_20d',
            'trust_net_buy',
            'trust_buy_5d', 'trust_buy_10d', 'trust_buy_20d',
            'margin_chg_5d',
            'short_chg_5d',
            'dealer_net_buy',
            'dealer_buy_5d', 'dealer_buy_10d', 'dealer_buy_20d',
            'foreign_hold_pct', 'foreign_hold_chg_5d',
        ]
        result = result[[c for c in keep_cols if c in result.columns]]
        return result.reset_index(drop=True)


def _safe_float(val) -> Optional[float]:
    """安全轉換為 float，處理 NaN/None"""
    if val is None:
        return None
    try:
        f = float(val)
        if pd.isna(f) or np.isinf(f):
            return None
        return round(f, 4)
    except (ValueError, TypeError):
        return None

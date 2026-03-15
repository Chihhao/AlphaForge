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

        # 5. 只取 target_date 當日的資料
        target_df = df[df['date'] == target_date].copy()

        if target_df.empty:
            logger.warning(f"[FeatureService] {target_date} 非交易日或無資料")
            return 0

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

        # 6b. Left join 籌碼面（Phase 4B）
        chip_start = target_date - timedelta(days=10)
        chip_rows = db.query(StockChipData).filter(
            StockChipData.date >= chip_start,
            StockChipData.date <= target_date
        ).all()
        chip_df = FeatureService._build_chip_features(chip_rows, target_date)

        if not chip_df.empty:
            target_df = target_df.merge(chip_df, on='stock_id', how='left')
        else:
            for col in ('foreign_net_buy', 'foreign_buy_5d',
                        'trust_net_buy', 'trust_buy_5d', 'margin_chg_5d',
                        'dealer_net_buy', 'dealer_buy_5d'):
                target_df[col] = None

        # 7. 刪除當日已存在的記錄（upsert 邏輯）
        db.execute(
            delete(StockFeature).where(StockFeature.date == target_date)
        )

        # 8. 批量寫入
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
                foreign_net_buy=_safe_float(row.get('foreign_net_buy')),
                foreign_buy_5d=_safe_float(row.get('foreign_buy_5d')),
                trust_net_buy=_safe_float(row.get('trust_net_buy')),
                trust_buy_5d=_safe_float(row.get('trust_buy_5d')),
                margin_chg_5d=_safe_float(row.get('margin_chg_5d')),
                dealer_net_buy=_safe_float(row.get('dealer_net_buy')),
                dealer_buy_5d=_safe_float(row.get('dealer_buy_5d')),
                price_vs_high20=_safe_float(row.get('price_vs_high20')),
                ma_trend=_safe_float(row.get('ma_trend')),
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

        # 籌碼面：讀取回補期間 + 前 10 天的籌碼資料
        chip_warmup = start_date - timedelta(days=10)
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
            } for c in chip_rows])
            chip_all = chip_all.sort_values(['stock_id', 'date'])
            # 為每個目標日期建立特徵（傳入完整 chip_all，讓函數自行取 5 天窗口）
            for d in chip_all['date'].unique():
                chip_by_date[d] = FeatureService._build_chip_features(None, d.date(), _chip_df=chip_all)

        # 去除重複的 (stock_id, date)（price data 中可能存在重複來源）
        backfill_df = backfill_df.drop_duplicates(subset=['stock_id', 'date'], keep='first')

        # 初始化籌碼欄位
        for col in ('foreign_net_buy', 'foreign_buy_5d',
                    'trust_net_buy', 'trust_buy_5d', 'margin_chg_5d',
                    'dealer_net_buy', 'dealer_buy_5d'):
            backfill_df[col] = None

        # 刪除已存在的記錄
        db.execute(
            delete(StockFeature).where(
                StockFeature.date >= start_date,
                StockFeature.date <= end_date
            )
        )
        db.flush()

        # 批量寫入（按月分批 commit 避免過大事務）
        total_written = 0
        dates = sorted(backfill_df['date'].unique())

        for batch_date in dates:
            day_df = backfill_df[backfill_df['date'] == batch_date].copy()

            # 合併當日籌碼特徵（若存在）
            # 先移除預先初始化的 None 欄位，避免 merge 後產生 _x/_y 衝突
            chip_cols = ['foreign_net_buy', 'foreign_buy_5d',
                         'trust_net_buy', 'trust_buy_5d', 'margin_chg_5d',
                         'dealer_net_buy', 'dealer_buy_5d']
            day_df = day_df.drop(columns=[c for c in chip_cols if c in day_df.columns])

            ts_key = pd.Timestamp(batch_date)
            day_chip = chip_by_date.get(ts_key, pd.DataFrame())
            if not day_chip.empty:
                day_df = day_df.merge(day_chip, on='stock_id', how='left')
            else:
                for col in chip_cols:
                    day_df[col] = None

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
                    foreign_net_buy=_safe_float(row.get('foreign_net_buy')),
                    foreign_buy_5d=_safe_float(row.get('foreign_buy_5d')),
                    trust_net_buy=_safe_float(row.get('trust_net_buy')),
                    trust_buy_5d=_safe_float(row.get('trust_buy_5d')),
                    margin_chg_5d=_safe_float(row.get('margin_chg_5d')),
                    dealer_net_buy=_safe_float(row.get('dealer_net_buy')),
                    dealer_buy_5d=_safe_float(row.get('dealer_buy_5d')),
                    price_vs_high20=_safe_float(row.get('price_vs_high20')),
                    ma_trend=_safe_float(row.get('ma_trend')),
                ))

            if records:
                db.bulk_save_objects(records)
                total_written += len(records)

            # 每 10 天 commit 一次
            if dates.index(batch_date) % 10 == 9:
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
        """計算單日籌碼衍生指標，回傳 DataFrame(stock_id, 5 欄位)

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
            } for c in chip_rows])

        if raw.empty:
            return pd.DataFrame()

        raw['date'] = pd.to_datetime(raw['date'])
        raw = raw.sort_values(['stock_id', 'date'])

        target_ts = pd.Timestamp(target_date)

        # 5 日累積買超（用過去 5 個交易日含今日的窗口）
        result_rows = []
        for sid, grp in raw.groupby('stock_id'):
            grp = grp.sort_values('date')
            today_row = grp[grp['date'] == target_ts]
            if today_row.empty:
                continue

            window = grp[grp['date'] <= target_ts].tail(5)

            foreign_nb  = today_row['foreign_net_buy'].values[0]
            foreign_5d  = window['foreign_net_buy'].sum() if 'foreign_net_buy' in window.columns else None
            trust_nb    = today_row['trust_net_buy'].values[0]
            trust_5d    = window['trust_net_buy'].sum() if 'trust_net_buy' in window.columns else None
            dealer_nb   = today_row['dealer_net_buy'].values[0] if 'dealer_net_buy' in today_row.columns else None
            dealer_5d   = window['dealer_net_buy'].sum() if 'dealer_net_buy' in window.columns else None

            # 融資餘額 5 日變化率
            if 'margin_balance' in window.columns and len(window) >= 2:
                m_now  = window['margin_balance'].iloc[-1]
                m_prev = window['margin_balance'].iloc[0]
                if m_prev and m_prev != 0 and pd.notna(m_prev) and pd.notna(m_now):
                    margin_chg_5d = (m_now - m_prev) / abs(m_prev) * 100
                else:
                    margin_chg_5d = None
            else:
                margin_chg_5d = None

            result_rows.append({
                'stock_id': sid,
                'foreign_net_buy': foreign_nb,
                'foreign_buy_5d': float(foreign_5d) if pd.notna(foreign_5d) else None,
                'trust_net_buy': trust_nb,
                'trust_buy_5d': float(trust_5d) if pd.notna(trust_5d) else None,
                'dealer_net_buy': float(dealer_nb) if dealer_nb is not None and pd.notna(dealer_nb) else None,
                'dealer_buy_5d': float(dealer_5d) if dealer_5d is not None and pd.notna(dealer_5d) else None,
                'margin_chg_5d': margin_chg_5d,
            })

        return pd.DataFrame(result_rows) if result_rows else pd.DataFrame()


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

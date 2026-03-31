"""籌碼面 10d/20d 擴展計算測試"""
import pytest
import pandas as pd
import numpy as np
from datetime import date, timedelta
from app.services.feature_service import FeatureService


def _make_chip_df(stock_ids, n_days=25):
    rows = []
    for sid in stock_ids:
        for i in range(n_days):
            d = pd.Timestamp(date(2025, 1, 2) + timedelta(days=i))
            rows.append({
                'stock_id': sid,
                'date': d,
                'foreign_net_buy': np.random.randint(-100, 100),
                'trust_net_buy': np.random.randint(-50, 50),
                'dealer_net_buy': np.random.randint(-30, 30),
                'margin_balance': 1000 + i * 10,
                'foreign_hold_pct': 30.0 + i * 0.1,
            })
    return pd.DataFrame(rows)


class TestChipExpansion:
    def test_build_chip_features_has_10d_20d_columns(self):
        chip_df = _make_chip_df(["2330"], 25)
        target_date = chip_df['date'].max().date()
        result = FeatureService._build_chip_features(None, target_date, _chip_df=chip_df)

        assert not result.empty
        for col in ['foreign_buy_10d', 'foreign_buy_20d',
                     'trust_buy_10d', 'trust_buy_20d',
                     'dealer_buy_10d', 'dealer_buy_20d']:
            assert col in result.columns, f"缺少欄位: {col}"

    def test_5d_unchanged(self):
        chip_df = _make_chip_df(["2330"], 25)
        target_date = chip_df['date'].max().date()
        result = FeatureService._build_chip_features(None, target_date, _chip_df=chip_df)

        for col in ['foreign_buy_5d', 'trust_buy_5d', 'dealer_buy_5d']:
            assert col in result.columns

    def test_20d_sum_larger_than_5d(self):
        chip_df = _make_chip_df(["2330"], 25)
        chip_df['foreign_net_buy'] = 10  # all positive
        target_date = chip_df['date'].max().date()
        result = FeatureService._build_chip_features(None, target_date, _chip_df=chip_df)

        row = result.iloc[0]
        assert row['foreign_buy_20d'] >= row['foreign_buy_5d']

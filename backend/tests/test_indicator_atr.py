"""ATR (Average True Range) 向量化計算測試"""
import pytest
import pandas as pd
import numpy as np
from app.services.indicator_service import IndicatorService


def _make_price_df(stock_id: str, n: int = 30) -> pd.DataFrame:
    """生成模擬價格 DataFrame"""
    np.random.seed(42)
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    close = 100 + np.cumsum(np.random.randn(n) * 2)
    high = close + np.abs(np.random.randn(n))
    low = close - np.abs(np.random.randn(n))
    return pd.DataFrame({
        "stock_id": stock_id,
        "date": dates,
        "open": close + np.random.randn(n) * 0.5,
        "high": high,
        "low": low,
        "close": close,
        "volume": np.random.randint(1000, 10000, n),
    })


class TestATR:
    def test_atr_returns_series(self):
        df = _make_price_df("2330")
        result = IndicatorService.calculate_atr_vec(df, window=5)
        assert isinstance(result, pd.Series)
        assert len(result) == len(df)

    def test_atr_first_n_minus_1_are_nan(self):
        """前 window-1 筆應為 NaN（rolling 暖機）"""
        df = _make_price_df("2330")
        result = IndicatorService.calculate_atr_vec(df, window=5)
        assert result.iloc[:5].isna().sum() >= 4

    def test_atr_values_positive(self):
        """ATR 值應全部 > 0"""
        df = _make_price_df("2330")
        result = IndicatorService.calculate_atr_vec(df, window=5)
        valid = result.dropna()
        assert (valid > 0).all()

    def test_atr_multi_stock(self):
        """多檔股票各自獨立計算"""
        df1 = _make_price_df("2330", 30)
        df2 = _make_price_df("2317", 30)
        df2["close"] = df2["close"] * 3
        df2["high"] = df2["high"] * 3
        df2["low"] = df2["low"] * 3
        combined = pd.concat([df1, df2]).sort_values(["stock_id", "date"]).reset_index(drop=True)

        result = IndicatorService.calculate_atr_vec(combined, window=5)
        atr_2330 = result[combined["stock_id"] == "2330"].dropna()
        atr_2317 = result[combined["stock_id"] == "2317"].dropna()
        ratio = atr_2317.mean() / atr_2330.mean()
        assert 2.0 < ratio < 4.0

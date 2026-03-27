import pytest
from app.services.market_service import MarketService
from app.schemas.market import SectorStocksResponse


def test_get_sector_stocks_returns_correct_schema():
    """回傳格式必須符合 SectorStocksResponse"""
    # 先取 sector-strength 找一個有效的產業名稱
    strength = MarketService.get_sector_strength()
    if not strength.top:
        pytest.skip("無產業資料，跳過")
    industry = strength.top[0].industry
    result = MarketService.get_sector_stocks(industry, top=10)
    assert isinstance(result, SectorStocksResponse)
    assert result.industry == industry
    assert isinstance(result.stocks, list)
    assert len(result.stocks) <= 10


def test_get_sector_stocks_sorted_descending():
    """個股應按 ret20 由高到低排序"""
    strength = MarketService.get_sector_strength()
    if not strength.top:
        pytest.skip("無產業資料，跳過")
    result = MarketService.get_sector_stocks(strength.top[0].industry)
    if len(result.stocks) >= 2:
        assert result.stocks[0].ret20 >= result.stocks[1].ret20


def test_get_sector_stocks_invalid_industry():
    """不存在的產業應回傳空清單，不拋例外"""
    result = MarketService.get_sector_stocks("不存在的產業_XXXX")
    assert isinstance(result, SectorStocksResponse)
    assert result.stocks == []


def test_get_sector_stocks_cache():
    """第二次呼叫應命中快取（同一產業，TTL 內）"""
    strength = MarketService.get_sector_strength()
    if not strength.top:
        pytest.skip("無產業資料，跳過")
    industry = strength.top[0].industry
    r1 = MarketService.get_sector_stocks(industry)
    r2 = MarketService.get_sector_stocks(industry)
    # 快取命中時回傳同一個物件（is）
    assert r1 is r2

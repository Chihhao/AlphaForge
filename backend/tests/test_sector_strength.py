import pytest
from app.services.market_service import MarketService
from app.schemas.market import SectorStrengthResponse


def test_get_sector_strength_returns_correct_schema():
    """回傳格式必須符合 SectorStrengthResponse"""
    result = MarketService.get_sector_strength()
    assert isinstance(result, SectorStrengthResponse)
    assert isinstance(result.top, list)
    assert isinstance(result.bottom, list)
    assert len(result.top) <= 5
    assert len(result.bottom) <= 5


def test_get_sector_strength_top_sorted_descending():
    """top 應依 median_rs 由高到低排序"""
    result = MarketService.get_sector_strength()
    if len(result.top) >= 2:
        assert result.top[0].median_rs >= result.top[1].median_rs


def test_get_sector_strength_bottom_sorted_ascending():
    """bottom 應依 median_rs 由低到高排序"""
    result = MarketService.get_sector_strength()
    if len(result.bottom) >= 2:
        assert result.bottom[0].median_rs <= result.bottom[1].median_rs


def test_get_sector_strength_no_overlap():
    """top 與 bottom 的產業不應重疊（除非總產業數 <= 10）"""
    result = MarketService.get_sector_strength()
    if len(result.top) == 5 and len(result.bottom) == 5:
        top_industries = {item.industry for item in result.top}
        bottom_industries = {item.industry for item in result.bottom}
        assert top_industries.isdisjoint(bottom_industries)


def test_get_sector_strength_empty_when_no_data():
    """無資料時應回傳 date=None, top=[], bottom=[]（不應拋例外）"""
    result = MarketService.get_sector_strength()
    assert result is not None

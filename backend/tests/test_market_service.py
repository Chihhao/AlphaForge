import pytest
from app.services.market_service import MarketService
from app.schemas.market import MarketRankingResponse

def test_get_market_rankings():
    """測試市場排行榜邏輯是否能正確回傳資料"""
    response = MarketService.get_market_rankings(limit=3)
    
    assert isinstance(response, MarketRankingResponse)
    
    # 檢查長度是否不超過 limit
    assert len(response.top_gainers) <= 3
    assert len(response.top_losers) <= 3
    assert len(response.top_volume) <= 3
    
    # 確保資料結構正確
    if len(response.top_gainers) > 0:
        first_item = response.top_gainers[0]
        assert hasattr(first_item, "stock_id")
        assert hasattr(first_item, "stock_name")
        assert hasattr(first_item, "price")
        assert hasattr(first_item, "change_percent")
        assert hasattr(first_item, "volume")
        
    # 確保排序正確 (漲幅由高到低)
    if len(response.top_gainers) >= 2:
        assert response.top_gainers[0].change_percent >= response.top_gainers[1].change_percent
        
    # 確保排序正確 (跌幅由低到高，即數字由小到大，或負越多在前面)
    if len(response.top_losers) >= 2:
        assert response.top_losers[0].change_percent <= response.top_losers[1].change_percent

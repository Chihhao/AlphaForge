# backend/tests/test_strategy_miner_concluded.py
import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_concluded_picks_returns_correct_shape():
    """回傳格式必須包含 items（list）和 total（int）"""
    resp = client.get("/strategy-miner/picks/concluded")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total" in data
    assert isinstance(data["items"], list)
    assert isinstance(data["total"], int)


def test_concluded_picks_each_item_has_required_fields():
    """每筆記錄必須包含所有必要欄位"""
    resp = client.get("/strategy-miner/picks/concluded")
    data = resp.json()
    if not data["items"]:
        pytest.skip("無已出場 picks，跳過欄位驗證")
    item = data["items"][0]
    for field in [
        "pick_date", "stock_id", "stock_name", "entry_price",
        "exit_reason", "return_pct", "days_held", "time_dimension",
        "buy_reasons", "take_profit_pct", "stop_loss_pct", "hold_days_max",
    ]:
        assert field in item, f"缺少欄位：{field}"


def test_concluded_picks_exit_reason_valid():
    """exit_reason 只能是 take_profit / stop_loss / time_limit / settled"""
    resp = client.get("/strategy-miner/picks/concluded")
    data = resp.json()
    valid = {"take_profit", "stop_loss", "time_limit", "settled"}
    for item in data["items"]:
        assert item["exit_reason"] in valid, f"無效 exit_reason: {item['exit_reason']}"


def test_concluded_picks_pagination():
    """limit=1&offset=0 應只回傳 1 筆，total 不變"""
    resp_all = client.get("/strategy-miner/picks/concluded?limit=100&offset=0")
    total = resp_all.json()["total"]
    if total < 2:
        pytest.skip("資料不足，跳過分頁測試")
    resp_page = client.get("/strategy-miner/picks/concluded?limit=1&offset=0")
    data = resp_page.json()
    assert len(data["items"]) == 1
    assert data["total"] == total


def test_concluded_picks_sorted_by_date_desc():
    """結果應按 pick_date 降序排列"""
    resp = client.get("/strategy-miner/picks/concluded?limit=100")
    items = resp.json()["items"]
    if len(items) < 2:
        pytest.skip("資料不足，跳過排序測試")
    dates = [i["pick_date"] for i in items]
    assert dates == sorted(dates, reverse=True)

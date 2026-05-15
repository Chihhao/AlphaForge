from datetime import date

import httpx
import pytest

from app.data.valuation_crawler import fetch_valuation_daily, _safe_float, _safe_int


def test_safe_float_parses_normal():
    assert _safe_float("3.26") == 3.26
    assert _safe_float("0.78") == 0.78


def test_safe_float_handles_empty_and_dash():
    assert _safe_float("-") is None
    assert _safe_float("") is None
    assert _safe_float("N/A") is None


def test_safe_int_parses_normal():
    assert _safe_int("114") == 114


def test_safe_int_handles_empty():
    assert _safe_int("-") is None
    assert _safe_int("") is None


def test_fetch_valuation_daily_parses_twse_response():
    """Mock TWSE BWIBBU_d response, 驗 parse 正確。"""
    sample = {
        "stat": "OK",
        "date": "20260514",
        "title": "115年05月14日 個股日本益比、殖利率及股價淨值比",
        "fields": ["證券代號", "證券名稱", "收盤價", "殖利率(%)", "股利年度", "本益比", "股價淨值比", "財報年/季"],
        "data": [
            ["1101", "台泥", "24.55", "3.26", "114", "-", "0.78", "115/1"],
            ["1102", "亞泥", "35.20", "6.53", "114", "11.81", "0.70", "115/1"],
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/exchangeReport/BWIBBU_d")
        return httpx.Response(200, json=sample)

    out = fetch_valuation_daily(date(2026, 5, 14), _transport=httpx.MockTransport(handler))
    assert len(out) == 2
    r1 = out[0]
    assert r1["stock_id"] == "1101"
    assert r1["close"] == 24.55
    assert r1["yield_rate"] == 3.26
    assert r1["pe_ratio"] is None  # '-' → None
    assert r1["pb_ratio"] == 0.78
    assert r1["dividend_year"] == 114
    assert r1["report_period"] == "115/1"
    r2 = out[1]
    assert r2["pe_ratio"] == 11.81


def test_fetch_valuation_daily_empty_on_holiday():
    """假日 TWSE 回 stat 非 OK 或 data 空, 應該 return []。"""
    def handler_empty(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"stat": "很抱歉，沒有符合條件的資料!", "data": []})

    out = fetch_valuation_daily(date(2026, 5, 17), _transport=httpx.MockTransport(handler_empty))
    assert out == []

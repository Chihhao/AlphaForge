"""新端點 /strategy-miner/history/{stock_id} 測試"""
from __future__ import annotations
from datetime import date
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from main import app
from app.db.database import Base, get_db
from app.models.strategy_miner_pick import StrategyMinerPick
from app.models.stock_price import StockPrice


@pytest.fixture
def client_and_db():
    # TestClient 在不同 thread 執行, SQLite memory 需 StaticPool + check_same_thread=False
    engine = create_engine(
        'sqlite:///:memory:',
        connect_args={'check_same_thread': False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=[
        StrategyMinerPick.__table__, StockPrice.__table__,
    ])
    Session = sessionmaker(bind=engine)
    db = Session()

    def _override():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _override
    yield TestClient(app), db
    app.dependency_overrides.clear()
    db.close()


def _add_pick(db, **kw):
    defaults = dict(
        pick_date=date(2026, 3, 1), stock_id='3710', stock_name='連展投控',
        strategy_ids='["20d"]', weighted_score=1.0, entry_price=10.0,
        take_profit_pct=0.08, stop_loss_pct=0.05, hold_days_max=5,
        time_dimension='20d', direction='long',
    )
    defaults.update(kw)
    db.add(StrategyMinerPick(**defaults))


def _add_price(db, stock_id, d, close):
    db.add(StockPrice(stock_id=stock_id, date=d, open=close, high=close, low=close, close=close, volume=1000))


def test_history_returns_concluded_only(client_and_db):
    client, db = client_and_db
    # concluded win
    _add_pick(db, pick_date=date(2026, 2, 1), entry_price=10.0)
    _add_price(db, '3710', date(2026, 2, 2), 10.9)
    # still holding
    _add_pick(db, pick_date=date(2026, 4, 17), entry_price=20.0, hold_days_max=20)
    db.commit()

    r = client.get('/strategy-miner/history/3710')
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]['entry_date'] == '2026-02-01'
    assert data[0]['exit_reason'] == 'take_profit'
    assert 'return_pct' in data[0]
    assert data[0]['strategy_id'] == '20d'


def test_history_empty_when_no_picks(client_and_db):
    client, _ = client_and_db
    r = client.get('/strategy-miner/history/0000')
    assert r.status_code == 200
    assert r.json() == []


def test_history_contract_matches_trades_endpoint(client_and_db):
    """回傳欄位需與 /trades/{stock_id} 一致 (前端相容性)."""
    client, db = client_and_db
    _add_pick(db, pick_date=date(2026, 2, 1), entry_price=10.0)
    _add_price(db, '3710', date(2026, 2, 2), 10.9)
    db.commit()

    r = client.get('/strategy-miner/history/3710')
    data = r.json()[0]
    expected_keys = {
        'strategy_id', 'stock_id', 'entry_date', 'entry_price',
        'exit_date', 'exit_price', 'exit_reason', 'return_pct', 'hold_days',
    }
    assert expected_keys.issubset(set(data.keys()))

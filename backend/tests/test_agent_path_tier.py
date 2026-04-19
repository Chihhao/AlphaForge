import pytest
from app.agent.path_tier import classify, Tier


@pytest.mark.parametrize("path,expected", [
    ("backend/app/services/alpha_miner_service.py", Tier.T2),
    ("backend/app/api/endpoints/picks.py", Tier.T2),
    ("backend/app/models/stock.py", Tier.T2),
    ("backend/scripts/research_decay.py", Tier.T1),
    ("backend/scripts/diag_something.py", Tier.T1),
    ("backend/scripts/backfill_prices.py", Tier.T2),  # existing prod script
    ("docs/reports/2026-04-19-0300.md", Tier.T1),
    ("docs/state/deploy-lock.json", Tier.T3),  # state 屬 T3 硬擋
    ("frontend/pages/index.tsx", Tier.T3),
    ("backend/app/core/scheduler.py", Tier.T3),
    ("backend/alembic/versions/abc123_xxx.py", Tier.T3),
    ("backend/app/core/database.py", Tier.T3),
    ("docker-compose.yml", Tier.T3),
    ("Dockerfile", Tier.T3),
    ("deploy.sh", Tier.T3),
    ("backend/requirements.txt", Tier.T3),
    (".claude/settings.json", Tier.T3),
    ("CLAUDE.md", Tier.T3),
])
def test_classify(path, expected):
    assert classify(path) == expected


def test_unknown_path_defaults_to_t3():
    assert classify("some/random/path.txt") == Tier.T3

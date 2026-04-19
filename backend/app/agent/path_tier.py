from __future__ import annotations
import re
from enum import IntEnum


class Tier(IntEnum):
    T0 = 0   # read-only, 不改檔
    T1 = 1   # research scripts + docs
    T2 = 2   # production code with preconditions
    T3 = 3   # blocked, proposal only


_T3_PATTERNS = [
    re.compile(r"^frontend/"),
    re.compile(r"^backend/app/core/scheduler\.py$"),
    re.compile(r"^backend/app/core/database\.py$"),
    re.compile(r"^backend/alembic/"),
    re.compile(r"^docker-compose.*\.ya?ml$"),
    re.compile(r"^Dockerfile"),
    re.compile(r"^deploy\.sh$"),
    re.compile(r"^start_dev\.sh$"),
    re.compile(r"^backend/requirements\.txt$"),
    re.compile(r"^\.claude/"),
    re.compile(r"^CLAUDE\.md$"),
    re.compile(r"^docs/state/"),
]

_T1_PATTERNS = [
    re.compile(r"^backend/scripts/research_"),
    re.compile(r"^backend/scripts/diag_"),
    re.compile(r"^docs/(?!state/)"),  # docs/ 除 docs/state
]

_T2_PATTERNS = [
    re.compile(r"^backend/app/services/"),
    re.compile(r"^backend/app/api/endpoints/"),
    re.compile(r"^backend/app/models/"),
    re.compile(r"^backend/app/schemas/"),
    re.compile(r"^backend/app/logic/"),
    re.compile(r"^backend/app/core/indicators\.py$"),
    re.compile(r"^backend/app/agent/"),   # agent 模組自己
    re.compile(r"^backend/scripts/"),     # 其他既有 scripts (backfill etc.)
    re.compile(r"^backend/tests/"),
]


def classify(path: str) -> Tier:
    for p in _T3_PATTERNS:
        if p.match(path):
            return Tier.T3
    for p in _T1_PATTERNS:
        if p.match(path):
            return Tier.T1
    for p in _T2_PATTERNS:
        if p.match(path):
            return Tier.T2
    return Tier.T3  # unknown → 硬擋

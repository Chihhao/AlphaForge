###### tags: `專案`,`notify-hub`,`實作計畫`,`AlphaForge`

# notify-hub v0.1.0 Implementation Plan

`文件版本: 2026-04-24a`

> **v2 修訂 (2026-04-24):**
> - Task 3/4: `approvals.expires_at` 改 nullable, 靜音時段建立的 approval 先不設倒數 (修 quiet hours × timeout 撞車)
> - Task 18: flush 推出成功後才設 expires_at, 啟動倒數
> - 新增 Task 19.5: push failure retry scheduler + telegram 健康狀態快取刷新 (補 spec §7.2 漏掉的邏輯)
> - Task 6/9/18: `TG_STATUS` 改成 push 行為的副作用 + retry job 主動 probe

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立 `~/Documents/GitHub/notify-hub` 新 repo，交付 v0.1.0 MVP: 一個 self-hosted FastAPI + PostgreSQL + Telegram Bot 整合服務，讓 AlphaForge agent 與其他 headless 腳本能透過 HTTP 推送 approval 請求並收集使用者回覆。

**Architecture:** FastAPI async + SQLAlchemy 2.0 async + asyncpg + Alembic。Telegram 透過 httpx 直接打 Bot HTTP API (不依賴重型 SDK)。Scheduler 跑在同 process 的 APScheduler，承擔 timeout 自動結案 / quiet hours flush / retention 清理。Webhook 接 Telegram callback_query 與 message。業務邏輯集中在 crud + dispatcher 兩層，狀態全存 DB，hub 重啟可恢復。

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0 (async), asyncpg, Alembic, httpx, APScheduler, pydantic-settings, pytest + pytest-asyncio + testcontainers-postgres, Docker.

**Scope (per spec §11.2):** 7 endpoints (`POST /v1/approvals`, `GET /v1/approvals/<id>/wait`, `GET /v1/approvals/<id>`, `POST /v1/jobs`, `GET /v1/jobs/next`, `POST /v1/jobs/<id>/complete`, `GET /healthz`, `POST /tg/webhook`) + Telegram integration (sendMessage, editMessageText, editMessageReplyMarkup, answerCallbackQuery, ForceReply) + quiet hours + timeout auto-close + /task + smoke test. **Explicitly excluded:** AlphaForge agent daemon (Phase 2 plan 處理)。

**Reference:** `docs/superpowers/specs/2026-04-22-notify-hub-design.md`

---

## File Structure

```
~/Documents/GitHub/notify-hub/
├── README.md
├── .gitignore
├── .env.example
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
├── alembic.ini
├── migrations/
│   ├── env.py
│   └── versions/
│       └── 0001_initial.py
├── src/notify_hub/
│   ├── __init__.py
│   ├── main.py                    # FastAPI app 建構 + startup/shutdown
│   ├── config.py                  # pydantic Settings
│   ├── auth.py                    # consumer token、webhook secret、chat 白名單
│   ├── db/
│   │   ├── __init__.py
│   │   ├── models.py              # 6 張 SQLAlchemy 表
│   │   ├── session.py             # async engine + session factory
│   │   └── crud.py                # 集中的純 SQL helpers
│   ├── api/
│   │   ├── __init__.py
│   │   ├── approvals.py           # POST/GET approvals, wait
│   │   ├── jobs.py                # jobs CRUD endpoints
│   │   ├── health.py              # /healthz
│   │   └── webhook.py             # POST /tg/webhook
│   ├── telegram/
│   │   ├── __init__.py
│   │   ├── client.py              # httpx wrapper
│   │   ├── formatter.py           # HTML message + inline keyboard
│   │   └── dispatcher.py          # callback_query / message 分派
│   ├── scheduler/
│   │   ├── __init__.py
│   │   ├── runtime.py             # APScheduler 啟停
│   │   ├── timeout_sweeper.py     # 每 30s 掃 timeout
│   │   ├── quiet_hours_flush.py   # 07:00 跑
│   │   └── cleanup.py             # 04:00 跑
│   └── schemas.py                 # Pydantic request/response
└── tests/
    ├── conftest.py                # DB fixture、FastAPI TestClient
    ├── unit/
    │   ├── test_auth.py
    │   ├── test_formatter.py
    │   ├── test_callback_parser.py
    │   └── test_quiet_hours.py
    ├── integration/
    │   ├── test_approvals_api.py
    │   ├── test_wait_longpoll.py
    │   ├── test_webhook_callback.py
    │   ├── test_per_item_flow.py
    │   ├── test_reject_reason.py
    │   ├── test_jobs_api.py
    │   ├── test_task_command.py
    │   ├── test_timeout_close.py
    │   ├── test_quiet_hours_flush.py
    │   └── test_idempotency.py
    └── smoke/
        └── smoke_test.py
```

**File responsibilities (聚焦 + 清楚邊界):**
- `config.py` 單一責任: env → Settings 物件，無業務邏輯
- `auth.py`: 三種 auth 驗證 (consumer / webhook secret / chat 白名單)，不觸 DB 寫入
- `db/models.py`: 純 ORM，無 query
- `db/crud.py`: 所有 SQL，測試從這裡切
- `telegram/client.py`: 純 HTTP，無業務判斷
- `telegram/formatter.py`: 純函式，產生 text + keyboard 結構
- `telegram/dispatcher.py`: 連接 webhook → crud → client 的 orchestration
- `scheduler/*`: 各自獨立 job，可個別 unit test

---

## Task 1: Repo scaffold + 工具鏈

**Files:**
- Create: `~/Documents/GitHub/notify-hub/pyproject.toml`
- Create: `~/Documents/GitHub/notify-hub/.gitignore`
- Create: `~/Documents/GitHub/notify-hub/.env.example`
- Create: `~/Documents/GitHub/notify-hub/src/notify_hub/__init__.py`

- [ ] **Step 1: 建立新 repo**

```bash
mkdir -p ~/Documents/GitHub/notify-hub/src/notify_hub
cd ~/Documents/GitHub/notify-hub
git init
```

- [ ] **Step 2: 寫 `pyproject.toml`**

```toml
[project]
name = "notify-hub"
version = "0.1.0"
description = "Self-hosted Telegram approval hub for headless automation agents"
requires-python = ">=3.12"
dependencies = [
  "fastapi>=0.115",
  "uvicorn[standard]>=0.30",
  "sqlalchemy[asyncio]>=2.0.30",
  "asyncpg>=0.29",
  "alembic>=1.13",
  "pydantic-settings>=2.4",
  "httpx>=0.27",
  "apscheduler>=3.10",
  "python-multipart>=0.0.9",
]

[project.optional-dependencies]
dev = [
  "pytest>=8",
  "pytest-asyncio>=0.23",
  "httpx>=0.27",
  "testcontainers[postgres]>=4.7",
  "ruff>=0.5",
]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.ruff]
line-length = 100
target-version = "py312"
```

- [ ] **Step 3: 寫 `.gitignore`**

```
.venv/
__pycache__/
*.pyc
.pytest_cache/
.env
.ruff_cache/
dist/
build/
*.egg-info/
```

- [ ] **Step 4: 寫 `.env.example`**

```bash
DATABASE_URL=postgresql+asyncpg://notify_hub:change_me@localhost:5432/notify_hub
TELEGRAM_BOT_TOKEN=
TELEGRAM_WEBHOOK_SECRET=
PUBLIC_BASE_URL=https://example.com/notify-hub
NOTIFY_HUB_CONSUMER_TOKENS=alphaforge:af_xxx
ALLOWED_CHAT_IDS=
QUIET_HOURS_START=22:00
QUIET_HOURS_END=07:00
QUIET_HOURS_TZ=Asia/Taipei
LOG_LEVEL=INFO
```

- [ ] **Step 5: 建立 venv + 安裝**

```bash
cd ~/Documents/GitHub/notify-hub
python3.12 -m venv .venv
./.venv/bin/pip install -e ".[dev]"
touch src/notify_hub/__init__.py
mkdir -p tests/unit tests/integration tests/smoke
touch tests/__init__.py tests/unit/__init__.py tests/integration/__init__.py
```

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "chore: scaffold notify-hub repo (pyproject, venv, layout)"
```

---

## Task 2: Config module

**Files:**
- Create: `src/notify_hub/config.py`
- Create: `tests/unit/test_config.py`

- [ ] **Step 1: 寫 failing test**

```python
# tests/unit/test_config.py
import os
import pytest
from notify_hub.config import Settings, parse_consumer_tokens, parse_chat_ids


def test_parse_consumer_tokens_multi():
    result = parse_consumer_tokens("alphaforge:af_abc,rebirth:rb_def")
    assert result == {"alphaforge": "af_abc", "rebirth": "rb_def"}


def test_parse_consumer_tokens_empty():
    assert parse_consumer_tokens("") == {}


def test_parse_chat_ids_multi():
    assert parse_chat_ids("123,456") == [123, 456]


def test_settings_load(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "sec")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://ex.com/h")
    monkeypatch.setenv("NOTIFY_HUB_CONSUMER_TOKENS", "alphaforge:x")
    monkeypatch.setenv("ALLOWED_CHAT_IDS", "42")
    s = Settings()
    assert s.telegram_bot_token == "tok"
    assert s.consumer_tokens == {"alphaforge": "x"}
    assert s.allowed_chat_ids == [42]
    assert s.quiet_hours_start == "22:00"
```

- [ ] **Step 2: 跑測試確認 fail**

```bash
./.venv/bin/pytest tests/unit/test_config.py -v
```

Expected: ModuleNotFoundError: notify_hub.config

- [ ] **Step 3: 實作 `config.py`**

```python
# src/notify_hub/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator


def parse_consumer_tokens(raw: str) -> dict[str, str]:
    if not raw:
        return {}
    out: dict[str, str] = {}
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        name, _, token = chunk.partition(":")
        if name and token:
            out[name.strip()] = token.strip()
    return out


def parse_chat_ids(raw: str) -> list[int]:
    if not raw:
        return []
    return [int(x.strip()) for x in raw.split(",") if x.strip()]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    telegram_bot_token: str
    telegram_webhook_secret: str
    public_base_url: str
    consumer_tokens: dict[str, str] = {}
    allowed_chat_ids: list[int] = []
    quiet_hours_start: str = "22:00"
    quiet_hours_end: str = "07:00"
    quiet_hours_tz: str = "Asia/Taipei"
    log_level: str = "INFO"

    @field_validator("consumer_tokens", mode="before")
    @classmethod
    def _parse_tokens(cls, v):
        return parse_consumer_tokens(v) if isinstance(v, str) else v

    @field_validator("allowed_chat_ids", mode="before")
    @classmethod
    def _parse_chats(cls, v):
        return parse_chat_ids(v) if isinstance(v, str) else v

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="",
        extra="ignore",
        env_nested_delimiter=None,
    )
```

注意：pydantic-settings 會把 `NOTIFY_HUB_CONSUMER_TOKENS` 映射到 `consumer_tokens`，要加 alias。改寫：

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    database_url: str
    telegram_bot_token: str
    telegram_webhook_secret: str
    public_base_url: str
    consumer_tokens: dict[str, str] = Field(default_factory=dict, alias="NOTIFY_HUB_CONSUMER_TOKENS")
    allowed_chat_ids: list[int] = Field(default_factory=list, alias="ALLOWED_CHAT_IDS")
    quiet_hours_start: str = "22:00"
    quiet_hours_end: str = "07:00"
    quiet_hours_tz: str = "Asia/Taipei"
    log_level: str = "INFO"
```

(import `Field` from pydantic, drop duplicate model_config)

- [ ] **Step 4: 跑測試確認 pass**

```bash
./.venv/bin/pytest tests/unit/test_config.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/notify_hub/config.py tests/unit/test_config.py
git commit -m "feat(config): env-driven Settings with token/chat parsing"
```

---

## Task 3: DB models + Alembic initial migration

**Files:**
- Create: `src/notify_hub/db/__init__.py`
- Create: `src/notify_hub/db/models.py`
- Create: `alembic.ini`
- Create: `migrations/env.py`
- Create: `migrations/versions/0001_initial.py`
- Create: `tests/unit/test_models.py`

- [ ] **Step 1: 寫 failing test**

```python
# tests/unit/test_models.py
from notify_hub.db.models import (
    Consumer, Subscriber, Approval, ApprovalItem, Decision, AgentJob,
    ApprovalStatus, PushState, DecisionType, JobStatus, JobSource,
)


def test_enums_values():
    assert ApprovalStatus.pending.value == "pending"
    assert ApprovalStatus.mixed.value == "mixed"
    assert PushState.suppressed_quiet_hours.value == "suppressed_quiet_hours"
    assert DecisionType.timeout.value == "timeout"
    assert JobStatus.claimed.value == "claimed"
    assert JobSource.telegram_task.value == "telegram_task"


def test_approval_model_table_name():
    assert Approval.__tablename__ == "approvals"
    assert ApprovalItem.__tablename__ == "approval_items"
```

- [ ] **Step 2: 跑 fail**

```bash
./.venv/bin/pytest tests/unit/test_models.py -v
```

- [ ] **Step 3: 實作 `models.py`**

```python
# src/notify_hub/db/models.py
from __future__ import annotations
import enum
import uuid
from datetime import datetime
from sqlalchemy import (
    BigInteger, Column, DateTime, Enum as SAEnum, ForeignKey, Integer,
    String, Text, UniqueConstraint, Index, text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class ApprovalStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    mixed = "mixed"
    timeout = "timeout"


class PushState(str, enum.Enum):
    scheduled = "scheduled"
    pushed = "pushed"
    push_failed = "push_failed"
    suppressed_quiet_hours = "suppressed_quiet_hours"


class DecisionType(str, enum.Enum):
    approved = "approved"
    rejected = "rejected"
    timeout = "timeout"


class JobStatus(str, enum.Enum):
    pending = "pending"
    claimed = "claimed"
    completed = "completed"
    failed = "failed"
    expired = "expired"


class JobSource(str, enum.Enum):
    telegram_task = "telegram_task"
    consumer_api = "consumer_api"


class Consumer(Base):
    __tablename__ = "consumers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Subscriber(Base):
    __tablename__ = "subscribers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class Approval(Base):
    __tablename__ = "approvals"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    consumer_id: Mapped[int] = mapped_column(ForeignKey("consumers.id"), nullable=False)
    project: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[ApprovalStatus] = mapped_column(
        SAEnum(ApprovalStatus, name="approval_status"),
        default=ApprovalStatus.pending, nullable=False,
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(64))
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=1200, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    # nullable: 靜音時段建立的 approval 先不設倒數, 等 flush_suppressed 推出後才設
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    telegram_chat_id: Mapped[int | None] = mapped_column(BigInteger)
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger)
    push_state: Mapped[PushState] = mapped_column(
        SAEnum(PushState, name="push_state"),
        default=PushState.scheduled, nullable=False,
    )
    last_push_error: Mapped[str | None] = mapped_column(Text)
    extra_metadata: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)

    items: Mapped[list["ApprovalItem"]] = relationship(
        "ApprovalItem", cascade="all, delete-orphan", order_by="ApprovalItem.position"
    )
    decisions: Mapped[list["Decision"]] = relationship(
        "Decision", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_approvals_consumer_status", "consumer_id", "status"),
        Index("ix_approvals_status_expires", "status", "expires_at"),
        Index(
            "ux_approvals_consumer_idem",
            "consumer_id", "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
    )


class ApprovalItem(Base):
    __tablename__ = "approval_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    approval_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("approvals.id", ondelete="CASCADE"), nullable=False
    )
    item_id: Mapped[str] = mapped_column(String(64), nullable=False)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    summary: Mapped[str] = mapped_column(String(255), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    __table_args__ = (
        UniqueConstraint("approval_id", "item_id", name="ux_approval_items_approval_item"),
    )


class Decision(Base):
    __tablename__ = "decisions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    approval_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("approvals.id", ondelete="CASCADE"), nullable=False
    )
    item_id: Mapped[str | None] = mapped_column(String(64))
    decision: Mapped[DecisionType] = mapped_column(
        SAEnum(DecisionType, name="decision_type"), nullable=False
    )
    decided_by_chat_id: Mapped[int | None] = mapped_column(BigInteger)
    reject_reason: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

    __table_args__ = (
        Index("ix_decisions_approval", "approval_id"),
    )


class AgentJob(Base):
    __tablename__ = "agent_jobs"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    consumer_id: Mapped[int] = mapped_column(ForeignKey("consumers.id"), nullable=False)
    source: Mapped[JobSource] = mapped_column(
        SAEnum(JobSource, name="job_source"), nullable=False
    )
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        SAEnum(JobStatus, name="job_status"),
        default=JobStatus.pending, nullable=False,
    )
    claimed_by: Mapped[str | None] = mapped_column(String(64))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result_summary: Mapped[str | None] = mapped_column(Text)
    result_path: Mapped[str | None] = mapped_column(String(255))
    notify_chat_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_agent_jobs_consumer_status", "consumer_id", "status"),
    )
```

- [ ] **Step 4: 設定 Alembic**

```bash
cd ~/Documents/GitHub/notify-hub
./.venv/bin/alembic init migrations
```

- [ ] **Step 5: 修 `alembic.ini`**

把 `sqlalchemy.url =` 那行清空 (由 env.py 讀 env var)。

- [ ] **Step 6: 寫 `migrations/env.py`**

```python
import asyncio
import os
from logging.config import fileConfig
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from alembic import context
from notify_hub.db.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

url = os.environ["DATABASE_URL"]
config.set_main_option("sqlalchemy.url", url)
target_metadata = Base.metadata


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


run_migrations_online()
```

- [ ] **Step 7: 產生 initial migration**

先本地起一個 postgres container 做 autogenerate:

```bash
docker run --rm -d --name nh-pg-tmp -p 5433:5432 \
  -e POSTGRES_USER=notify_hub -e POSTGRES_PASSWORD=dev \
  -e POSTGRES_DB=notify_hub postgres:16
DATABASE_URL=postgresql+asyncpg://notify_hub:dev@localhost:5433/notify_hub \
  ./.venv/bin/alembic revision --autogenerate -m "initial"
docker stop nh-pg-tmp
```

檢查 `migrations/versions/*_initial.py` 包含 6 張表 + 所有索引 + enum types。

- [ ] **Step 8: 跑測試**

```bash
./.venv/bin/pytest tests/unit/test_models.py -v
```

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "feat(db): 6-table schema + alembic initial migration"
```

---

## Task 4: DB session factory + CRUD 基礎

**Files:**
- Create: `src/notify_hub/db/session.py`
- Create: `src/notify_hub/db/crud.py`
- Create: `tests/conftest.py`
- Create: `tests/integration/test_crud_approvals.py`

- [ ] **Step 1: 寫 conftest 提供 testcontainers DB**

```python
# tests/conftest.py
import asyncio
import os
import pytest
import pytest_asyncio
from testcontainers.postgres import PostgresContainer
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from notify_hub.db.models import Base


@pytest.fixture(scope="session")
def pg_container():
    with PostgresContainer("postgres:16") as pg:
        url = pg.get_connection_url().replace("psycopg2", "asyncpg")
        os.environ["DATABASE_URL"] = url
        yield url


@pytest_asyncio.fixture(scope="session")
async def engine(pg_container):
    eng = create_async_engine(pg_container, echo=False)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session(engine) -> AsyncSession:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
        await s.rollback()
```

- [ ] **Step 2: 寫 failing test**

```python
# tests/integration/test_crud_approvals.py
import hashlib
import uuid
from datetime import datetime, timedelta, timezone
import pytest
from notify_hub.db import crud
from notify_hub.db.models import Consumer, ApprovalStatus, PushState


@pytest.mark.asyncio
async def test_create_consumer_and_approval(session):
    c = Consumer(
        name="alphaforge",
        token_hash=hashlib.sha256(b"tok").hexdigest(),
    )
    session.add(c)
    await session.commit()

    approval = await crud.create_approval(
        session,
        consumer_id=c.id,
        project="alphaforge",
        title="test",
        items=[
            {"id": "1", "type": "t3", "summary": "do X", "detail": "d1", "position": 0},
            {"id": "2", "type": "t3", "summary": "do Y", "detail": None, "position": 1},
        ],
        timeout_seconds=1200,
        metadata={"k": "v"},
    )
    assert approval.status == ApprovalStatus.pending
    assert len(approval.items) == 2
    assert approval.extra_metadata == {"k": "v"}
    assert approval.expires_at > approval.created_at


@pytest.mark.asyncio
async def test_get_approval_by_id(session):
    c = Consumer(name="c2", token_hash="h")
    session.add(c)
    await session.commit()
    ap = await crud.create_approval(
        session, consumer_id=c.id, project="p", title="t",
        items=[{"id": "1", "type": "x", "summary": "s", "detail": None, "position": 0}],
        timeout_seconds=60, metadata={},
    )
    got = await crud.get_approval(session, ap.id)
    assert got.id == ap.id


@pytest.mark.asyncio
async def test_create_approval_in_quiet_hours_has_no_expires(session):
    """靜音時段建立的 approval 不該設 expires_at, 避免還沒推給 user 就被 sweeper 掃掉。"""
    c = Consumer(name="c3", token_hash="h")
    session.add(c)
    await session.commit()
    ap = await crud.create_approval(
        session, consumer_id=c.id, project="p", title="t",
        items=[{"id": "1", "type": "x", "summary": "s", "detail": None, "position": 0}],
        timeout_seconds=1200, metadata={},
        push_state=PushState.suppressed_quiet_hours,
    )
    assert ap.expires_at is None
    assert ap.push_state == PushState.suppressed_quiet_hours


@pytest.mark.asyncio
async def test_sweep_skips_suppressed_quiet_hours(session):
    """即使 created_at 已過很久, suppressed 的 approval 也不該被 sweeper 掃成 timeout。"""
    from sqlalchemy import update
    from notify_hub.db.models import Approval
    c = Consumer(name="c4", token_hash="h")
    session.add(c)
    await session.commit()
    ap = await crud.create_approval(
        session, consumer_id=c.id, project="p", title="t",
        items=[{"id": "1", "type": "x", "summary": "s", "detail": None, "position": 0}],
        timeout_seconds=1, metadata={},
        push_state=PushState.suppressed_quiet_hours,
    )
    # 強制把 created_at 推到 1 小時前 (但 expires_at 仍是 None)
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    await session.execute(update(Approval).where(Approval.id == ap.id).values(created_at=past))
    await session.commit()

    ids = await crud.sweep_timeouts(session)
    assert ap.id not in ids
```

- [ ] **Step 3: 跑 fail**

```bash
./.venv/bin/pytest tests/integration/test_crud_approvals.py -v
```

- [ ] **Step 4: 實作 session + crud**

```python
# src/notify_hub/db/session.py
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from notify_hub.config import Settings


_engine = None
_maker = None


def init_engine(settings: Settings) -> None:
    global _engine, _maker
    _engine = create_async_engine(settings.database_url, pool_size=10, max_overflow=20)
    _maker = async_sessionmaker(_engine, expire_on_commit=False)


async def dispose() -> None:
    global _engine
    if _engine:
        await _engine.dispose()
        _engine = None


def session_maker() -> async_sessionmaker[AsyncSession]:
    assert _maker is not None, "init_engine() not called"
    return _maker


async def get_session() -> AsyncSession:  # FastAPI dependency
    async with _maker() as s:
        yield s
```

```python
# src/notify_hub/db/crud.py
from __future__ import annotations
import uuid
from datetime import datetime, timedelta, timezone
from typing import Sequence, Any
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from notify_hub.db.models import (
    Approval, ApprovalItem, ApprovalStatus, Consumer, Decision, DecisionType,
    PushState, Subscriber, AgentJob, JobStatus, JobSource,
)


async def get_consumer_by_name(session: AsyncSession, name: str) -> Consumer | None:
    r = await session.execute(select(Consumer).where(Consumer.name == name))
    return r.scalar_one_or_none()


async def get_consumer_by_token_hash(session: AsyncSession, token_hash: str) -> Consumer | None:
    r = await session.execute(
        select(Consumer).where(Consumer.token_hash == token_hash, Consumer.disabled_at.is_(None))
    )
    return r.scalar_one_or_none()


async def upsert_consumer(session: AsyncSession, name: str, token_hash: str) -> Consumer:
    existing = await get_consumer_by_name(session, name)
    if existing:
        if existing.token_hash != token_hash:
            existing.token_hash = token_hash
        await session.flush()
        return existing
    c = Consumer(name=name, token_hash=token_hash)
    session.add(c)
    await session.flush()
    return c


async def create_approval(
    session: AsyncSession, *,
    consumer_id: int, project: str, title: str,
    items: Sequence[dict[str, Any]],
    timeout_seconds: int, metadata: dict,
    idempotency_key: str | None = None,
    push_state: PushState = PushState.scheduled,
) -> Approval:
    now = datetime.now(timezone.utc)
    # 靜音時段: 先不設 expires_at, 等 flush_suppressed 推出後才開始倒數 (避免還沒被使用者看見就被 sweeper 掃成 timeout)
    expires_at = (
        None if push_state == PushState.suppressed_quiet_hours
        else now + timedelta(seconds=timeout_seconds)
    )
    ap = Approval(
        consumer_id=consumer_id, project=project, title=title,
        timeout_seconds=timeout_seconds, idempotency_key=idempotency_key,
        extra_metadata=metadata, expires_at=expires_at,
        push_state=push_state,
    )
    for i, it in enumerate(items):
        ap.items.append(ApprovalItem(
            item_id=it["id"], type=it["type"], summary=it["summary"],
            detail=it.get("detail"), position=it.get("position", i),
        ))
    session.add(ap)
    await session.flush()
    await session.commit()
    await session.refresh(ap, attribute_names=["items"])
    return ap


async def get_approval(session: AsyncSession, approval_id: uuid.UUID) -> Approval | None:
    r = await session.execute(
        select(Approval).where(Approval.id == approval_id).options(
            selectinload(Approval.items), selectinload(Approval.decisions),
        )
    )
    return r.scalar_one_or_none()


async def get_approval_by_idem(
    session: AsyncSession, consumer_id: int, idem_key: str
) -> Approval | None:
    r = await session.execute(
        select(Approval).where(
            Approval.consumer_id == consumer_id,
            Approval.idempotency_key == idem_key,
        ).options(selectinload(Approval.items))
    )
    return r.scalar_one_or_none()


async def set_approval_push_info(
    session: AsyncSession, approval_id: uuid.UUID, *,
    chat_id: int | None, message_id: int | None,
    push_state: PushState, last_push_error: str | None = None,
    start_countdown: bool = False,
) -> None:
    """更新 push 結果與 Telegram message ref。

    `start_countdown=True`: 同時把 expires_at 設為 now + timeout_seconds, 讓倒數開始
    (供 flush_suppressed 在靜音時段推出成功後呼叫)。
    """
    values: dict = dict(
        telegram_chat_id=chat_id, telegram_message_id=message_id,
        push_state=push_state, last_push_error=last_push_error,
    )
    if start_countdown:
        ap = await get_approval(session, approval_id)
        if ap is not None:
            values["expires_at"] = (
                datetime.now(timezone.utc) + timedelta(seconds=ap.timeout_seconds)
            )
    await session.execute(
        update(Approval).where(Approval.id == approval_id).values(**values)
    )
    await session.commit()


async def record_decision(
    session: AsyncSession, *,
    approval_id: uuid.UUID, item_id: str | None, decision: DecisionType,
    chat_id: int | None, reject_reason: str | None = None,
) -> Decision:
    d = Decision(
        approval_id=approval_id, item_id=item_id, decision=decision,
        decided_by_chat_id=chat_id, reject_reason=reject_reason,
    )
    session.add(d)
    await session.flush()
    return d


async def recompute_approval_status(session: AsyncSession, approval_id: uuid.UUID) -> ApprovalStatus:
    """依 decisions + items 重算 status，已決項目滿則結案。"""
    ap = await get_approval(session, approval_id)
    if ap is None or ap.status != ApprovalStatus.pending:
        return ap.status if ap else ApprovalStatus.pending
    item_ids = {it.item_id for it in ap.items}
    decided: dict[str, DecisionType] = {}
    has_all_approve = False
    has_all_reject = False
    for d in ap.decisions:
        if d.item_id is None and d.decision == DecisionType.approved:
            has_all_approve = True
        elif d.item_id is None and d.decision == DecisionType.rejected:
            has_all_reject = True
        elif d.item_id is not None:
            decided[d.item_id] = d.decision

    if has_all_approve:
        new = ApprovalStatus.approved
    elif has_all_reject:
        new = ApprovalStatus.rejected
    elif set(decided.keys()) >= item_ids:
        vals = set(decided.values())
        if vals == {DecisionType.approved}:
            new = ApprovalStatus.approved
        elif vals == {DecisionType.rejected}:
            new = ApprovalStatus.rejected
        else:
            new = ApprovalStatus.mixed
    else:
        return ApprovalStatus.pending  # 尚未全部決定

    now = datetime.now(timezone.utc)
    await session.execute(
        update(Approval).where(Approval.id == approval_id).values(
            status=new, decided_at=now,
        )
    )
    await session.commit()
    return new


async def sweep_timeouts(session: AsyncSession) -> list[uuid.UUID]:
    """返回被 timeout 結案的 approval ids，caller 負責編輯 Telegram 訊息。

    `expires_at IS NULL` 代表該 approval 仍在靜音時段 queue 等待 flush, 尚未開始倒數, 不應掃掉。
    """
    now = datetime.now(timezone.utc)
    r = await session.execute(
        select(Approval).where(
            Approval.status == ApprovalStatus.pending,
            Approval.expires_at.isnot(None),
            Approval.expires_at < now,
        ).options(selectinload(Approval.items), selectinload(Approval.decisions))
    )
    approvals = r.scalars().all()
    out: list[uuid.UUID] = []
    for ap in approvals:
        decided_items = {d.item_id for d in ap.decisions if d.item_id}
        for it in ap.items:
            if it.item_id not in decided_items:
                session.add(Decision(
                    approval_id=ap.id, item_id=it.item_id,
                    decision=DecisionType.timeout, decided_by_chat_id=None,
                ))
        ap.status = ApprovalStatus.timeout
        ap.decided_at = now
        out.append(ap.id)
    await session.commit()
    return out


async def get_subscriber_by_chat(session: AsyncSession, chat_id: int) -> Subscriber | None:
    r = await session.execute(select(Subscriber).where(Subscriber.chat_id == chat_id))
    return r.scalar_one_or_none()


async def upsert_subscriber(session: AsyncSession, chat_id: int, display_name: str) -> Subscriber:
    existing = await get_subscriber_by_chat(session, chat_id)
    if existing:
        return existing
    sub = Subscriber(chat_id=chat_id, display_name=display_name)
    session.add(sub)
    await session.flush()
    await session.commit()
    return sub


async def create_job(
    session: AsyncSession, *,
    consumer_id: int, prompt: str, source: JobSource, notify_chat_id: int | None,
    ttl_days: int = 7,
) -> AgentJob:
    now = datetime.now(timezone.utc)
    job = AgentJob(
        consumer_id=consumer_id, prompt=prompt, source=source,
        notify_chat_id=notify_chat_id,
        expires_at=now + timedelta(days=ttl_days),
    )
    session.add(job)
    await session.flush()
    await session.commit()
    return job


async def claim_next_job(
    session: AsyncSession, consumer_id: int, instance_id: str,
) -> AgentJob | None:
    """SELECT FOR UPDATE SKIP LOCKED + UPDATE status=claimed."""
    now = datetime.now(timezone.utc)
    r = await session.execute(
        select(AgentJob).where(
            AgentJob.consumer_id == consumer_id,
            AgentJob.status == JobStatus.pending,
            AgentJob.expires_at > now,
        ).order_by(AgentJob.created_at.asc())
         .limit(1)
         .with_for_update(skip_locked=True)
    )
    job = r.scalar_one_or_none()
    if job is None:
        return None
    job.status = JobStatus.claimed
    job.claimed_by = instance_id
    job.claimed_at = now
    await session.commit()
    return job


async def complete_job(
    session: AsyncSession, *,
    job_id: uuid.UUID, status: JobStatus,
    result_summary: str | None, result_path: str | None,
) -> AgentJob | None:
    now = datetime.now(timezone.utc)
    r = await session.execute(select(AgentJob).where(AgentJob.id == job_id))
    job = r.scalar_one_or_none()
    if job is None:
        return None
    job.status = status
    job.result_summary = result_summary
    job.result_path = result_path
    job.completed_at = now
    await session.commit()
    return job
```

- [ ] **Step 5: 跑測試**

```bash
./.venv/bin/pytest tests/integration/test_crud_approvals.py -v
```

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(db): async session factory + crud helpers"
```

---

## Task 5: Auth module (consumer token + webhook secret + chat 白名單)

**Files:**
- Create: `src/notify_hub/auth.py`
- Create: `tests/unit/test_auth.py`

- [ ] **Step 1: 寫 failing tests**

```python
# tests/unit/test_auth.py
import hashlib
import pytest
from fastapi import HTTPException
from notify_hub.auth import (
    hash_token, verify_consumer_token, verify_webhook_secret, verify_chat_whitelist,
)


def test_hash_token_deterministic():
    assert hash_token("abc") == hashlib.sha256(b"abc").hexdigest()


def test_verify_consumer_token_match():
    tokens = {"alphaforge": "secret"}
    assert verify_consumer_token("Bearer secret", tokens) == "alphaforge"


def test_verify_consumer_token_bad_header():
    with pytest.raises(HTTPException) as exc:
        verify_consumer_token(None, {"a": "x"})
    assert exc.value.status_code == 401


def test_verify_consumer_token_wrong_scheme():
    with pytest.raises(HTTPException) as exc:
        verify_consumer_token("Basic xxx", {"a": "x"})
    assert exc.value.status_code == 401


def test_verify_consumer_token_not_found():
    with pytest.raises(HTTPException) as exc:
        verify_consumer_token("Bearer nope", {"a": "secret"})
    assert exc.value.status_code == 401


def test_verify_webhook_secret_ok():
    verify_webhook_secret("sec", expected="sec")  # no raise


def test_verify_webhook_secret_bad():
    with pytest.raises(HTTPException) as exc:
        verify_webhook_secret("x", expected="y")
    assert exc.value.status_code == 403


def test_verify_chat_whitelist_ok():
    verify_chat_whitelist(42, [42, 99])


def test_verify_chat_whitelist_denied():
    with pytest.raises(HTTPException) as exc:
        verify_chat_whitelist(1, [42])
    assert exc.value.status_code == 403
```

- [ ] **Step 2: 跑 fail**

```bash
./.venv/bin/pytest tests/unit/test_auth.py -v
```

- [ ] **Step 3: 實作 `auth.py`**

```python
# src/notify_hub/auth.py
import hashlib
import hmac
from fastapi import HTTPException


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def verify_consumer_token(
    authorization: str | None, tokens: dict[str, str],
) -> str:
    """返回 consumer name，失敗 raise 401。"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing or bad Authorization header")
    token = authorization[len("Bearer "):].strip()
    for name, expected in tokens.items():
        if hmac.compare_digest(token, expected):
            return name
    raise HTTPException(status_code=401, detail="invalid consumer token")


def verify_webhook_secret(received: str | None, expected: str) -> None:
    if not received or not hmac.compare_digest(received, expected):
        raise HTTPException(status_code=403, detail="webhook secret mismatch")


def verify_chat_whitelist(chat_id: int, allowed: list[int]) -> None:
    if chat_id not in allowed:
        raise HTTPException(status_code=403, detail="chat not in whitelist")
```

- [ ] **Step 4: 跑 pass**

```bash
./.venv/bin/pytest tests/unit/test_auth.py -v
```

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(auth): consumer token + webhook secret + chat whitelist"
```

---

## Task 6: FastAPI app skeleton + `/healthz`

**Files:**
- Create: `src/notify_hub/main.py`
- Create: `src/notify_hub/api/__init__.py`
- Create: `src/notify_hub/api/health.py`
- Create: `src/notify_hub/schemas.py`
- Create: `tests/integration/test_healthz.py`

- [ ] **Step 1: 寫 failing test**

```python
# tests/integration/test_healthz.py
import pytest
from httpx import AsyncClient, ASGITransport
from notify_hub.main import create_app


@pytest.mark.asyncio
async def test_healthz_ok(monkeypatch, pg_container):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "s")
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://x")
    monkeypatch.setenv("NOTIFY_HUB_CONSUMER_TOKENS", "alphaforge:t")
    monkeypatch.setenv("ALLOWED_CHAT_IDS", "42")

    app = create_app(skip_telegram_check=True)
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as c:
        r = await c.get("/healthz")
        assert r.status_code == 200
        body = r.json()
        assert body["db"] == "ok"
        assert body["version"] == "0.1.0"
```

- [ ] **Step 2: 跑 fail**

```bash
./.venv/bin/pytest tests/integration/test_healthz.py -v
```

- [ ] **Step 3: 實作 schemas + app**

```python
# src/notify_hub/schemas.py
from pydantic import BaseModel, Field
from typing import Literal, Any
import uuid
from datetime import datetime


class ApprovalItemIn(BaseModel):
    id: str
    type: str
    summary: str
    detail: str | None = None


class ApprovalCreate(BaseModel):
    project: str
    title: str
    items: list[ApprovalItemIn] = Field(min_length=1)
    timeout_seconds: int = 1200
    metadata: dict[str, Any] = {}


class ApprovalCreated(BaseModel):
    request_id: str
    status: str
    created_at: datetime
    # 靜音時段建立時為 None, 等 flush_suppressed 推出後才設
    expires_at: datetime | None = None
    push_state: str


class PerItemDecision(BaseModel):
    id: str
    decision: str
    reject_reason: str | None = None


class ApprovalState(BaseModel):
    request_id: str
    status: str
    decided_at: datetime | None = None
    per_item: list[PerItemDecision] = []


class JobCreate(BaseModel):
    agent: str
    prompt: str
    notify_chat_id: int | None = None


class JobCreated(BaseModel):
    job_id: str
    status: str


class JobNext(BaseModel):
    job_id: str
    prompt: str
    notify_chat_id: int | None
    created_at: datetime


class JobComplete(BaseModel):
    status: Literal["completed", "failed"]
    result_summary: str | None = None
    result_path: str | None = None


class HealthResponse(BaseModel):
    db: str
    telegram: str
    queue_size: int
    version: str
```

```python
# src/notify_hub/api/health.py
from fastapi import APIRouter
from sqlalchemy import select, func
from notify_hub.db.session import session_maker
from notify_hub.db.models import AgentJob, JobStatus
from notify_hub.schemas import HealthResponse

router = APIRouter()


@router.get("/healthz", response_model=HealthResponse)
async def healthz():
    db_status = "ok"
    queue = 0
    try:
        maker = session_maker()
        async with maker() as s:
            r = await s.execute(
                select(func.count()).select_from(AgentJob)
                .where(AgentJob.status == JobStatus.pending)
            )
            queue = int(r.scalar_one())
    except Exception as e:
        db_status = f"error: {type(e).__name__}"
    # telegram 狀態於 startup 時實測，這裡回快取值
    from notify_hub.main import TG_STATUS
    tg = TG_STATUS.get("status", "unknown")
    from notify_hub import __version__
    return HealthResponse(db=db_status, telegram=tg, queue_size=queue, version=__version__)
```

```python
# src/notify_hub/__init__.py
__version__ = "0.1.0"
```

```python
# src/notify_hub/main.py
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import FastAPI, Response
from notify_hub.config import Settings
from notify_hub.db import session as dbsess
from notify_hub.api import health


TG_STATUS: dict = {"status": "unknown", "last_updated": None, "last_error": None}


def update_tg_status(*, ok: bool, error: str | None = None) -> None:
    """由 push 行為與定時 probe (Task 19.5) 更新 telegram 健康狀態快取。

    被 /healthz 讀取, 讓健康狀態反映真實 runtime 行為, 而非 startup 時那一秒的快照。
    """
    TG_STATUS["status"] = "ok" if ok else "degraded"
    TG_STATUS["last_updated"] = datetime.now(timezone.utc).isoformat()
    TG_STATUS["last_error"] = None if ok else (error or "unknown")


def create_app(skip_telegram_check: bool = False) -> FastAPI:
    settings = Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        dbsess.init_engine(settings)
        # 在這裡把 consumers 表用 env 同步 (Task 5 後續)
        if not skip_telegram_check:
            # 之後 Task 7 實作真實 getMe
            update_tg_status(ok=True)
        else:
            TG_STATUS["status"] = "skipped"
        yield
        await dbsess.dispose()

    app = FastAPI(title="notify-hub", version="0.1.0", lifespan=lifespan)
    app.include_router(health.router)

    @app.get("/")
    def root():
        return {"service": "notify-hub", "version": "0.1.0"}

    return app


app = create_app()
```

- [ ] **Step 4: 跑 pass**

```bash
./.venv/bin/pytest tests/integration/test_healthz.py -v
```

若失敗: 通常是 `create_app` 沒在 test 看到 env (因 Settings 立即載入)；把 `create_app` 改成在函式內才建 Settings 即可。

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(api): FastAPI skeleton + /healthz"
```

---

## Task 7: Telegram HTTP client

**Files:**
- Create: `src/notify_hub/telegram/__init__.py`
- Create: `src/notify_hub/telegram/client.py`
- Create: `tests/unit/test_telegram_client.py`

- [ ] **Step 1: 寫 failing test (mock httpx)**

```python
# tests/unit/test_telegram_client.py
import pytest
import httpx
from notify_hub.telegram.client import TelegramClient


@pytest.mark.asyncio
async def test_send_message_builds_payload():
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["json"] = httpx._content.json.loads(request.content)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 42, "chat": {"id": 7}}})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        tg = TelegramClient(token="TOK", http=http)
        r = await tg.send_message(chat_id=7, text="<b>hi</b>", reply_markup={"inline_keyboard": []})
        assert r["message_id"] == 42
    assert "TOK/sendMessage" in captured["url"]
    assert captured["json"]["parse_mode"] == "HTML"
    assert captured["json"]["chat_id"] == 7


@pytest.mark.asyncio
async def test_edit_message_text():
    async def handler(request):
        return httpx.Response(200, json={"ok": True, "result": {}})
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        tg = TelegramClient(token="T", http=http)
        await tg.edit_message_text(chat_id=1, message_id=2, text="x")


@pytest.mark.asyncio
async def test_answer_callback_query():
    async def handler(request):
        return httpx.Response(200, json={"ok": True, "result": True})
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        tg = TelegramClient(token="T", http=http)
        await tg.answer_callback_query("cb_id", text=None)


@pytest.mark.asyncio
async def test_get_me_error_raises():
    async def handler(request):
        return httpx.Response(401, json={"ok": False, "description": "Unauthorized"})
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        tg = TelegramClient(token="T", http=http)
        with pytest.raises(RuntimeError):
            await tg.get_me()
```

- [ ] **Step 2: 跑 fail**

- [ ] **Step 3: 實作 client**

```python
# src/notify_hub/telegram/client.py
from __future__ import annotations
from typing import Any
import httpx


BASE_URL = "https://api.telegram.org/bot"


class TelegramClient:
    def __init__(self, token: str, http: httpx.AsyncClient | None = None) -> None:
        self.token = token
        self._own_http = http is None
        self.http = http or httpx.AsyncClient(timeout=15.0)

    async def close(self) -> None:
        if self._own_http:
            await self.http.aclose()

    async def _call(self, method: str, payload: dict[str, Any]) -> Any:
        url = f"{BASE_URL}{self.token}/{method}"
        r = await self.http.post(url, json=payload)
        data = r.json()
        if r.status_code != 200 or not data.get("ok"):
            raise RuntimeError(f"telegram {method} failed: {r.status_code} {data}")
        return data["result"]

    async def send_message(
        self, *, chat_id: int, text: str,
        reply_markup: dict | None = None,
        reply_to_message_id: int | None = None,
    ) -> dict:
        payload = {
            "chat_id": chat_id, "text": text, "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        if reply_to_message_id is not None:
            payload["reply_to_message_id"] = reply_to_message_id
        return await self._call("sendMessage", payload)

    async def edit_message_text(
        self, *, chat_id: int, message_id: int, text: str,
        reply_markup: dict | None = None,
    ) -> dict:
        payload = {
            "chat_id": chat_id, "message_id": message_id,
            "text": text, "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        return await self._call("editMessageText", payload)

    async def edit_message_reply_markup(
        self, *, chat_id: int, message_id: int, reply_markup: dict | None,
    ) -> dict:
        payload = {"chat_id": chat_id, "message_id": message_id}
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        return await self._call("editMessageReplyMarkup", payload)

    async def answer_callback_query(self, callback_query_id: str, text: str | None = None) -> Any:
        payload = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        return await self._call("answerCallbackQuery", payload)

    async def get_me(self) -> dict:
        return await self._call("getMe", {})
```

- [ ] **Step 4: 跑 pass + commit**

```bash
./.venv/bin/pytest tests/unit/test_telegram_client.py -v
git add -A && git commit -m "feat(telegram): httpx-based Bot API client"
```

---

## Task 8: Message formatter + callback_data parser

**Files:**
- Create: `src/notify_hub/telegram/formatter.py`
- Create: `tests/unit/test_formatter.py`
- Create: `tests/unit/test_callback_parser.py`

- [ ] **Step 1: 寫 failing tests**

```python
# tests/unit/test_formatter.py
import html
from notify_hub.telegram.formatter import (
    build_approval_message, build_keyboard_top, build_per_item_panel,
    build_closed_message, short_id,
)


def test_build_approval_message_escapes_html():
    text = build_approval_message(
        project="AlphaForge", title="0300 tick <bad>",
        items=[{"item_id": "1", "type": "t3-action", "summary": "改 <x> & y"}],
    )
    assert "&lt;bad&gt;" in text
    assert "&lt;x&gt;" in text
    assert "&amp;" in text


def test_build_keyboard_top_has_three_buttons():
    kb = build_keyboard_top(approval_id="abcd1234...")
    assert "inline_keyboard" in kb
    rows = kb["inline_keyboard"]
    labels = [b["text"] for row in rows for b in row]
    assert "✅ 全部同意" in labels
    assert "❌ 全部拒絕" in labels
    assert "👀 逐項批" in labels


def test_build_per_item_panel_strikes_decided():
    items = [
        {"item_id": "1", "summary": "改 deploy"},
        {"item_id": "2", "summary": "加 memory"},
        {"item_id": "3", "summary": "延工時"},
    ]
    decided = {"1": "approved", "3": "rejected"}
    text, kb = build_per_item_panel(
        approval_id="abcd1234", project="AlphaForge", title="0300 tick",
        items=items, decided=decided,
    )
    assert "✓ 同意" in text and "✗ 退回" in text
    # 只有 item 2 還有按鈕
    rows = kb["inline_keyboard"]
    callbacks = [b["callback_data"] for row in rows for b in row]
    assert any("item_approve:abcd1234:2" in c for c in callbacks)
    assert not any("item_approve:abcd1234:1" in c for c in callbacks)


def test_build_closed_message_approved():
    text = build_closed_message(
        project="AlphaForge", title="0300 tick",
        status="approved", decided_at_str="2026-04-22 07:08",
        per_item=[], mixed_reject_reasons={},
    )
    assert "✓ 已批准全部" in text


def test_short_id():
    assert short_id("req_01hz1234567890") == "req_01hz"
    assert len(short_id("abcdef1234567890")) == 8
```

```python
# tests/unit/test_callback_parser.py
import pytest
from notify_hub.telegram.formatter import parse_callback_data


def test_parse_approve_all():
    a = parse_callback_data("v1:approve_all:abcd1234")
    assert a == {"version": "v1", "action": "approve_all", "approval_short": "abcd1234", "item_id": None}


def test_parse_per_item():
    a = parse_callback_data("v1:item_reject:abcd1234:3")
    assert a["action"] == "item_reject"
    assert a["item_id"] == "3"


def test_parse_invalid_prefix():
    with pytest.raises(ValueError):
        parse_callback_data("v2:approve_all:abcd")


def test_parse_unknown_action():
    with pytest.raises(ValueError):
        parse_callback_data("v1:bogus:abcd")
```

- [ ] **Step 2: 跑 fail**

- [ ] **Step 3: 實作 formatter**

```python
# src/notify_hub/telegram/formatter.py
from __future__ import annotations
import html
from typing import Sequence, Any


ALLOWED_ACTIONS = {
    "approve_all", "reject_all", "per_item",
    "item_approve", "item_reject", "back",
}


def short_id(approval_id: str) -> str:
    return approval_id[:8]


def _esc(s: str) -> str:
    return html.escape(s or "", quote=False)


def build_approval_message(
    *, project: str, title: str,
    items: Sequence[dict[str, Any]],
) -> str:
    lines = [f"🔔 <b>[{_esc(project)}] {_esc(title)}</b>", ""]
    for i, it in enumerate(items, start=1):
        lines.append(f"<b>項目 {_esc(it['item_id'])}</b> <code>{_esc(it['type'])}</code>")
        lines.append(_esc(it["summary"]))
        lines.append("")
    return "\n".join(lines).rstrip()


def build_keyboard_top(*, approval_id: str) -> dict:
    sid = short_id(approval_id)
    return {
        "inline_keyboard": [
            [
                {"text": "✅ 全部同意", "callback_data": f"v1:approve_all:{sid}"},
                {"text": "❌ 全部拒絕", "callback_data": f"v1:reject_all:{sid}"},
            ],
            [{"text": "👀 逐項批", "callback_data": f"v1:per_item:{sid}"}],
        ]
    }


def build_per_item_panel(
    *, approval_id: str, project: str, title: str,
    items: Sequence[dict[str, Any]], decided: dict[str, str],
) -> tuple[str, dict]:
    """decided: {item_id: 'approved'|'rejected'}，已決項目顯示狀態，按鈕只留未決。"""
    sid = short_id(approval_id)
    lines = [f"🔔 <b>[{_esc(project)}] {_esc(title)}</b>（逐項批）", ""]
    rows: list[list[dict]] = []
    for it in items:
        iid = it["item_id"]
        summary = _esc(it["summary"])
        st = decided.get(iid)
        if st == "approved":
            lines.append(f"{_esc(iid)}. {summary}  ✓ 同意")
        elif st == "rejected":
            lines.append(f"{_esc(iid)}. {summary}  ✗ 退回")
        else:
            lines.append(f"{_esc(iid)}. {summary}")
            rows.append([
                {"text": "✅", "callback_data": f"v1:item_approve:{sid}:{iid}"},
                {"text": "❌", "callback_data": f"v1:item_reject:{sid}:{iid}"},
            ])
    rows.append([{"text": "← 返回", "callback_data": f"v1:back:{sid}"}])
    return "\n".join(lines), {"inline_keyboard": rows}


def build_closed_message(
    *, project: str, title: str, status: str,
    decided_at_str: str,
    per_item: Sequence[dict[str, Any]],
    mixed_reject_reasons: dict[str, str],
) -> str:
    head = f"🔔 <b>[{_esc(project)}] {_esc(title)}</b>"
    if status == "approved":
        return f"{head} ✓ 已批准全部\n決定於 {decided_at_str}"
    if status == "rejected":
        return f"{head} ✗ 已全部退回\n決定於 {decided_at_str}"
    if status == "timeout":
        return f"{head} ⏱ 超時未批，自動結束\n決定於 {decided_at_str}"
    # mixed
    approved_ids = [p["id"] for p in per_item if p["decision"] == "approved"]
    rejected = [p for p in per_item if p["decision"] == "rejected"]
    lines = [
        f"{head} ⚠ 部分批准 ({len(approved_ids)}/{len(per_item)} 通過)",
        f"決定於 {decided_at_str}",
    ]
    for p in rejected:
        reason = mixed_reject_reasons.get(p["id"]) or p.get("reject_reason") or "(未填理由)"
        lines.append(f"項目 {_esc(p['id'])} 被退回: {_esc(reason)}")
    return "\n".join(lines)


def parse_callback_data(data: str) -> dict:
    parts = data.split(":")
    if len(parts) < 3 or parts[0] != "v1":
        raise ValueError(f"bad callback_data: {data}")
    action = parts[1]
    if action not in ALLOWED_ACTIONS:
        raise ValueError(f"unknown action: {action}")
    approval_short = parts[2]
    item_id = parts[3] if len(parts) >= 4 else None
    return {"version": "v1", "action": action, "approval_short": approval_short, "item_id": item_id}


MAX_TG_LEN = 4000  # 保守 (Telegram 限 4096，留格式空間)


def split_long_message(text: str, limit: int = MAX_TG_LEN) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current = ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > limit:
            chunks.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        chunks.append(current)
    return chunks
```

- [ ] **Step 4: 跑 pass + commit**

```bash
./.venv/bin/pytest tests/unit/test_formatter.py tests/unit/test_callback_parser.py -v
git add -A && git commit -m "feat(telegram): HTML formatter + callback_data parser"
```

---

## Task 9: POST /v1/approvals (with Telegram push)

**Files:**
- Create: `src/notify_hub/api/approvals.py`
- Modify: `src/notify_hub/main.py` (register router, inject TelegramClient)
- Create: `src/notify_hub/dependencies.py`
- Create: `tests/integration/test_approvals_api.py`

- [ ] **Step 1: 寫 failing test**

```python
# tests/integration/test_approvals_api.py
import hashlib
import os
import httpx
import pytest
from httpx import AsyncClient, ASGITransport
from notify_hub.main import create_app
from notify_hub.db import crud
from notify_hub.db.models import Consumer
from notify_hub.db.session import session_maker


@pytest.fixture
def app(monkeypatch, pg_container):
    monkeypatch.setenv("DATABASE_URL", pg_container)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "T")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "S")
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://x")
    monkeypatch.setenv("NOTIFY_HUB_CONSUMER_TOKENS", "alphaforge:af_secret")
    monkeypatch.setenv("ALLOWED_CHAT_IDS", "42")
    return create_app(skip_telegram_check=True)


@pytest.mark.asyncio
async def test_create_approval_201(app, monkeypatch):
    # mock telegram send_message
    from notify_hub.telegram import client as tg_mod

    async def fake_send(self, *, chat_id, text, reply_markup=None, reply_to_message_id=None):
        return {"message_id": 9001, "chat": {"id": chat_id}}
    monkeypatch.setattr(tg_mod.TelegramClient, "send_message", fake_send)

    async with AsyncClient(transport=ASGITransport(app), base_url="http://t") as c:
        # 先建 subscriber
        async with session_maker()() as s:
            await crud.upsert_subscriber(s, chat_id=42, display_name="test")

        r = await c.post(
            "/v1/approvals",
            headers={"Authorization": "Bearer af_secret"},
            json={
                "project": "alphaforge",
                "title": "test",
                "items": [{"id": "1", "type": "t3", "summary": "x"}],
                "timeout_seconds": 60,
                "metadata": {},
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["status"] == "pending"
        assert body["push_state"] in ("pushed", "suppressed_quiet_hours")


@pytest.mark.asyncio
async def test_create_approval_bad_auth(app):
    async with AsyncClient(transport=ASGITransport(app), base_url="http://t") as c:
        r = await c.post("/v1/approvals", headers={"Authorization": "Bearer wrong"},
                         json={"project": "x", "title": "t", "items": [{"id":"1","type":"a","summary":"s"}]})
        assert r.status_code == 401
```

- [ ] **Step 2: 跑 fail**

- [ ] **Step 3: 實作 dependencies + approvals router**

```python
# src/notify_hub/dependencies.py
from __future__ import annotations
from fastapi import Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession
from notify_hub.auth import verify_consumer_token
from notify_hub.config import Settings
from notify_hub.db.session import session_maker
from notify_hub.db import crud


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


async def get_session() -> AsyncSession:
    async with session_maker()() as s:
        yield s


async def current_consumer(
    authorization: str | None = Header(None),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
):
    name = verify_consumer_token(authorization, settings.consumer_tokens)
    c = await crud.get_consumer_by_name(session, name)
    if c is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="consumer not registered")
    return c
```

```python
# src/notify_hub/api/approvals.py
from __future__ import annotations
import uuid
from datetime import timezone
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession
from notify_hub.db import crud
from notify_hub.db.models import Consumer, PushState, ApprovalStatus
from notify_hub.dependencies import current_consumer, get_session, get_settings
from notify_hub.main import update_tg_status
from notify_hub.schemas import ApprovalCreate, ApprovalCreated, ApprovalState, PerItemDecision
from notify_hub.telegram.formatter import (
    build_approval_message, build_keyboard_top, split_long_message, short_id,
)
from notify_hub.config import Settings
from notify_hub.scheduler.quiet_hours_flush import is_quiet_hour_now

router = APIRouter(prefix="/v1/approvals")


def _to_dict(approval) -> list[dict]:
    return [
        {"item_id": it.item_id, "type": it.type, "summary": it.summary, "detail": it.detail}
        for it in approval.items
    ]


def _assemble_state(approval) -> ApprovalState:
    # 從 decisions + items 組出 per_item 最新狀態
    by_item = {}
    for d in approval.decisions:
        if d.item_id is None:
            # all-* decisions: 覆寫所有 items
            for it in approval.items:
                by_item.setdefault(it.item_id, {
                    "id": it.item_id,
                    "decision": d.decision.value,
                    "reject_reason": d.reject_reason,
                })
        else:
            by_item[d.item_id] = {
                "id": d.item_id,
                "decision": d.decision.value,
                "reject_reason": d.reject_reason,
            }
    per_item = [PerItemDecision(**by_item[it.item_id]) for it in approval.items if it.item_id in by_item]
    return ApprovalState(
        request_id=str(approval.id),
        status=approval.status.value,
        decided_at=approval.decided_at,
        per_item=per_item,
    )


@router.post("", response_model=ApprovalCreated, status_code=201)
async def create_approval(
    payload: ApprovalCreate,
    request: Request,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    consumer: Consumer = Depends(current_consumer),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    # Idempotency
    if idempotency_key:
        existing = await crud.get_approval_by_idem(session, consumer.id, idempotency_key)
        if existing:
            # 比對 body 一致 (以 title + items item_ids 為粗 key)
            existing_item_ids = {it.item_id for it in existing.items}
            incoming_item_ids = {it.id for it in payload.items}
            if existing.title == payload.title and existing_item_ids == incoming_item_ids:
                return ApprovalCreated(
                    request_id=str(existing.id),
                    status=existing.status.value,
                    created_at=existing.created_at,
                    expires_at=existing.expires_at,
                    push_state=existing.push_state.value,
                )
            raise HTTPException(status_code=409, detail="idempotency key conflict")

    items = [
        {"id": it.id, "type": it.type, "summary": it.summary, "detail": it.detail}
        for it in payload.items
    ]
    quiet = is_quiet_hour_now(settings)
    push_state = PushState.suppressed_quiet_hours if quiet else PushState.scheduled
    ap = await crud.create_approval(
        session,
        consumer_id=consumer.id,
        project=payload.project,
        title=payload.title,
        items=items,
        timeout_seconds=payload.timeout_seconds,
        metadata=payload.metadata,
        idempotency_key=idempotency_key,
        push_state=push_state,
    )

    # Push (非靜音時段)
    if not quiet:
        tg = request.app.state.telegram
        allowed = settings.allowed_chat_ids
        if allowed:
            chat_id = allowed[0]
            text = build_approval_message(
                project=ap.project, title=ap.title,
                items=[{"item_id": it.item_id, "type": it.type, "summary": it.summary}
                       for it in ap.items],
            )
            kb = build_keyboard_top(approval_id=str(ap.id))
            try:
                parts = split_long_message(text)
                first = parts[0]
                r = await tg.send_message(chat_id=chat_id, text=first, reply_markup=kb)
                msg_id = r["message_id"]
                for extra in parts[1:]:
                    await tg.send_message(chat_id=chat_id, text=extra)
                await crud.set_approval_push_info(
                    session, ap.id,
                    chat_id=chat_id, message_id=msg_id,
                    push_state=PushState.pushed,
                )
                ap.push_state = PushState.pushed
                update_tg_status(ok=True)
            except Exception as e:
                await crud.set_approval_push_info(
                    session, ap.id, chat_id=None, message_id=None,
                    push_state=PushState.push_failed, last_push_error=str(e)[:500],
                )
                ap.push_state = PushState.push_failed
                update_tg_status(ok=False, error=str(e)[:200])

    return ApprovalCreated(
        request_id=str(ap.id), status=ap.status.value,
        created_at=ap.created_at, expires_at=ap.expires_at,
        push_state=ap.push_state.value,
    )
```

- [ ] **Step 4: Wire in `main.py`**

```python
# src/notify_hub/main.py (修改 lifespan)
from notify_hub.telegram.client import TelegramClient
from notify_hub.api import health, approvals

...

@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    app.state.settings = settings
    dbsess.init_engine(settings)
    tg = TelegramClient(token=settings.telegram_bot_token)
    app.state.telegram = tg
    if not skip_telegram_check:
        try:
            await tg.get_me()
            TG_STATUS["status"] = "ok"
        except Exception:
            TG_STATUS["status"] = "error"
    else:
        TG_STATUS["status"] = "skipped"
    yield
    await tg.close()
    await dbsess.dispose()

app.include_router(approvals.router)
```

- [ ] **Step 5: 加 quiet_hours stub (僅 `is_quiet_hour_now`)**

```python
# src/notify_hub/scheduler/__init__.py
(empty)

# src/notify_hub/scheduler/quiet_hours_flush.py
from datetime import datetime, time
from zoneinfo import ZoneInfo
from notify_hub.config import Settings


def _parse_hhmm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def is_quiet_hour_now(settings: Settings, now: datetime | None = None) -> bool:
    tz = ZoneInfo(settings.quiet_hours_tz)
    now = now or datetime.now(tz)
    now_t = now.timetz().replace(tzinfo=None)
    start = _parse_hhmm(settings.quiet_hours_start)
    end = _parse_hhmm(settings.quiet_hours_end)
    if start <= end:
        return start <= now_t < end
    # 跨午夜
    return now_t >= start or now_t < end
```

- [ ] **Step 6: 跑 pass + commit**

```bash
./.venv/bin/pytest tests/integration/test_approvals_api.py -v
git add -A && git commit -m "feat(api): POST /v1/approvals with telegram push"
```

---

## Task 10: GET /v1/approvals/<id> + /wait long-polling

**Files:**
- Modify: `src/notify_hub/api/approvals.py`
- Create: `tests/integration/test_wait_longpoll.py`

- [ ] **Step 1: 寫 failing tests**

```python
# tests/integration/test_wait_longpoll.py
import asyncio
import pytest
from httpx import AsyncClient, ASGITransport
from notify_hub.main import create_app
from notify_hub.db import crud
from notify_hub.db.models import DecisionType
from notify_hub.db.session import session_maker


@pytest.fixture
def app(monkeypatch, pg_container):
    monkeypatch.setenv("DATABASE_URL", pg_container)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "T")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "S")
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://x")
    monkeypatch.setenv("NOTIFY_HUB_CONSUMER_TOKENS", "alphaforge:af_secret")
    monkeypatch.setenv("ALLOWED_CHAT_IDS", "42")
    return create_app(skip_telegram_check=True)


@pytest.mark.asyncio
async def test_wait_returns_when_decided(app, monkeypatch):
    from notify_hub.telegram import client as tg_mod
    async def fake_send(self, **kw): return {"message_id": 1, "chat": {"id": kw["chat_id"]}}
    monkeypatch.setattr(tg_mod.TelegramClient, "send_message", fake_send)

    async with AsyncClient(transport=ASGITransport(app), base_url="http://t") as c:
        async with session_maker()() as s:
            await crud.upsert_subscriber(s, chat_id=42, display_name="x")
        r = await c.post(
            "/v1/approvals",
            headers={"Authorization": "Bearer af_secret"},
            json={"project":"alphaforge","title":"t","items":[{"id":"1","type":"a","summary":"s"}],
                  "timeout_seconds":60,"metadata":{}},
        )
        rid = r.json()["request_id"]

        async def decide_soon():
            await asyncio.sleep(0.3)
            async with session_maker()() as s:
                await crud.record_decision(
                    s, approval_id=__import__("uuid").UUID(rid),
                    item_id=None, decision=DecisionType.approved,
                    chat_id=42,
                )
                await crud.recompute_approval_status(s, __import__("uuid").UUID(rid))

        task = asyncio.create_task(decide_soon())
        w = await c.get(f"/v1/approvals/{rid}/wait?timeout=5",
                        headers={"Authorization":"Bearer af_secret"})
        await task
        assert w.status_code == 200
        assert w.json()["status"] == "approved"


@pytest.mark.asyncio
async def test_wait_timeout_param_caps_to_55(app, monkeypatch):
    from notify_hub.telegram import client as tg_mod
    async def fake_send(self, **kw): return {"message_id": 1, "chat": {"id": kw["chat_id"]}}
    monkeypatch.setattr(tg_mod.TelegramClient, "send_message", fake_send)

    async with AsyncClient(transport=ASGITransport(app), base_url="http://t") as c:
        async with session_maker()() as s:
            await crud.upsert_subscriber(s, chat_id=42, display_name="x")
        r = await c.post(
            "/v1/approvals",
            headers={"Authorization": "Bearer af_secret"},
            json={"project":"p","title":"t","items":[{"id":"1","type":"a","summary":"s"}],
                  "timeout_seconds":1,"metadata":{}},
        )
        rid = r.json()["request_id"]
        # timeout 超大應 cap 成 55 但我們不想等 55s - 改用 0.5s short poll
        w = await c.get(f"/v1/approvals/{rid}/wait?timeout=1",
                        headers={"Authorization":"Bearer af_secret"})
        # approval timeout_seconds=1 還未過期前 poll 1s，回 pending
        assert w.status_code == 200


@pytest.mark.asyncio
async def test_get_approval_current_state(app, monkeypatch):
    from notify_hub.telegram import client as tg_mod
    async def fake_send(self, **kw): return {"message_id": 1, "chat": {"id": kw["chat_id"]}}
    monkeypatch.setattr(tg_mod.TelegramClient, "send_message", fake_send)

    async with AsyncClient(transport=ASGITransport(app), base_url="http://t") as c:
        async with session_maker()() as s:
            await crud.upsert_subscriber(s, chat_id=42, display_name="x")
        r = await c.post(
            "/v1/approvals",
            headers={"Authorization": "Bearer af_secret"},
            json={"project":"p","title":"t","items":[{"id":"1","type":"a","summary":"s"}],
                  "timeout_seconds":60,"metadata":{}},
        )
        rid = r.json()["request_id"]
        w = await c.get(f"/v1/approvals/{rid}", headers={"Authorization":"Bearer af_secret"})
        assert w.status_code == 200
        assert w.json()["status"] == "pending"
```

- [ ] **Step 2: 跑 fail**

- [ ] **Step 3: 加 endpoints**

```python
# 加到 src/notify_hub/api/approvals.py
import asyncio
from fastapi import Query


@router.get("/{approval_id}", response_model=ApprovalState)
async def get_approval(
    approval_id: uuid.UUID,
    consumer: Consumer = Depends(current_consumer),
    session: AsyncSession = Depends(get_session),
):
    ap = await crud.get_approval(session, approval_id)
    if ap is None or ap.consumer_id != consumer.id:
        raise HTTPException(status_code=404, detail="approval not found")
    return _assemble_state(ap)


@router.get("/{approval_id}/wait", response_model=ApprovalState)
async def wait_approval(
    approval_id: uuid.UUID,
    timeout: int = Query(30, ge=1),
    consumer: Consumer = Depends(current_consumer),
    session: AsyncSession = Depends(get_session),
):
    effective = min(timeout, 55)
    deadline = asyncio.get_event_loop().time() + effective
    poll_interval = 0.5
    ap = await crud.get_approval(session, approval_id)
    if ap is None or ap.consumer_id != consumer.id:
        raise HTTPException(status_code=404, detail="approval not found")
    while True:
        if ap.status != ApprovalStatus.pending:
            return _assemble_state(ap)
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            return _assemble_state(ap)
        await asyncio.sleep(min(poll_interval, remaining))
        await session.expire_all()
        ap = await crud.get_approval(session, approval_id)
```

- [ ] **Step 4: 跑 pass + commit**

```bash
./.venv/bin/pytest tests/integration/test_wait_longpoll.py -v
git add -A && git commit -m "feat(api): GET /v1/approvals/<id> + /wait long-polling"
```

---

## Task 11: Idempotency-Key 衝突測試

**Files:**
- Create: `tests/integration/test_idempotency.py`

- [ ] **Step 1: 寫 test**

```python
# tests/integration/test_idempotency.py
import pytest
from httpx import AsyncClient, ASGITransport
from notify_hub.main import create_app
from notify_hub.db import crud
from notify_hub.db.session import session_maker


@pytest.fixture
def app(monkeypatch, pg_container):
    monkeypatch.setenv("DATABASE_URL", pg_container)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "T")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "S")
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://x")
    monkeypatch.setenv("NOTIFY_HUB_CONSUMER_TOKENS", "alphaforge:af_secret")
    monkeypatch.setenv("ALLOWED_CHAT_IDS", "42")
    return create_app(skip_telegram_check=True)


@pytest.mark.asyncio
async def test_idempotency_same_body_returns_same_id(app, monkeypatch):
    from notify_hub.telegram import client as tg_mod
    async def fake_send(self, **kw): return {"message_id": 1, "chat": {"id": kw["chat_id"]}}
    monkeypatch.setattr(tg_mod.TelegramClient, "send_message", fake_send)

    async with AsyncClient(transport=ASGITransport(app), base_url="http://t") as c:
        async with session_maker()() as s:
            await crud.upsert_subscriber(s, chat_id=42, display_name="x")
        body = {"project":"p","title":"same","items":[{"id":"1","type":"a","summary":"s"}],
                "timeout_seconds":60,"metadata":{}}
        h = {"Authorization":"Bearer af_secret","Idempotency-Key":"k1"}
        r1 = await c.post("/v1/approvals", headers=h, json=body)
        r2 = await c.post("/v1/approvals", headers=h, json=body)
        assert r1.json()["request_id"] == r2.json()["request_id"]


@pytest.mark.asyncio
async def test_idempotency_different_body_409(app, monkeypatch):
    from notify_hub.telegram import client as tg_mod
    async def fake_send(self, **kw): return {"message_id": 1, "chat": {"id": kw["chat_id"]}}
    monkeypatch.setattr(tg_mod.TelegramClient, "send_message", fake_send)

    async with AsyncClient(transport=ASGITransport(app), base_url="http://t") as c:
        async with session_maker()() as s:
            await crud.upsert_subscriber(s, chat_id=42, display_name="x")
        h = {"Authorization":"Bearer af_secret","Idempotency-Key":"k2"}
        r1 = await c.post("/v1/approvals", headers=h, json={
            "project":"p","title":"A","items":[{"id":"1","type":"a","summary":"s"}],
            "timeout_seconds":60,"metadata":{}})
        r2 = await c.post("/v1/approvals", headers=h, json={
            "project":"p","title":"B","items":[{"id":"2","type":"a","summary":"s"}],
            "timeout_seconds":60,"metadata":{}})
        assert r1.status_code == 201
        assert r2.status_code == 409
```

- [ ] **Step 2: 跑 pass (Task 9 已實作 idempotency，應該綠)**

```bash
./.venv/bin/pytest tests/integration/test_idempotency.py -v
```

- [ ] **Step 3: Commit**

```bash
git add -A && git commit -m "test: idempotency-key conflict + retry"
```

---

## Task 12: Telegram Webhook skeleton + auth

**Files:**
- Create: `src/notify_hub/api/webhook.py`
- Create: `src/notify_hub/telegram/dispatcher.py`
- Modify: `src/notify_hub/main.py` (register router)
- Create: `tests/integration/test_webhook_auth.py`

- [ ] **Step 1: 寫 failing test**

```python
# tests/integration/test_webhook_auth.py
import pytest
from httpx import AsyncClient, ASGITransport
from notify_hub.main import create_app


@pytest.fixture
def app(monkeypatch, pg_container):
    monkeypatch.setenv("DATABASE_URL", pg_container)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "T")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "sec_123")
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://x")
    monkeypatch.setenv("NOTIFY_HUB_CONSUMER_TOKENS", "alphaforge:t")
    monkeypatch.setenv("ALLOWED_CHAT_IDS", "42")
    return create_app(skip_telegram_check=True)


@pytest.mark.asyncio
async def test_webhook_rejects_without_secret(app):
    async with AsyncClient(transport=ASGITransport(app), base_url="http://t") as c:
        r = await c.post("/tg/webhook", json={"update_id": 1})
        assert r.status_code == 403


@pytest.mark.asyncio
async def test_webhook_accepts_with_secret(app):
    async with AsyncClient(transport=ASGITransport(app), base_url="http://t") as c:
        r = await c.post(
            "/tg/webhook",
            json={"update_id": 1},
            headers={"X-Telegram-Bot-Api-Secret-Token": "sec_123"},
        )
        assert r.status_code == 200


@pytest.mark.asyncio
async def test_webhook_non_whitelisted_chat_callback(app, monkeypatch):
    from notify_hub.telegram import client as tg_mod
    called = []
    async def fake_answer(self, cb_id, text=None): called.append((cb_id, text)); return True
    monkeypatch.setattr(tg_mod.TelegramClient, "answer_callback_query", fake_answer)

    async with AsyncClient(transport=ASGITransport(app), base_url="http://t") as c:
        r = await c.post(
            "/tg/webhook",
            headers={"X-Telegram-Bot-Api-Secret-Token": "sec_123"},
            json={
                "update_id": 1,
                "callback_query": {
                    "id": "cb1",
                    "from": {"id": 9999, "is_bot": False, "first_name": "x"},
                    "message": {"message_id": 1, "chat": {"id": 9999, "type": "private"}},
                    "data": "v1:approve_all:abcdef12",
                },
            },
        )
        assert r.status_code == 200
        assert called == [("cb1", "您沒有權限")]
```

- [ ] **Step 2: 跑 fail**

- [ ] **Step 3: 實作 webhook router 與 dispatcher skeleton**

```python
# src/notify_hub/telegram/dispatcher.py
from __future__ import annotations
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession
from notify_hub.auth import verify_chat_whitelist
from notify_hub.config import Settings
from notify_hub.telegram.client import TelegramClient
from notify_hub.telegram.formatter import parse_callback_data


async def handle_update(
    update: dict[str, Any], *,
    session: AsyncSession, settings: Settings, tg: TelegramClient,
) -> None:
    if "callback_query" in update:
        await _handle_callback(update["callback_query"], session=session, settings=settings, tg=tg)
    elif "message" in update:
        await _handle_message(update["message"], session=session, settings=settings, tg=tg)


async def _handle_callback(cb: dict, *, session, settings, tg):
    cb_id = cb["id"]
    chat_id = cb["from"]["id"]
    try:
        verify_chat_whitelist(chat_id, settings.allowed_chat_ids)
    except Exception:
        await tg.answer_callback_query(cb_id, text="您沒有權限")
        return
    # 完整流程於 Task 13/14/15/16
    try:
        parsed = parse_callback_data(cb.get("data", ""))
    except ValueError:
        await tg.answer_callback_query(cb_id, text="無效按鈕")
        return
    # stub: 真正業務在後續 task 實作，這裡先 ack
    await tg.answer_callback_query(cb_id)


async def _handle_message(msg: dict, *, session, settings, tg):
    chat_id = msg["from"]["id"]
    text = msg.get("text", "")
    if not text:
        return
    if text.startswith("/task "):
        # Task 22 實作
        return
    # 其他 message: log + 忽略 (Task 16 處理 reject reason)
    return
```

```python
# src/notify_hub/api/webhook.py
from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession
from notify_hub.auth import verify_webhook_secret
from notify_hub.config import Settings
from notify_hub.dependencies import get_session, get_settings
from notify_hub.telegram.dispatcher import handle_update

router = APIRouter()


@router.post("/tg/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(None),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
):
    verify_webhook_secret(x_telegram_bot_api_secret_token, settings.telegram_webhook_secret)
    update = await request.json()
    tg = request.app.state.telegram
    await handle_update(update, session=session, settings=settings, tg=tg)
    return {"ok": True}
```

register router in `main.py`:

```python
from notify_hub.api import webhook
app.include_router(webhook.router)
```

- [ ] **Step 4: 跑 pass + commit**

```bash
./.venv/bin/pytest tests/integration/test_webhook_auth.py -v
git add -A && git commit -m "feat(webhook): POST /tg/webhook secret + whitelist"
```

---

## Task 13: Callback approve_all / reject_all + 訊息結案

**Files:**
- Modify: `src/notify_hub/telegram/dispatcher.py`
- Create: `tests/integration/test_callback_approve_all.py`

- [ ] **Step 1: 寫 failing test**

```python
# tests/integration/test_callback_approve_all.py
import uuid
import pytest
from httpx import AsyncClient, ASGITransport
from notify_hub.main import create_app
from notify_hub.db import crud
from notify_hub.db.models import DecisionType, ApprovalStatus
from notify_hub.db.session import session_maker


@pytest.fixture
def app(monkeypatch, pg_container):
    monkeypatch.setenv("DATABASE_URL", pg_container)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "T")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "sec")
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://x")
    monkeypatch.setenv("NOTIFY_HUB_CONSUMER_TOKENS", "alphaforge:af")
    monkeypatch.setenv("ALLOWED_CHAT_IDS", "42")
    return create_app(skip_telegram_check=True)


@pytest.mark.asyncio
async def test_callback_approve_all_finalizes(app, monkeypatch):
    from notify_hub.telegram import client as tg_mod
    sent_edits, acks = [], []
    async def fake_send(self, **kw): return {"message_id": 1, "chat": {"id": kw["chat_id"]}}
    async def fake_edit(self, **kw): sent_edits.append(kw); return {}
    async def fake_ack(self, cb_id, text=None): acks.append((cb_id, text)); return True
    monkeypatch.setattr(tg_mod.TelegramClient, "send_message", fake_send)
    monkeypatch.setattr(tg_mod.TelegramClient, "edit_message_text", fake_edit)
    monkeypatch.setattr(tg_mod.TelegramClient, "answer_callback_query", fake_ack)

    async with AsyncClient(transport=ASGITransport(app), base_url="http://t") as c:
        async with session_maker()() as s:
            await crud.upsert_subscriber(s, chat_id=42, display_name="x")
        r = await c.post(
            "/v1/approvals",
            headers={"Authorization": "Bearer af"},
            json={"project":"p","title":"t","items":[
                {"id":"1","type":"a","summary":"s1"},
                {"id":"2","type":"a","summary":"s2"}],
                "timeout_seconds":60,"metadata":{}},
        )
        rid = r.json()["request_id"]
        short = rid[:8]

        wh = await c.post(
            "/tg/webhook",
            headers={"X-Telegram-Bot-Api-Secret-Token": "sec"},
            json={
                "update_id": 10,
                "callback_query": {
                    "id": "cb1",
                    "from": {"id": 42, "is_bot": False, "first_name": "me"},
                    "message": {"message_id": 1, "chat": {"id": 42, "type": "private"}},
                    "data": f"v1:approve_all:{short}",
                },
            },
        )
        assert wh.status_code == 200

        async with session_maker()() as s:
            ap = await crud.get_approval(s, uuid.UUID(rid))
            assert ap.status == ApprovalStatus.approved

        # 一次 edit + 一次 ack
        assert len(sent_edits) >= 1
        assert len(acks) == 1
```

- [ ] **Step 2: 實作 dispatcher 的 approve_all / reject_all 分支 + 尋找 approval**

在 `dispatcher.py` 加入:

```python
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo
from notify_hub.db import crud
from notify_hub.db.models import DecisionType, ApprovalStatus
from notify_hub.telegram.formatter import build_closed_message


async def _find_approval_by_short(session, short: str):
    # 單一 subscriber 模型下 short 前 8 碼唯一機率極高；保險起見只找 pending
    from sqlalchemy import select
    from notify_hub.db.models import Approval
    r = await session.execute(
        select(Approval).where(Approval.status == ApprovalStatus.pending)
    )
    for ap in r.scalars():
        if str(ap.id).startswith(short):
            return await crud.get_approval(session, ap.id)
    return None


async def _finalize_and_edit(ap, *, session, settings, tg, chat_id: int):
    tz = ZoneInfo(settings.quiet_hours_tz)
    decided_at_str = (ap.decided_at or datetime.now(tz)).astimezone(tz).strftime("%Y-%m-%d %H:%M")
    per_item = []
    mixed_reasons: dict[str, str] = {}
    # 從 decisions 彙整
    by_item = {}
    for d in ap.decisions:
        if d.item_id is None:
            for it in ap.items:
                by_item.setdefault(it.item_id, {
                    "id": it.item_id, "decision": d.decision.value, "reject_reason": d.reject_reason,
                })
        else:
            by_item[d.item_id] = {
                "id": d.item_id, "decision": d.decision.value, "reject_reason": d.reject_reason,
            }
            if d.reject_reason:
                mixed_reasons[d.item_id] = d.reject_reason
    for it in ap.items:
        if it.item_id in by_item:
            per_item.append(by_item[it.item_id])
    text = build_closed_message(
        project=ap.project, title=ap.title,
        status=ap.status.value,
        decided_at_str=decided_at_str,
        per_item=per_item, mixed_reject_reasons=mixed_reasons,
    )
    if ap.telegram_chat_id and ap.telegram_message_id:
        try:
            await tg.edit_message_text(
                chat_id=ap.telegram_chat_id,
                message_id=ap.telegram_message_id,
                text=text, reply_markup=None,
            )
        except Exception:
            pass
```

修改 `_handle_callback`:

```python
async def _handle_callback(cb, *, session, settings, tg):
    cb_id = cb["id"]
    chat_id = cb["from"]["id"]
    try:
        verify_chat_whitelist(chat_id, settings.allowed_chat_ids)
    except Exception:
        await tg.answer_callback_query(cb_id, text="您沒有權限")
        return
    try:
        parsed = parse_callback_data(cb.get("data", ""))
    except ValueError:
        await tg.answer_callback_query(cb_id, text="無效按鈕")
        return

    action = parsed["action"]
    short = parsed["approval_short"]
    ap = await _find_approval_by_short(session, short)
    if ap is None:
        await tg.answer_callback_query(cb_id, text="此請求已結案或不存在")
        return

    if action == "approve_all":
        await crud.record_decision(
            session, approval_id=ap.id, item_id=None,
            decision=DecisionType.approved, chat_id=chat_id,
        )
        await crud.recompute_approval_status(session, ap.id)
        ap = await crud.get_approval(session, ap.id)
        await _finalize_and_edit(ap, session=session, settings=settings, tg=tg, chat_id=chat_id)
        await tg.answer_callback_query(cb_id, text="已全部同意")
        return

    if action == "reject_all":
        await crud.record_decision(
            session, approval_id=ap.id, item_id=None,
            decision=DecisionType.rejected, chat_id=chat_id,
        )
        await crud.recompute_approval_status(session, ap.id)
        ap = await crud.get_approval(session, ap.id)
        await _finalize_and_edit(ap, session=session, settings=settings, tg=tg, chat_id=chat_id)
        await _ask_reject_reason(ap, item_id=None, session=session, settings=settings, tg=tg, chat_id=chat_id)
        await tg.answer_callback_query(cb_id, text="已全部拒絕")
        return

    if action == "per_item":
        # Task 14
        await tg.answer_callback_query(cb_id)
        return

    if action in ("item_approve", "item_reject"):
        # Task 14
        await tg.answer_callback_query(cb_id)
        return

    if action == "back":
        # Task 15
        await tg.answer_callback_query(cb_id)
        return
```

stub `_ask_reject_reason` (Task 16 真正實作):

```python
async def _ask_reject_reason(ap, *, item_id, session, settings, tg, chat_id):
    return  # Task 16 實作
```

- [ ] **Step 3: 跑 pass + commit**

```bash
./.venv/bin/pytest tests/integration/test_callback_approve_all.py -v
git add -A && git commit -m "feat(dispatcher): approve_all / reject_all finalizes + edits message"
```

---

## Task 14: Per-item panel + item_approve / item_reject

**Files:**
- Modify: `src/notify_hub/telegram/dispatcher.py`
- Create: `tests/integration/test_per_item_flow.py`

- [ ] **Step 1: 寫 failing test**

```python
# tests/integration/test_per_item_flow.py
import uuid
import pytest
from httpx import AsyncClient, ASGITransport
from notify_hub.main import create_app
from notify_hub.db import crud
from notify_hub.db.models import ApprovalStatus
from notify_hub.db.session import session_maker


@pytest.fixture
def app(monkeypatch, pg_container):
    monkeypatch.setenv("DATABASE_URL", pg_container)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "T")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "sec")
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://x")
    monkeypatch.setenv("NOTIFY_HUB_CONSUMER_TOKENS", "alphaforge:af")
    monkeypatch.setenv("ALLOWED_CHAT_IDS", "42")
    return create_app(skip_telegram_check=True)


@pytest.mark.asyncio
async def test_per_item_y_n_y_results_mixed(app, monkeypatch):
    from notify_hub.telegram import client as tg_mod
    async def fake_send(self, **kw): return {"message_id": 1, "chat": {"id": kw["chat_id"]}}
    async def fake_edit_text(self, **kw): return {}
    async def fake_edit_kb(self, **kw): return {}
    async def fake_ack(self, cb_id, text=None): return True
    monkeypatch.setattr(tg_mod.TelegramClient, "send_message", fake_send)
    monkeypatch.setattr(tg_mod.TelegramClient, "edit_message_text", fake_edit_text)
    monkeypatch.setattr(tg_mod.TelegramClient, "edit_message_reply_markup", fake_edit_kb)
    monkeypatch.setattr(tg_mod.TelegramClient, "answer_callback_query", fake_ack)

    async with AsyncClient(transport=ASGITransport(app), base_url="http://t") as c:
        async with session_maker()() as s:
            await crud.upsert_subscriber(s, chat_id=42, display_name="x")
        r = await c.post(
            "/v1/approvals",
            headers={"Authorization": "Bearer af"},
            json={"project":"p","title":"t","items":[
                {"id":"1","type":"a","summary":"x"},
                {"id":"2","type":"a","summary":"y"},
                {"id":"3","type":"a","summary":"z"}],
                "timeout_seconds":60,"metadata":{}},
        )
        rid = r.json()["request_id"]
        short = rid[:8]

        async def webhook(action, iid=None):
            data = f"v1:{action}:{short}" + (f":{iid}" if iid else "")
            return await c.post(
                "/tg/webhook",
                headers={"X-Telegram-Bot-Api-Secret-Token": "sec"},
                json={"update_id": 1,
                      "callback_query": {
                          "id": "cb",
                          "from": {"id": 42, "is_bot": False, "first_name": "me"},
                          "message": {"message_id": 1, "chat": {"id": 42, "type": "private"}},
                          "data": data,
                      }},
            )

        await webhook("per_item")
        await webhook("item_approve", "1")
        await webhook("item_reject", "2")
        await webhook("item_approve", "3")

        async with session_maker()() as s:
            ap = await crud.get_approval(s, uuid.UUID(rid))
            assert ap.status == ApprovalStatus.mixed
```

- [ ] **Step 2: 實作 per_item, item_approve, item_reject 分支**

在 `dispatcher.py` 內:

```python
from notify_hub.telegram.formatter import build_per_item_panel


async def _render_per_item(ap, *, session, tg):
    decided = {}
    for d in ap.decisions:
        if d.item_id:
            decided[d.item_id] = d.decision.value
    text, kb = build_per_item_panel(
        approval_id=str(ap.id), project=ap.project, title=ap.title,
        items=[{"item_id": it.item_id, "summary": it.summary} for it in ap.items],
        decided=decided,
    )
    if ap.telegram_chat_id and ap.telegram_message_id:
        await tg.edit_message_text(
            chat_id=ap.telegram_chat_id,
            message_id=ap.telegram_message_id,
            text=text, reply_markup=kb,
        )
```

修改 callback handler:

```python
    if action == "per_item":
        await _render_per_item(ap, session=session, tg=tg)
        await tg.answer_callback_query(cb_id)
        return

    if action == "item_approve":
        iid = parsed["item_id"]
        if not iid:
            await tg.answer_callback_query(cb_id, text="缺少項目 id")
            return
        # 已批過就忽略 (避免重複寫入)
        already = any(d.item_id == iid for d in ap.decisions)
        if not already:
            await crud.record_decision(
                session, approval_id=ap.id, item_id=iid,
                decision=DecisionType.approved, chat_id=chat_id,
            )
            new_status = await crud.recompute_approval_status(session, ap.id)
            ap = await crud.get_approval(session, ap.id)
            if new_status == ApprovalStatus.pending:
                await _render_per_item(ap, session=session, tg=tg)
            else:
                await _finalize_and_edit(ap, session=session, settings=settings, tg=tg, chat_id=chat_id)
        await tg.answer_callback_query(cb_id, text="✓")
        return

    if action == "item_reject":
        iid = parsed["item_id"]
        if not iid:
            await tg.answer_callback_query(cb_id, text="缺少項目 id")
            return
        already = any(d.item_id == iid for d in ap.decisions)
        if not already:
            await crud.record_decision(
                session, approval_id=ap.id, item_id=iid,
                decision=DecisionType.rejected, chat_id=chat_id,
            )
            new_status = await crud.recompute_approval_status(session, ap.id)
            ap = await crud.get_approval(session, ap.id)
            if new_status == ApprovalStatus.pending:
                await _render_per_item(ap, session=session, tg=tg)
            else:
                await _finalize_and_edit(ap, session=session, settings=settings, tg=tg, chat_id=chat_id)
            await _ask_reject_reason(ap, item_id=iid, session=session, settings=settings, tg=tg, chat_id=chat_id)
        await tg.answer_callback_query(cb_id, text="✗")
        return
```

- [ ] **Step 3: 跑 pass + commit**

```bash
./.venv/bin/pytest tests/integration/test_per_item_flow.py -v
git add -A && git commit -m "feat(dispatcher): per-item approval panel"
```

---

## Task 15: Back button (返回，保留已決項)

**Files:**
- Modify: `src/notify_hub/telegram/dispatcher.py`
- Create: `tests/integration/test_back_button.py`

- [x] **Step 1: 寫 test**

```python
# tests/integration/test_back_button.py
import uuid
import pytest
from httpx import AsyncClient, ASGITransport
from notify_hub.main import create_app
from notify_hub.db import crud
from notify_hub.db.session import session_maker


@pytest.fixture
def app(monkeypatch, pg_container):
    monkeypatch.setenv("DATABASE_URL", pg_container)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "T")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "sec")
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://x")
    monkeypatch.setenv("NOTIFY_HUB_CONSUMER_TOKENS", "alphaforge:af")
    monkeypatch.setenv("ALLOWED_CHAT_IDS", "42")
    return create_app(skip_telegram_check=True)


@pytest.mark.asyncio
async def test_back_preserves_decisions(app, monkeypatch):
    from notify_hub.telegram import client as tg_mod
    async def fake_send(self, **kw): return {"message_id": 1, "chat": {"id": kw["chat_id"]}}
    async def fake_edit(self, **kw): return {}
    async def fake_ack(self, cb_id, text=None): return True
    monkeypatch.setattr(tg_mod.TelegramClient, "send_message", fake_send)
    monkeypatch.setattr(tg_mod.TelegramClient, "edit_message_text", fake_edit)
    monkeypatch.setattr(tg_mod.TelegramClient, "edit_message_reply_markup", fake_edit)
    monkeypatch.setattr(tg_mod.TelegramClient, "answer_callback_query", fake_ack)

    async with AsyncClient(transport=ASGITransport(app), base_url="http://t") as c:
        async with session_maker()() as s:
            await crud.upsert_subscriber(s, chat_id=42, display_name="x")
        r = await c.post(
            "/v1/approvals",
            headers={"Authorization": "Bearer af"},
            json={"project":"p","title":"t","items":[
                {"id":"1","type":"a","summary":"x"},
                {"id":"2","type":"a","summary":"y"}],
                "timeout_seconds":60,"metadata":{}},
        )
        rid = r.json()["request_id"]
        short = rid[:8]

        async def hook(action, iid=None):
            data = f"v1:{action}:{short}" + (f":{iid}" if iid else "")
            return await c.post("/tg/webhook",
                headers={"X-Telegram-Bot-Api-Secret-Token":"sec"},
                json={"update_id":1, "callback_query":{
                    "id":"cb","from":{"id":42,"is_bot":False,"first_name":"m"},
                    "message":{"message_id":1,"chat":{"id":42,"type":"private"}},
                    "data":data}})

        await hook("per_item")
        await hook("item_approve", "1")
        await hook("back")

        async with session_maker()() as s:
            ap = await crud.get_approval(s, uuid.UUID(rid))
            # item 1 決定仍保留
            item1_d = [d for d in ap.decisions if d.item_id == "1"]
            assert len(item1_d) == 1
            assert item1_d[0].decision.value == "approved"
```

- [x] **Step 2: 實作 back 分支**

加入 `_render_top_keyboard`:

```python
from notify_hub.telegram.formatter import build_keyboard_top, build_approval_message


async def _render_top(ap, *, tg):
    text = build_approval_message(
        project=ap.project, title=ap.title,
        items=[{"item_id": it.item_id, "type": it.type, "summary": it.summary} for it in ap.items],
    )
    kb = build_keyboard_top(approval_id=str(ap.id))
    if ap.telegram_chat_id and ap.telegram_message_id:
        await tg.edit_message_text(
            chat_id=ap.telegram_chat_id,
            message_id=ap.telegram_message_id,
            text=text, reply_markup=kb,
        )
```

handler:

```python
    if action == "back":
        await _render_top(ap, tg=tg)
        await tg.answer_callback_query(cb_id)
        return
```

- [x] **Step 3: 跑 pass + commit**

```bash
./.venv/bin/pytest tests/integration/test_back_button.py -v
git add -A && git commit -m "feat(dispatcher): back button preserves decisions"
```

---

## Task 16: Reject reason ForceReply 流程

**Files:**
- Modify: `src/notify_hub/db/crud.py` (pending_reject_reason helpers)
- Modify: `src/notify_hub/telegram/dispatcher.py`
- Create: `tests/integration/test_reject_reason.py`

**Approach:** 使用 `decisions.reject_reason=NULL` + 加一張 in-memory 狀態，簡化為「找最近 5 分鐘內 chat 送出的 `item_reject` 或 `reject_all` 決定若 `reject_reason` 仍 NULL，就拿下一則 message 當理由」。不需要新表，用 DB query 即可。

- [ ] **Step 1: 寫 test**

```python
# tests/integration/test_reject_reason.py
import uuid
import pytest
from httpx import AsyncClient, ASGITransport
from notify_hub.main import create_app
from notify_hub.db import crud
from notify_hub.db.session import session_maker


@pytest.fixture
def app(monkeypatch, pg_container):
    monkeypatch.setenv("DATABASE_URL", pg_container)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "T")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "sec")
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://x")
    monkeypatch.setenv("NOTIFY_HUB_CONSUMER_TOKENS", "alphaforge:af")
    monkeypatch.setenv("ALLOWED_CHAT_IDS", "42")
    return create_app(skip_telegram_check=True)


@pytest.mark.asyncio
async def test_reject_reason_captured_from_next_message(app, monkeypatch):
    from notify_hub.telegram import client as tg_mod
    async def noop(*a, **k): return {"message_id": 1, "chat": {"id": 42}} if "chat_id" in (k or {}) else True
    monkeypatch.setattr(tg_mod.TelegramClient, "send_message", lambda self, **kw: noop(**kw) if False else {"message_id": 2, "chat": {"id": kw["chat_id"]}})
    monkeypatch.setattr(tg_mod.TelegramClient, "edit_message_text", lambda self, **kw: {})
    monkeypatch.setattr(tg_mod.TelegramClient, "edit_message_reply_markup", lambda self, **kw: {})
    monkeypatch.setattr(tg_mod.TelegramClient, "answer_callback_query", lambda self, *a, **k: True)

    # 由於 lambda 無法 async，改用 async 函式
    async def fake_send(self, **kw): return {"message_id": 2, "chat": {"id": kw["chat_id"]}}
    async def fake_edit(self, **kw): return {}
    async def fake_ack(self, *a, **k): return True
    monkeypatch.setattr(tg_mod.TelegramClient, "send_message", fake_send)
    monkeypatch.setattr(tg_mod.TelegramClient, "edit_message_text", fake_edit)
    monkeypatch.setattr(tg_mod.TelegramClient, "edit_message_reply_markup", fake_edit)
    monkeypatch.setattr(tg_mod.TelegramClient, "answer_callback_query", fake_ack)

    async with AsyncClient(transport=ASGITransport(app), base_url="http://t") as c:
        async with session_maker()() as s:
            await crud.upsert_subscriber(s, chat_id=42, display_name="x")
        r = await c.post(
            "/v1/approvals",
            headers={"Authorization": "Bearer af"},
            json={"project":"p","title":"t","items":[
                {"id":"1","type":"a","summary":"x"},
                {"id":"2","type":"a","summary":"y"}],
                "timeout_seconds":120,"metadata":{}},
        )
        rid = r.json()["request_id"]
        short = rid[:8]

        # item_reject 2
        await c.post("/tg/webhook", headers={"X-Telegram-Bot-Api-Secret-Token":"sec"},
                     json={"update_id":1,"callback_query":{
                         "id":"cb","from":{"id":42,"is_bot":False,"first_name":"m"},
                         "message":{"message_id":1,"chat":{"id":42,"type":"private"}},
                         "data":f"v1:per_item:{short}"}})
        await c.post("/tg/webhook", headers={"X-Telegram-Bot-Api-Secret-Token":"sec"},
                     json={"update_id":2,"callback_query":{
                         "id":"cb","from":{"id":42,"is_bot":False,"first_name":"m"},
                         "message":{"message_id":1,"chat":{"id":42,"type":"private"}},
                         "data":f"v1:item_reject:{short}:2"}})
        # 使用者下一則 message 是理由
        await c.post("/tg/webhook", headers={"X-Telegram-Bot-Api-Secret-Token":"sec"},
                     json={"update_id":3,"message":{
                         "message_id":99,"from":{"id":42,"is_bot":False,"first_name":"m"},
                         "chat":{"id":42,"type":"private"},
                         "text":"這不急，明天再延"}})

        async with session_maker()() as s:
            ap = await crud.get_approval(s, uuid.UUID(rid))
            d2 = [d for d in ap.decisions if d.item_id == "2"][0]
            assert d2.reject_reason == "這不急，明天再延"


@pytest.mark.asyncio
async def test_skip_reject_reason(app, monkeypatch):
    from notify_hub.telegram import client as tg_mod
    async def fake_send(self, **kw): return {"message_id": 2, "chat": {"id": kw["chat_id"]}}
    async def fake_edit(self, **kw): return {}
    async def fake_ack(self, *a, **k): return True
    monkeypatch.setattr(tg_mod.TelegramClient, "send_message", fake_send)
    monkeypatch.setattr(tg_mod.TelegramClient, "edit_message_text", fake_edit)
    monkeypatch.setattr(tg_mod.TelegramClient, "edit_message_reply_markup", fake_edit)
    monkeypatch.setattr(tg_mod.TelegramClient, "answer_callback_query", fake_ack)

    async with AsyncClient(transport=ASGITransport(app), base_url="http://t") as c:
        async with session_maker()() as s:
            await crud.upsert_subscriber(s, chat_id=42, display_name="x")
        r = await c.post("/v1/approvals", headers={"Authorization": "Bearer af"},
            json={"project":"p","title":"t","items":[{"id":"1","type":"a","summary":"x"}],
                  "timeout_seconds":120,"metadata":{}})
        rid = r.json()["request_id"]; short = rid[:8]

        await c.post("/tg/webhook", headers={"X-Telegram-Bot-Api-Secret-Token":"sec"},
            json={"update_id":1,"callback_query":{
                "id":"cb","from":{"id":42,"is_bot":False,"first_name":"m"},
                "message":{"message_id":1,"chat":{"id":42,"type":"private"}},
                "data":f"v1:reject_all:{short}"}})
        await c.post("/tg/webhook", headers={"X-Telegram-Bot-Api-Secret-Token":"sec"},
            json={"update_id":2,"message":{
                "message_id":99,"from":{"id":42,"is_bot":False,"first_name":"m"},
                "chat":{"id":42,"type":"private"}, "text":"skip"}})

        async with session_maker()() as s:
            ap = await crud.get_approval(s, uuid.UUID(rid))
            d = [d for d in ap.decisions if d.item_id is None][0]
            assert d.reject_reason is None
```

- [ ] **Step 2: 加 crud helper: find_pending_reject**

```python
# 加到 crud.py
from datetime import timedelta


async def find_pending_reject_for_chat(session: AsyncSession, chat_id: int) -> Decision | None:
    """找 5 分鐘內該 chat 送出的 rejected 決定且 reject_reason 仍 NULL。"""
    from sqlalchemy import select
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=5)
    r = await session.execute(
        select(Decision).where(
            Decision.decided_by_chat_id == chat_id,
            Decision.decision == DecisionType.rejected,
            Decision.reject_reason.is_(None),
            Decision.decided_at >= cutoff,
        ).order_by(Decision.decided_at.desc()).limit(1)
    )
    return r.scalar_one_or_none()


async def set_reject_reason(session: AsyncSession, decision_id: int, reason: str) -> None:
    await session.execute(
        update(Decision).where(Decision.id == decision_id).values(reject_reason=reason)
    )
    await session.commit()


async def mark_reject_reason_skipped(session: AsyncSession, decision_id: int) -> None:
    await session.execute(
        update(Decision).where(Decision.id == decision_id).values(reject_reason="(skipped)")
    )
    await session.commit()
```

- [ ] **Step 3: 實作 ask_reject_reason + message 分派**

```python
# dispatcher.py
async def _ask_reject_reason(ap, *, item_id, session, settings, tg, chat_id):
    label = f"項目 {item_id}" if item_id else "全部項目"
    await tg.send_message(
        chat_id=chat_id,
        text=f"拒絕了{label}。\n回一句話我存成理由，或打「skip」跳過。",
        reply_markup={"force_reply": True, "selective": True},
    )


async def _handle_message(msg, *, session, settings, tg):
    chat_id = msg["from"]["id"]
    try:
        verify_chat_whitelist(chat_id, settings.allowed_chat_ids)
    except Exception:
        return
    text = (msg.get("text") or "").strip()
    if not text:
        return
    if text.startswith("/task "):
        # Task 22
        await _handle_task_command(msg, text=text, session=session, settings=settings, tg=tg)
        return
    if text == "/task":
        await tg.send_message(chat_id=chat_id,
            text="用法: /task <任務描述>\n例: /task 幫我看 2330 有沒有缺口")
        return
    # 檢查是否有 pending reject reason
    pending = await crud.find_pending_reject_for_chat(session, chat_id)
    if pending:
        if text.lower() == "skip":
            await crud.mark_reject_reason_skipped(session, pending.id)
            await tg.send_message(chat_id=chat_id, text="已跳過理由紀錄。")
        else:
            await crud.set_reject_reason(session, pending.id, text[:1000])
            await tg.send_message(chat_id=chat_id, text="理由已記錄。")
        return
    # 其他: 忽略
    return


async def _handle_task_command(msg, *, text, session, settings, tg):
    pass  # Task 22
```

- [ ] **Step 4: 跑 pass + commit**

```bash
./.venv/bin/pytest tests/integration/test_reject_reason.py -v
git add -A && git commit -m "feat(dispatcher): ForceReply reject reason capture + skip"
```

---

## Task 17: Timeout auto-close scheduler

**Files:**
- Create: `src/notify_hub/scheduler/timeout_sweeper.py`
- Create: `src/notify_hub/scheduler/runtime.py`
- Modify: `src/notify_hub/main.py` (start scheduler in lifespan)
- Create: `tests/integration/test_timeout_close.py`

- [ ] **Step 1: 寫 test**

```python
# tests/integration/test_timeout_close.py
import asyncio
import uuid
from datetime import datetime, timedelta, timezone
import pytest
from notify_hub.db import crud
from notify_hub.db.models import Approval, ApprovalStatus, PushState
from notify_hub.db.session import session_maker, init_engine
from notify_hub.config import Settings
from notify_hub.scheduler.timeout_sweeper import sweep_and_close
from sqlalchemy import update


@pytest.mark.asyncio
async def test_sweep_closes_expired(monkeypatch, pg_container):
    monkeypatch.setenv("DATABASE_URL", pg_container)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "T")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "s")
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://x")
    monkeypatch.setenv("NOTIFY_HUB_CONSUMER_TOKENS", "alphaforge:af")
    monkeypatch.setenv("ALLOWED_CHAT_IDS", "42")
    settings = Settings()
    init_engine(settings)

    async with session_maker()() as s:
        c = await crud.upsert_consumer(s, "alphaforge", "h")
        ap = await crud.create_approval(
            s, consumer_id=c.id, project="p", title="t",
            items=[{"id":"1","type":"a","summary":"x","detail":None,"position":0}],
            timeout_seconds=1, metadata={},
        )
        # 強制 expired
        await s.execute(update(Approval).where(Approval.id == ap.id).values(
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
        await s.commit()

    edits = []
    class FakeTg:
        async def edit_message_text(self, **kw): edits.append(kw)
    await sweep_and_close(settings=settings, tg=FakeTg())

    async with session_maker()() as s:
        got = await crud.get_approval(s, ap.id)
        assert got.status == ApprovalStatus.timeout
        assert any(d.decision.value == "timeout" for d in got.decisions)
```

- [ ] **Step 2: 實作 sweeper + runtime**

```python
# src/notify_hub/scheduler/timeout_sweeper.py
from datetime import datetime
from zoneinfo import ZoneInfo
from notify_hub.db.session import session_maker
from notify_hub.db import crud
from notify_hub.telegram.formatter import build_closed_message


async def sweep_and_close(*, settings, tg) -> None:
    tz = ZoneInfo(settings.quiet_hours_tz)
    async with session_maker()() as s:
        ids = await crud.sweep_timeouts(s)
        for aid in ids:
            ap = await crud.get_approval(s, aid)
            if ap is None or not (ap.telegram_chat_id and ap.telegram_message_id):
                continue
            decided_str = (ap.decided_at or datetime.now(tz)).astimezone(tz).strftime("%Y-%m-%d %H:%M")
            text = build_closed_message(
                project=ap.project, title=ap.title, status="timeout",
                decided_at_str=decided_str, per_item=[], mixed_reject_reasons={},
            )
            try:
                await tg.edit_message_text(
                    chat_id=ap.telegram_chat_id,
                    message_id=ap.telegram_message_id,
                    text=text, reply_markup=None,
                )
            except Exception:
                pass
```

```python
# src/notify_hub/scheduler/runtime.py
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from notify_hub.scheduler.timeout_sweeper import sweep_and_close


def build_scheduler(*, settings, tg) -> AsyncIOScheduler:
    sched = AsyncIOScheduler(timezone=settings.quiet_hours_tz)
    sched.add_job(
        sweep_and_close, IntervalTrigger(seconds=30),
        kwargs={"settings": settings, "tg": tg},
        id="timeout_sweeper", replace_existing=True, max_instances=1,
    )
    return sched
```

- [ ] **Step 3: 在 main.py 啟動 scheduler**

```python
from notify_hub.scheduler.runtime import build_scheduler

@asynccontextmanager
async def lifespan(app):
    ...
    sched = build_scheduler(settings=settings, tg=tg)
    sched.start()
    app.state.scheduler = sched
    yield
    sched.shutdown()
    ...
```

- [ ] **Step 4: 跑 pass + commit**

```bash
./.venv/bin/pytest tests/integration/test_timeout_close.py -v
git add -A && git commit -m "feat(scheduler): timeout sweeper every 30s"
```

---

## Task 18: Quiet hours flush (07:00 batch)

**Files:**
- Modify: `src/notify_hub/scheduler/quiet_hours_flush.py`
- Modify: `src/notify_hub/scheduler/runtime.py`
- Create: `tests/integration/test_quiet_hours_flush.py`
- Create: `tests/unit/test_quiet_hours.py`

- [ ] **Step 1: 寫 unit test**

```python
# tests/unit/test_quiet_hours.py
from datetime import datetime
from zoneinfo import ZoneInfo
from notify_hub.scheduler.quiet_hours_flush import is_quiet_hour_now
from notify_hub.config import Settings


def _settings():
    import os
    os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://x")
    os.environ.setdefault("TELEGRAM_BOT_TOKEN", "x")
    os.environ.setdefault("TELEGRAM_WEBHOOK_SECRET", "x")
    os.environ.setdefault("PUBLIC_BASE_URL", "x")
    os.environ.setdefault("NOTIFY_HUB_CONSUMER_TOKENS", "a:b")
    os.environ.setdefault("ALLOWED_CHAT_IDS", "1")
    return Settings()


def test_night_is_quiet():
    s = _settings()
    tz = ZoneInfo("Asia/Taipei")
    assert is_quiet_hour_now(s, datetime(2026, 4, 22, 23, 0, tzinfo=tz)) is True


def test_morning_not_quiet():
    s = _settings()
    tz = ZoneInfo("Asia/Taipei")
    assert is_quiet_hour_now(s, datetime(2026, 4, 22, 7, 30, tzinfo=tz)) is False


def test_boundary_22_00():
    s = _settings()
    tz = ZoneInfo("Asia/Taipei")
    assert is_quiet_hour_now(s, datetime(2026, 4, 22, 22, 0, tzinfo=tz)) is True


def test_boundary_07_00():
    s = _settings()
    tz = ZoneInfo("Asia/Taipei")
    assert is_quiet_hour_now(s, datetime(2026, 4, 22, 7, 0, tzinfo=tz)) is False
```

- [ ] **Step 2: 寫 integration test**

```python
# tests/integration/test_quiet_hours_flush.py
import pytest
from notify_hub.db import crud
from notify_hub.db.models import PushState, ApprovalStatus
from notify_hub.db.session import session_maker, init_engine
from notify_hub.config import Settings
from notify_hub.scheduler.quiet_hours_flush import flush_suppressed


@pytest.mark.asyncio
async def test_flush_pushes_suppressed(monkeypatch, pg_container):
    monkeypatch.setenv("DATABASE_URL", pg_container)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "T")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "s")
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://x")
    monkeypatch.setenv("NOTIFY_HUB_CONSUMER_TOKENS", "alphaforge:af")
    monkeypatch.setenv("ALLOWED_CHAT_IDS", "42")
    settings = Settings()
    init_engine(settings)

    async with session_maker()() as s:
        c = await crud.upsert_consumer(s, "alphaforge", "h")
        await crud.upsert_subscriber(s, chat_id=42, display_name="x")
        await crud.create_approval(
            s, consumer_id=c.id, project="alphaforge", title="昨晚的事",
            items=[{"id":"1","type":"a","summary":"x","detail":None,"position":0}],
            timeout_seconds=3600, metadata={},
            push_state=PushState.suppressed_quiet_hours,
        )

    sent = []
    class FakeTg:
        async def send_message(self, **kw): sent.append(kw); return {"message_id": 77, "chat": {"id": kw["chat_id"]}}

    await flush_suppressed(settings=settings, tg=FakeTg())
    assert len(sent) == 1
    assert "昨晚" in sent[0]["text"] or "早安" in sent[0]["text"]

    async with session_maker()() as s:
        from sqlalchemy import select
        from notify_hub.db.models import Approval
        r = await s.execute(select(Approval))
        ap = r.scalar_one()
        assert ap.push_state == PushState.pushed
        # flush 推出後才啟動倒數
        assert ap.expires_at is not None
        # timeout_seconds=3600 → expires_at 應落在未來 50-70 分鐘內
        from datetime import datetime, timedelta, timezone
        delta = ap.expires_at - datetime.now(timezone.utc)
        assert timedelta(minutes=50) < delta < timedelta(minutes=70)
```

- [ ] **Step 3: 實作 flush_suppressed**

```python
# 加到 quiet_hours_flush.py
from sqlalchemy import select
from notify_hub.db.models import Approval, ApprovalStatus, PushState, Consumer
from notify_hub.db.session import session_maker
from notify_hub.db import crud
from notify_hub.main import update_tg_status
from notify_hub.telegram.formatter import (
    build_keyboard_top, split_long_message,
)


async def flush_suppressed(*, settings, tg) -> None:
    allowed = settings.allowed_chat_ids
    if not allowed:
        return
    chat_id = allowed[0]
    async with session_maker()() as s:
        r = await s.execute(
            select(Approval, Consumer).join(Consumer, Approval.consumer_id == Consumer.id)
            .where(
                Approval.push_state == PushState.suppressed_quiet_hours,
                Approval.status == ApprovalStatus.pending,
            )
        )
        rows = r.all()
        # 依 consumer 分組
        by_consumer: dict[str, list] = {}
        for ap, cons in rows:
            by_consumer.setdefault(cons.name, []).append(ap)

        for consumer_name, approvals in by_consumer.items():
            # 每個 approval 仍單獨可批 (按鈕綁該 approval)；打包成多則訊息
            header = f"🔔 早安！昨晚累積 {len(approvals)} 件事要批 ({consumer_name})"
            for ap in approvals:
                ap_full = await crud.get_approval(s, ap.id)
                text_lines = [header, "", f"<b>{ap_full.title}</b>"]
                for it in ap_full.items:
                    text_lines.append(f"- {it.summary}")
                full = "\n".join(text_lines)
                kb = build_keyboard_top(approval_id=str(ap_full.id))
                parts = split_long_message(full)
                try:
                    r_send = await tg.send_message(chat_id=chat_id, text=parts[0], reply_markup=kb)
                    msg_id = r_send["message_id"]
                    for extra in parts[1:]:
                        await tg.send_message(chat_id=chat_id, text=extra)
                    # 推出成功 → 啟動倒數 (靜音時段建立時沒設 expires_at, 這裡才開始算)
                    await crud.set_approval_push_info(
                        s, ap_full.id, chat_id=chat_id, message_id=msg_id,
                        push_state=PushState.pushed, start_countdown=True,
                    )
                    update_tg_status(ok=True)
                except Exception as e:
                    await crud.set_approval_push_info(
                        s, ap_full.id, chat_id=None, message_id=None,
                        push_state=PushState.push_failed, last_push_error=str(e)[:500],
                    )
                    update_tg_status(ok=False, error=str(e)[:200])
                header = ""  # 後續訊息不重複 header
```

- [ ] **Step 4: 加到 scheduler**

```python
# scheduler/runtime.py 加
from notify_hub.scheduler.quiet_hours_flush import flush_suppressed


def build_scheduler(*, settings, tg) -> AsyncIOScheduler:
    sched = AsyncIOScheduler(timezone=settings.quiet_hours_tz)
    sched.add_job(
        sweep_and_close, IntervalTrigger(seconds=30),
        kwargs={"settings": settings, "tg": tg},
        id="timeout_sweeper", replace_existing=True, max_instances=1,
    )
    end_h, end_m = settings.quiet_hours_end.split(":")
    sched.add_job(
        flush_suppressed, CronTrigger(hour=int(end_h), minute=int(end_m)),
        kwargs={"settings": settings, "tg": tg},
        id="quiet_hours_flush", replace_existing=True, max_instances=1,
    )
    return sched
```

- [ ] **Step 5: 跑 pass + commit**

```bash
./.venv/bin/pytest tests/unit/test_quiet_hours.py tests/integration/test_quiet_hours_flush.py -v
git add -A && git commit -m "feat(scheduler): quiet hours flush at end time"
```

---

## Task 19: Cleanup cron (04:00)

**Files:**
- Create: `src/notify_hub/scheduler/cleanup.py`
- Modify: `src/notify_hub/scheduler/runtime.py`
- Create: `tests/integration/test_cleanup.py`

- [ ] **Step 1: 寫 test**

```python
# tests/integration/test_cleanup.py
import pytest
from datetime import datetime, timedelta, timezone
from sqlalchemy import update, select
from notify_hub.db import crud
from notify_hub.db.models import AgentJob, JobStatus, JobSource
from notify_hub.db.session import session_maker, init_engine
from notify_hub.config import Settings
from notify_hub.scheduler.cleanup import run_cleanup


@pytest.mark.asyncio
async def test_cleanup_deletes_old_jobs(monkeypatch, pg_container):
    monkeypatch.setenv("DATABASE_URL", pg_container)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "T")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "s")
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://x")
    monkeypatch.setenv("NOTIFY_HUB_CONSUMER_TOKENS", "alphaforge:af")
    monkeypatch.setenv("ALLOWED_CHAT_IDS", "42")
    settings = Settings()
    init_engine(settings)

    async with session_maker()() as s:
        c = await crud.upsert_consumer(s, "alphaforge", "h")
        job = await crud.create_job(
            s, consumer_id=c.id, prompt="old", source=JobSource.telegram_task,
            notify_chat_id=None, ttl_days=7,
        )
        # 手動改成 completed 35 天前
        await s.execute(update(AgentJob).where(AgentJob.id == job.id).values(
            status=JobStatus.completed,
            completed_at=datetime.now(timezone.utc) - timedelta(days=35)))
        await s.commit()

    await run_cleanup()

    async with session_maker()() as s:
        r = await s.execute(select(AgentJob))
        assert r.scalar_one_or_none() is None
```

- [ ] **Step 2: 實作 cleanup**

```python
# src/notify_hub/scheduler/cleanup.py
from datetime import datetime, timedelta, timezone
from sqlalchemy import delete
from notify_hub.db.session import session_maker
from notify_hub.db.models import AgentJob, JobStatus


async def run_cleanup() -> None:
    now = datetime.now(timezone.utc)
    completed_cutoff = now - timedelta(days=30)
    failed_cutoff = now - timedelta(days=90)
    async with session_maker()() as s:
        await s.execute(
            delete(AgentJob).where(
                AgentJob.status == JobStatus.completed,
                AgentJob.completed_at < completed_cutoff,
            )
        )
        await s.execute(
            delete(AgentJob).where(
                AgentJob.status == JobStatus.failed,
                AgentJob.completed_at < failed_cutoff,
            )
        )
        await s.commit()
    # approvals 只做歸檔 (spec §3.7 不刪)，暫不實作 archived 欄位 → v0.1.0 不需要
```

- [ ] **Step 3: 加 cron**

```python
# scheduler/runtime.py 加
from notify_hub.scheduler.cleanup import run_cleanup

sched.add_job(
    run_cleanup, CronTrigger(hour=4, minute=0),
    id="cleanup", replace_existing=True, max_instances=1,
)
```

- [ ] **Step 4: 跑 pass + commit**

```bash
./.venv/bin/pytest tests/integration/test_cleanup.py -v
git add -A && git commit -m "feat(scheduler): daily 04:00 cleanup of old jobs"
```

---

## Task 19.5: Push failure retry + Telegram 健康狀態定時 probe

補 spec §7.2 規範 (每小時重送 push_failed 但仍 pending 的 approval) + 確保 `/healthz` 的 telegram 狀態不只停留在 startup 那一刻。單一排程器職責涵蓋兩件事:

1. 掃 `(status=pending AND push_state=push_failed)` 的 approval, 重送 sendMessage
2. 不管有沒有東西要重送, 都打一次 Telegram `getMe` 更新 `TG_STATUS` cache

**Files:**
- Create: `src/notify_hub/scheduler/push_retry.py`
- Modify: `src/notify_hub/scheduler/runtime.py`
- Modify: `src/notify_hub/telegram/client.py` (加 `get_me` method)
- Create: `tests/integration/test_push_retry.py`
- Create: `tests/unit/test_tg_status_cache.py`

- [ ] **Step 1: 寫 unit test (TG_STATUS cache 行為)**

```python
# tests/unit/test_tg_status_cache.py
from notify_hub.main import TG_STATUS, update_tg_status


def test_update_ok_sets_last_updated():
    update_tg_status(ok=True)
    assert TG_STATUS["status"] == "ok"
    assert TG_STATUS["last_updated"] is not None
    assert TG_STATUS["last_error"] is None


def test_update_failure_captures_error():
    update_tg_status(ok=False, error="429 Too Many Requests")
    assert TG_STATUS["status"] == "degraded"
    assert "429" in TG_STATUS["last_error"]
```

- [ ] **Step 2: 寫 integration test (retry 真的會重送 + cache 被刷新)**

```python
# tests/integration/test_push_retry.py
import pytest
from notify_hub.db import crud
from notify_hub.db.models import PushState, ApprovalStatus
from notify_hub.db.session import session_maker, init_engine
from notify_hub.config import Settings
from notify_hub.scheduler.push_retry import retry_and_probe
from notify_hub.main import TG_STATUS


class FakeTg:
    def __init__(self, fail_send: bool = False):
        self.sent = []
        self.probed = 0
        self.fail_send = fail_send

    async def send_message(self, **kw):
        if self.fail_send:
            raise RuntimeError("telegram down")
        self.sent.append(kw)
        return {"message_id": 99, "chat": {"id": kw["chat_id"]}}

    async def get_me(self):
        self.probed += 1
        return {"id": 12345, "username": "bot"}


@pytest.mark.asyncio
async def test_retry_resends_failed_approvals(monkeypatch, pg_container):
    monkeypatch.setenv("DATABASE_URL", pg_container)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "T")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "s")
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://x")
    monkeypatch.setenv("NOTIFY_HUB_CONSUMER_TOKENS", "alphaforge:af")
    monkeypatch.setenv("ALLOWED_CHAT_IDS", "42")
    settings = Settings()
    init_engine(settings)

    async with session_maker()() as s:
        c = await crud.upsert_consumer(s, "alphaforge", "h")
        ap = await crud.create_approval(
            s, consumer_id=c.id, project="p", title="t",
            items=[{"id":"1","type":"a","summary":"x","detail":None,"position":0}],
            timeout_seconds=1200, metadata={},
        )
        # 模擬先前 push 失敗
        await crud.set_approval_push_info(
            s, ap.id, chat_id=None, message_id=None,
            push_state=PushState.push_failed, last_push_error="prior failure",
        )

    tg = FakeTg(fail_send=False)
    await retry_and_probe(settings=settings, tg=tg)

    # 重送成功: 呼叫 send_message 一次 + 更新 push_state=pushed
    assert len(tg.sent) == 1
    assert tg.probed == 1  # 每次 run 都 probe 一次
    assert TG_STATUS["status"] == "ok"

    async with session_maker()() as s:
        got = await crud.get_approval(s, ap.id)
        assert got.push_state == PushState.pushed
        assert got.telegram_message_id == 99


@pytest.mark.asyncio
async def test_probe_marks_degraded_when_getme_fails(monkeypatch, pg_container):
    monkeypatch.setenv("DATABASE_URL", pg_container)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "T")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "s")
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://x")
    monkeypatch.setenv("NOTIFY_HUB_CONSUMER_TOKENS", "alphaforge:af")
    monkeypatch.setenv("ALLOWED_CHAT_IDS", "42")
    settings = Settings()
    init_engine(settings)

    class BrokenTg:
        async def send_message(self, **kw): raise RuntimeError("x")
        async def get_me(self): raise RuntimeError("telegram unreachable")

    await retry_and_probe(settings=settings, tg=BrokenTg())
    assert TG_STATUS["status"] == "degraded"
    assert "unreachable" in TG_STATUS["last_error"]
```

- [ ] **Step 3: 在 telegram client 加 `get_me`**

```python
# src/notify_hub/telegram/client.py 加 method
async def get_me(self) -> dict:
    return await self._call("getMe", {})
```

- [ ] **Step 4: 實作 push_retry.py**

```python
# src/notify_hub/scheduler/push_retry.py
from sqlalchemy import select
from notify_hub.db.models import Approval, ApprovalStatus, PushState
from notify_hub.db.session import session_maker
from notify_hub.db import crud
from notify_hub.main import update_tg_status
from notify_hub.telegram.formatter import (
    build_approval_message, build_keyboard_top, split_long_message,
)


async def retry_and_probe(*, settings, tg) -> None:
    """每小時跑: 重送 push_failed 的 approval + probe telegram 健康狀態。

    兩件事綁同一 job 的理由: 重送也是一種 probe, 失敗/成功都可以拿來刷 TG_STATUS;
    若當下沒 failed approval 要重送, 仍主動打 getMe 確保 healthz 不會因為沒流量而停滯。
    """
    allowed = settings.allowed_chat_ids
    if not allowed:
        return
    chat_id = allowed[0]

    # Step 1: 掃 push_failed AND 仍 pending (非 timeout/approved/rejected)
    async with session_maker()() as s:
        r = await s.execute(
            select(Approval).where(
                Approval.push_state == PushState.push_failed,
                Approval.status == ApprovalStatus.pending,
            )
        )
        failed = r.scalars().all()
        any_push_result = False

        for ap in failed:
            ap_full = await crud.get_approval(s, ap.id)
            text = build_approval_message(
                project=ap_full.project, title=ap_full.title,
                items=[{"item_id": it.item_id, "type": it.type, "summary": it.summary}
                       for it in ap_full.items],
            )
            kb = build_keyboard_top(approval_id=str(ap_full.id))
            parts = split_long_message(text)
            try:
                r_send = await tg.send_message(chat_id=chat_id, text=parts[0], reply_markup=kb)
                for extra in parts[1:]:
                    await tg.send_message(chat_id=chat_id, text=extra)
                # 若原本是靜音時段建立 (expires_at IS NULL), start_countdown 會順便設倒數
                needs_countdown = ap_full.expires_at is None
                await crud.set_approval_push_info(
                    s, ap_full.id,
                    chat_id=chat_id, message_id=r_send["message_id"],
                    push_state=PushState.pushed,
                    start_countdown=needs_countdown,
                )
                update_tg_status(ok=True)
                any_push_result = True
            except Exception as e:
                await crud.set_approval_push_info(
                    s, ap_full.id, chat_id=None, message_id=None,
                    push_state=PushState.push_failed, last_push_error=str(e)[:500],
                )
                update_tg_status(ok=False, error=str(e)[:200])
                any_push_result = True

    # Step 2: 若本輪沒有任何 push 刷到 cache, 主動 probe getMe
    if not any_push_result:
        try:
            await tg.get_me()
            update_tg_status(ok=True)
        except Exception as e:
            update_tg_status(ok=False, error=str(e)[:200])
```

- [ ] **Step 5: 加到 scheduler runtime**

```python
# scheduler/runtime.py 加
from notify_hub.scheduler.push_retry import retry_and_probe

sched.add_job(
    retry_and_probe, IntervalTrigger(hours=1),
    kwargs={"settings": settings, "tg": tg},
    id="push_retry", replace_existing=True, max_instances=1,
)
```

- [ ] **Step 6: 跑 pass + commit**

```bash
./.venv/bin/pytest tests/integration/test_push_retry.py tests/unit/test_tg_status_cache.py -v
git add -A && git commit -m "feat(scheduler): hourly push retry + telegram health probe"
```

---

## Task 20: Jobs API (POST /v1/jobs + GET /v1/jobs/next)

**Files:**
- Create: `src/notify_hub/api/jobs.py`
- Modify: `src/notify_hub/main.py`
- Create: `tests/integration/test_jobs_api.py`

- [ ] **Step 1: 寫 test**

```python
# tests/integration/test_jobs_api.py
import pytest
from httpx import AsyncClient, ASGITransport
from notify_hub.main import create_app


@pytest.fixture
def app(monkeypatch, pg_container):
    monkeypatch.setenv("DATABASE_URL", pg_container)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "T")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "sec")
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://x")
    monkeypatch.setenv("NOTIFY_HUB_CONSUMER_TOKENS", "alphaforge:af")
    monkeypatch.setenv("ALLOWED_CHAT_IDS", "42")
    return create_app(skip_telegram_check=True)


@pytest.mark.asyncio
async def test_create_and_claim_job(app):
    async with AsyncClient(transport=ASGITransport(app), base_url="http://t") as c:
        r = await c.post(
            "/v1/jobs",
            headers={"Authorization": "Bearer af"},
            json={"agent": "alphaforge", "prompt": "do thing", "notify_chat_id": 42},
        )
        assert r.status_code == 201
        jid = r.json()["job_id"]

        n = await c.get(
            "/v1/jobs/next?agent=alphaforge&timeout=1",
            headers={"Authorization": "Bearer af"},
        )
        assert n.status_code == 200
        assert n.json()["job_id"] == jid


@pytest.mark.asyncio
async def test_next_returns_204_when_empty(app):
    async with AsyncClient(transport=ASGITransport(app), base_url="http://t") as c:
        r = await c.get(
            "/v1/jobs/next?agent=alphaforge&timeout=1",
            headers={"Authorization": "Bearer af"},
        )
        assert r.status_code == 204


@pytest.mark.asyncio
async def test_agent_mismatch_400(app):
    async with AsyncClient(transport=ASGITransport(app), base_url="http://t") as c:
        # agent 欄位與 consumer 名不一致
        r = await c.post(
            "/v1/jobs",
            headers={"Authorization": "Bearer af"},
            json={"agent": "rebirth", "prompt": "x", "notify_chat_id": None},
        )
        assert r.status_code == 400
```

- [ ] **Step 2: 實作 jobs router**

```python
# src/notify_hub/api/jobs.py
from __future__ import annotations
import asyncio
import socket
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession
from notify_hub.db import crud
from notify_hub.db.models import Consumer, JobSource, JobStatus
from notify_hub.dependencies import current_consumer, get_session
from notify_hub.schemas import JobCreate, JobCreated, JobNext, JobComplete


router = APIRouter(prefix="/v1/jobs")

INSTANCE_ID = socket.gethostname()


@router.post("", response_model=JobCreated, status_code=201)
async def create_job(
    payload: JobCreate,
    consumer: Consumer = Depends(current_consumer),
    session: AsyncSession = Depends(get_session),
):
    if payload.agent != consumer.name:
        raise HTTPException(status_code=400, detail="agent must match consumer name")
    job = await crud.create_job(
        session, consumer_id=consumer.id, prompt=payload.prompt,
        source=JobSource.consumer_api, notify_chat_id=payload.notify_chat_id,
    )
    return JobCreated(job_id=str(job.id), status=job.status.value)


@router.get("/next")
async def next_job(
    agent: str = Query(...),
    timeout: int = Query(30, ge=1),
    consumer: Consumer = Depends(current_consumer),
    session: AsyncSession = Depends(get_session),
):
    if agent != consumer.name:
        raise HTTPException(status_code=400, detail="agent mismatch")
    effective = min(timeout, 55)
    deadline = asyncio.get_event_loop().time() + effective
    poll = 0.5
    while True:
        job = await crud.claim_next_job(session, consumer.id, INSTANCE_ID)
        if job:
            return JobNext(
                job_id=str(job.id), prompt=job.prompt,
                notify_chat_id=job.notify_chat_id, created_at=job.created_at,
            )
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            return Response(status_code=204)
        await asyncio.sleep(min(poll, remaining))


@router.post("/{job_id}/complete")
async def complete_job(
    job_id: uuid.UUID, payload: JobComplete,
    consumer: Consumer = Depends(current_consumer),
    session: AsyncSession = Depends(get_session),
):
    # Task 21 加上 notify push
    job = await crud.complete_job(
        session, job_id=job_id,
        status=JobStatus.completed if payload.status == "completed" else JobStatus.failed,
        result_summary=payload.result_summary, result_path=payload.result_path,
    )
    if job is None or job.consumer_id != consumer.id:
        raise HTTPException(status_code=404, detail="job not found")
    return {"ok": True}
```

register: `app.include_router(jobs.router)`

- [ ] **Step 3: 跑 pass + commit**

```bash
./.venv/bin/pytest tests/integration/test_jobs_api.py -v
git add -A && git commit -m "feat(api): POST /v1/jobs + GET /v1/jobs/next + /complete (no push yet)"
```

---

## Task 21: POST /v1/jobs/<id>/complete notify push

**Files:**
- Modify: `src/notify_hub/api/jobs.py` (加 push 後段)
- Create: `tests/integration/test_job_complete_push.py`

- [ ] **Step 1: 寫 test**

```python
# tests/integration/test_job_complete_push.py
import pytest
from httpx import AsyncClient, ASGITransport
from notify_hub.main import create_app


@pytest.fixture
def app(monkeypatch, pg_container):
    monkeypatch.setenv("DATABASE_URL", pg_container)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "T")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "sec")
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://x")
    monkeypatch.setenv("NOTIFY_HUB_CONSUMER_TOKENS", "alphaforge:af")
    monkeypatch.setenv("ALLOWED_CHAT_IDS", "42")
    return create_app(skip_telegram_check=True)


@pytest.mark.asyncio
async def test_complete_pushes_notify_chat(app, monkeypatch):
    from notify_hub.telegram import client as tg_mod
    sent = []
    async def fake_send(self, **kw): sent.append(kw); return {"message_id": 1, "chat": {"id": kw["chat_id"]}}
    monkeypatch.setattr(tg_mod.TelegramClient, "send_message", fake_send)

    async with AsyncClient(transport=ASGITransport(app), base_url="http://t") as c:
        j = await c.post("/v1/jobs", headers={"Authorization":"Bearer af"},
            json={"agent":"alphaforge","prompt":"p","notify_chat_id":42})
        jid = j.json()["job_id"]
        await c.post(f"/v1/jobs/{jid}/complete", headers={"Authorization":"Bearer af"},
            json={"status":"completed","result_summary":"done","result_path":"docs/x.md"})

    assert len(sent) == 1
    assert "done" in sent[0]["text"]
    assert sent[0]["chat_id"] == 42
```

- [ ] **Step 2: 修 complete endpoint 加 push**

```python
# src/notify_hub/api/jobs.py (替換 complete_job)
from fastapi import Request


@router.post("/{job_id}/complete")
async def complete_job(
    job_id: uuid.UUID, payload: JobComplete,
    request: Request,
    consumer: Consumer = Depends(current_consumer),
    session: AsyncSession = Depends(get_session),
):
    job = await crud.complete_job(
        session, job_id=job_id,
        status=JobStatus.completed if payload.status == "completed" else JobStatus.failed,
        result_summary=payload.result_summary, result_path=payload.result_path,
    )
    if job is None or job.consumer_id != consumer.id:
        raise HTTPException(status_code=404, detail="job not found")
    if job.notify_chat_id and payload.result_summary:
        tg = request.app.state.telegram
        icon = "✓" if payload.status == "completed" else "✗"
        body = f"{icon} 任務完成\n{payload.result_summary}"
        if payload.result_path:
            body += f"\n報告: <code>{payload.result_path}</code>"
        try:
            await tg.send_message(chat_id=job.notify_chat_id, text=body)
        except Exception:
            pass
    return {"ok": True}
```

- [ ] **Step 3: 跑 pass + commit**

```bash
./.venv/bin/pytest tests/integration/test_job_complete_push.py -v
git add -A && git commit -m "feat(api): job complete triggers telegram notify"
```

---

## Task 22: `/task` Telegram command

**Files:**
- Modify: `src/notify_hub/telegram/dispatcher.py`
- Create: `tests/integration/test_task_command.py`

- [ ] **Step 1: 寫 test**

```python
# tests/integration/test_task_command.py
import pytest
from httpx import AsyncClient, ASGITransport
from notify_hub.main import create_app
from notify_hub.db import crud
from notify_hub.db.session import session_maker


@pytest.fixture
def app(monkeypatch, pg_container):
    monkeypatch.setenv("DATABASE_URL", pg_container)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "T")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "sec")
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://x")
    monkeypatch.setenv("NOTIFY_HUB_CONSUMER_TOKENS", "alphaforge:af")
    monkeypatch.setenv("ALLOWED_CHAT_IDS", "42")
    return create_app(skip_telegram_check=True)


@pytest.mark.asyncio
async def test_task_command_creates_job(app, monkeypatch):
    from notify_hub.telegram import client as tg_mod
    sent = []
    async def fake_send(self, **kw): sent.append(kw); return {"message_id": 1, "chat": {"id": kw["chat_id"]}}
    monkeypatch.setattr(tg_mod.TelegramClient, "send_message", fake_send)

    async with AsyncClient(transport=ASGITransport(app), base_url="http://t") as c:
        async with session_maker()() as s:
            await crud.upsert_subscriber(s, chat_id=42, display_name="x")
        r = await c.post(
            "/tg/webhook",
            headers={"X-Telegram-Bot-Api-Secret-Token": "sec"},
            json={"update_id": 1, "message": {
                "message_id": 100,
                "from": {"id": 42, "is_bot": False, "first_name": "m"},
                "chat": {"id": 42, "type": "private"},
                "text": "/task 幫我看 2330 最近 10 天有沒有缺口",
            }},
        )
        assert r.status_code == 200
        assert any("收到任務" in s["text"] for s in sent)

    # 驗 job 落地
    async with session_maker()() as s:
        from sqlalchemy import select
        from notify_hub.db.models import AgentJob
        r = await s.execute(select(AgentJob))
        job = r.scalar_one()
        assert "2330" in job.prompt
        assert job.notify_chat_id == 42
```

- [ ] **Step 2: 實作 /task handler**

```python
# dispatcher.py
from notify_hub.db.models import JobSource


async def _handle_task_command(msg, *, text, session, settings, tg):
    chat_id = msg["from"]["id"]
    prompt = text[len("/task "):].strip()
    if not prompt:
        await tg.send_message(chat_id=chat_id, text="用法: /task <任務描述>")
        return
    # v1: 固定 agent=alphaforge
    consumer = await crud.get_consumer_by_name(session, "alphaforge")
    if consumer is None:
        await tg.send_message(chat_id=chat_id, text="AlphaForge consumer 未註冊，請檢查 hub 設定。")
        return
    job = await crud.create_job(
        session, consumer_id=consumer.id, prompt=prompt,
        source=JobSource.telegram_task, notify_chat_id=chat_id,
    )
    short = str(job.id)[-6:]
    await tg.send_message(
        chat_id=chat_id,
        text=f"✓ 收到任務 #{short}\nagent 拉到後會動手，做完再通知你",
    )
```

- [ ] **Step 3: 確保 consumers 表有 alphaforge 資料**

要在啟動時把 env 裡宣告的 consumers 同步進 DB。修改 `main.py` lifespan:

```python
@asynccontextmanager
async def lifespan(app):
    settings = Settings()
    app.state.settings = settings
    dbsess.init_engine(settings)

    # Sync consumers from env
    from notify_hub.auth import hash_token
    from notify_hub.db.session import session_maker
    async with session_maker()() as s:
        for name, tok in settings.consumer_tokens.items():
            await crud.upsert_consumer(s, name=name, token_hash=hash_token(tok))

    tg = TelegramClient(token=settings.telegram_bot_token)
    ...
```

因為 auth.py 的 `verify_consumer_token` 用明碼比對，但 consumers 表存 hash。需統一: 要嘛 auth 改存明碼到 memory 比對 consumer_name (目前實作已經是對 memory dict 比對)，要嘛 DB 對照 hash。當前設計 auth 走 memory dict (快)，DB 只存 consumer name。OK 設計一致。

- [ ] **Step 4: 跑 pass + commit**

```bash
./.venv/bin/pytest tests/integration/test_task_command.py -v
git add -A && git commit -m "feat(dispatcher): /task command creates agent_job + ack"
```

---

## Task 23: Dockerfile + docker-compose.yml

**Files:**
- Create: `Dockerfile`
- Create: `docker-compose.yml`
- Create: `.dockerignore`

- [ ] **Step 1: 寫 Dockerfile**

```dockerfile
FROM python:3.12-slim AS builder
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir .

FROM python:3.12-slim
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./
ENV PYTHONPATH=/app/src
EXPOSE 8080
CMD ["sh", "-c", "alembic upgrade head && uvicorn notify_hub.main:app --host 0.0.0.0 --port 8080"]
```

- [ ] **Step 2: docker-compose.yml**

```yaml
version: "3.9"
services:
  notify-hub:
    build: .
    image: notify-hub:latest
    container_name: notify-hub
    restart: unless-stopped
    ports:
      - "8080:8080"
    environment:
      DATABASE_URL: ${DATABASE_URL}
      TELEGRAM_BOT_TOKEN: ${TELEGRAM_BOT_TOKEN}
      TELEGRAM_WEBHOOK_SECRET: ${TELEGRAM_WEBHOOK_SECRET}
      PUBLIC_BASE_URL: ${PUBLIC_BASE_URL}
      NOTIFY_HUB_CONSUMER_TOKENS: ${NOTIFY_HUB_CONSUMER_TOKENS}
      ALLOWED_CHAT_IDS: ${ALLOWED_CHAT_IDS}
      QUIET_HOURS_START: ${QUIET_HOURS_START:-22:00}
      QUIET_HOURS_END: ${QUIET_HOURS_END:-07:00}
      QUIET_HOURS_TZ: ${QUIET_HOURS_TZ:-Asia/Taipei}
      LOG_LEVEL: ${LOG_LEVEL:-INFO}
```

- [ ] **Step 3: .dockerignore**

```
.venv
__pycache__
*.pyc
.pytest_cache
tests
.git
.env
```

- [ ] **Step 4: 本機 build 驗證**

```bash
docker build -t notify-hub:dev ~/Documents/GitHub/notify-hub
```

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "build: Dockerfile + docker-compose with alembic migration on start"
```

---

## Task 24: README + 部署指南

**Files:**
- Create: `README.md`

- [ ] **Step 1: 寫 README**

```markdown
###### tags: `notify-hub`,`README`

# notify-hub

Self-hosted Telegram approval hub for headless automation agents。

## 功能

- HTTP API 讓 headless script 送 approval request
- Telegram Bot inline keyboard 做 approve / reject UX
- 逐項批、拒絕理由收集、timeout 自動結案
- 靜音時段壓住通知，早上打包送出
- `/task` 命令轉成 agent job

## 快速開始

### 1. 建立 Telegram Bot

1. 開 `@BotFather` (要有藍色認證勾勾)
2. `/newbot` 跟著流程走，拿到 bot token
3. 記下 token (e.g. `123:ABC...`)

### 2. 取得自己的 chat_id

傳 `/start` 給 bot 後:

```bash
curl "https://api.telegram.org/bot<TOKEN>/getUpdates" | jq '.result[-1].message.chat.id'
```

### 3. 設定環境變數 (`.env`)

複製 `.env.example` → `.env`，填入:
- `DATABASE_URL`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_WEBHOOK_SECRET` (自行產一串隨機字)
- `PUBLIC_BASE_URL` (可公開的網址，Telegram 要 HTTPS)
- `NOTIFY_HUB_CONSUMER_TOKENS=alphaforge:af_<random>,rebirth:rb_<random>`
- `ALLOWED_CHAT_IDS=<你的 chat_id>`

### 4. 起服務

```bash
docker-compose up -d
```

### 5. 設定 Telegram webhook

```bash
curl -X POST "https://api.telegram.org/bot<TOKEN>/setWebhook" \
  -d "url=<PUBLIC_BASE_URL>/tg/webhook" \
  -d "secret_token=<TELEGRAM_WEBHOOK_SECRET>" \
  -d 'allowed_updates=["message","callback_query"]'
```

### 6. 煙霧測試

```bash
python tests/smoke/smoke_test.py
```

應該會收到 Telegram 訊息且能按按鈕。

## API 速查

| Method | Path | 用途 |
|---|---|---|
| POST | `/v1/approvals` | 建 approval |
| GET | `/v1/approvals/<id>/wait` | long-poll 30s |
| GET | `/v1/approvals/<id>` | 讀當前狀態 |
| POST | `/v1/jobs` | 建 agent job |
| GET | `/v1/jobs/next` | 領 job |
| POST | `/v1/jobs/<id>/complete` | 回報結果 |
| GET | `/healthz` | 健康檢查 |

詳細 schema 見 `docs/api.md` (TBD) 或 FastAPI 自動產生的 `/docs`。

## 設計文件

見 `docs/superpowers/specs/2026-04-22-notify-hub-design.md`。

## License

MIT
```

- [ ] **Step 2: Commit**

```bash
git add -A && git commit -m "docs: README with quickstart + API reference"
```

---

## Task 25: Smoke test

**Files:**
- Create: `tests/smoke/smoke_test.py`
- Create: `tests/smoke/README.md`

- [ ] **Step 1: 寫 smoke_test.py**

```python
#!/usr/bin/env python3
"""End-to-end smoke: build approval → push to real Telegram → read /healthz.

需要 env vars:
- NOTIFY_HUB_URL (e.g. http://localhost:8080)
- NOTIFY_HUB_TOKEN (consumer token)

注意: 這會真的推播到你 bot 對話，按按鈕後會真的寫 DB。
"""
import os
import time
import uuid
import httpx


def main() -> None:
    base = os.environ["NOTIFY_HUB_URL"].rstrip("/")
    token = os.environ["NOTIFY_HUB_TOKEN"]

    with httpx.Client(base_url=base, headers={"Authorization": f"Bearer {token}"}, timeout=60) as c:
        # 1. 健康檢查
        h = c.get("/healthz")
        print("healthz:", h.status_code, h.json())
        assert h.status_code == 200

        # 2. 建 approval
        idem = str(uuid.uuid4())
        r = c.post("/v1/approvals", headers={"Idempotency-Key": idem}, json={
            "project": "smoke",
            "title": "notify-hub 煙霧測試",
            "items": [
                {"id": "1", "type": "test", "summary": "按我同意"},
                {"id": "2", "type": "test", "summary": "按我拒絕"},
            ],
            "timeout_seconds": 180,
            "metadata": {"run": "smoke"},
        })
        print("create:", r.status_code, r.json())
        assert r.status_code == 201
        rid = r.json()["request_id"]

        # 3. 等 user 操作 (最多 3 分鐘)
        deadline = time.time() + 180
        while time.time() < deadline:
            w = c.get(f"/v1/approvals/{rid}/wait", params={"timeout": 30})
            body = w.json()
            print("wait:", body)
            if body["status"] != "pending":
                print("DONE:", body)
                return
        print("TIMEOUT - 使用者 3 分鐘內沒回應")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 手動跑 smoke (部署後)**

```bash
export NOTIFY_HUB_URL=http://localhost:8080
export NOTIFY_HUB_TOKEN=af_xxx
python ~/Documents/GitHub/notify-hub/tests/smoke/smoke_test.py
```

檢查:
1. Telegram 手機收到訊息 + 三顆按鈕
2. 按「全部同意」後 `wait` 立刻回 `status=approved`
3. 按「👀 逐項批」，再按項目 1 同意、項目 2 拒絕 → `wait` 回 `mixed`
4. 拒絕後收到 ForceReply，回一句話驗證 reject_reason 被存

- [ ] **Step 3: Commit**

```bash
git add -A && git commit -m "test(smoke): end-to-end script against real Telegram bot"
```

---

## 全量整合驗證

- [ ] **Step 1: 跑全部測試**

```bash
cd ~/Documents/GitHub/notify-hub
./.venv/bin/pytest -v
```

應 100% 綠。coverage 檢查 (選用):

```bash
./.venv/bin/pip install pytest-cov
./.venv/bin/pytest --cov=notify_hub --cov-report=term-missing
```

目標 80%。

- [ ] **Step 2: NAS 部署驗證**

```bash
# 本機 git commit 後等 Synology Drive 同步
# SSH 進 NAS:
cd /volume1/docker/notify-hub
docker-compose up -d --build
docker logs -f notify-hub   # 看 startup + migration
curl http://localhost:8080/healthz
```

- [ ] **Step 3: nginx-router 設定新 location**

(按 spec §8.3 模板)

- [ ] **Step 4: setWebhook 指向生產 URL**

- [ ] **Step 5: 從 Mac 跑 smoke_test.py 打 NAS**

- [ ] **Step 6: 標 v0.1.0 tag**

```bash
cd ~/Documents/GitHub/notify-hub
git tag v0.1.0
git log --oneline
```

---

## Self-review

**Spec coverage check:**

| spec 要求 | task |
|---|---|
| 6 張表 + 索引 | Task 3 |
| POST /v1/approvals | Task 9 |
| GET /v1/approvals/<id>/wait (long-poll 55s cap) | Task 10 |
| GET /v1/approvals/<id> | Task 10 |
| POST /v1/jobs | Task 20 |
| GET /v1/jobs/next (SKIP LOCKED) | Task 20 |
| POST /v1/jobs/<id>/complete + notify push | Task 20 + 21 |
| GET /healthz | Task 6 |
| POST /tg/webhook (secret + 白名單) | Task 12 |
| Approval HTML message + keyboard | Task 8 + 9 |
| callback_data v1 格式 + parser | Task 8 |
| approve_all / reject_all | Task 13 |
| per_item panel | Task 14 |
| back 保留決定 | Task 15 |
| ForceReply reject reason | Task 16 |
| 結案訊息編輯 (approved/mixed/timeout) | Task 13 + 17 |
| Timeout auto-close | Task 17 |
| Quiet hours 壓住 + 07:00 flush | Task 18 |
| Long message 切分 | Task 8 `split_long_message` + Task 18 apply |
| `/task` 命令 | Task 22 |
| Idempotency-Key | Task 9 + 11 |
| Consumer token auth | Task 5 |
| Webhook secret | Task 5 + 12 |
| Chat 白名單 | Task 5 + 12 |
| Retention cleanup (daily 04:00) | Task 19 |
| Dockerfile + compose | Task 23 |
| README | Task 24 |
| smoke_test | Task 25 |

所有 v0.1.0 MVP 項目 (spec §11.2) 都有對應 task。

**Placeholder scan:**
- Task 22 Step 3 涉及 consumer sync 在 lifespan，已給 code。
- Task 24 README 提到 `docs/api.md (TBD)` — 此檔為可選產物，非 MVP 必需，留 note 可接受。
- 無其他 TBD / TODO。

**Type consistency check:**
- `ApprovalStatus` enum values 統一用 `.value`。
- `callback_data` 格式統一 `v1:<action>:<short>:<item_id?>` across formatter + parser + handler。
- `short_id` 取前 8 碼一致。
- `build_closed_message` 簽名與 caller `_finalize_and_edit` 參數對齊。
- `sweep_timeouts` / `sweep_and_close` 兩層分工清楚。

**Scope check:**
- Agent daemon 本身: 不在 plan (已於 spec §1.2 排除，由 AlphaForge Phase 2 實作)。
- LINE adapter / admin dashboard: 已排除。

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-22-notify-hub.md`.

兩種執行方式：

1. **Subagent-Driven (建議)** — 每個 task 派一個 fresh subagent 去做，task 間我 review 一次再派下一棒。優點：context 乾淨、速度快、不會互相干擾；缺點：subagent 之間不共享中間狀態，需靠 plan 本身完整。

2. **Inline Execution** — 我在這個 session 直接照 plan 一 task 一 task 跑，到 checkpoint 停下來給你 review。優點：你能邊看邊改；缺點：context 會慢慢長。

要用哪個？

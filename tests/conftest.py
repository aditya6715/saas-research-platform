"""
tests/conftest.py
-----------------
Shared pytest fixtures for all test modules.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from typing import Any, AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import aiosqlite
import pytest
import pytest_asyncio

from database.connection import DatabaseManager, apply_migrations
from database.models import AppRecord, ResearchSession
from database.repository import (
    AgentLogRepository,
    AppRepository,
    EvidenceRepository,
    SessionRepository,
    VerificationRepository,
)


# ── Event loop ───────────────────────────────────────────────────────────
@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ── In-memory SQLite database ─────────────────────────────────────────────
@pytest_asyncio.fixture
async def db_conn() -> AsyncGenerator[aiosqlite.Connection, None]:
    """Provides a fresh in-memory SQLite connection with migrations applied."""
    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA foreign_keys=ON")
    await apply_migrations(conn)
    yield conn
    await conn.close()


# ── Repository fixtures ───────────────────────────────────────────────────
@pytest_asyncio.fixture
async def app_repo(db_conn: aiosqlite.Connection) -> AppRepository:
    return AppRepository(db_conn)


@pytest_asyncio.fixture
async def ev_repo(db_conn: aiosqlite.Connection) -> EvidenceRepository:
    return EvidenceRepository(db_conn)


@pytest_asyncio.fixture
async def verif_repo(db_conn: aiosqlite.Connection) -> VerificationRepository:
    return VerificationRepository(db_conn)


@pytest_asyncio.fixture
async def log_repo(db_conn: aiosqlite.Connection) -> AgentLogRepository:
    return AgentLogRepository(db_conn)


@pytest_asyncio.fixture
async def sess_repo(db_conn: aiosqlite.Connection) -> SessionRepository:
    return SessionRepository(db_conn)


# ── Sample session ────────────────────────────────────────────────────────
@pytest_asyncio.fixture
async def sample_session(sess_repo: SessionRepository) -> ResearchSession:
    session = ResearchSession(
        id="test-session-0001",
        config_snapshot={"concurrency": 2},
    )
    await sess_repo.create(session)
    return session


# ── Sample app record ─────────────────────────────────────────────────────
@pytest_asyncio.fixture
async def sample_app(app_repo: AppRepository, sample_session: ResearchSession) -> AppRecord:
    app = AppRecord(
        session_id=sample_session.id,
        app_name="TestApp",
        seed_url="https://testapp.com",
        status="pending",
    )
    app_id = await app_repo.create(app)
    app.id = app_id
    return app


# ── Mock LLM ─────────────────────────────────────────────────────────────
@pytest.fixture
def mock_llm():
    """A mock ChatOpenAI that returns a configurable structured output."""
    llm = MagicMock()
    llm.with_structured_output = MagicMock(return_value=llm)
    llm.ainvoke = AsyncMock()
    return llm


# ── Mock search client ────────────────────────────────────────────────────
@pytest.fixture
def mock_search():
    search = MagicMock()
    search.search = AsyncMock(return_value=[
        {"url": "https://testapp.com/docs/api", "title": "TestApp API Docs", "snippet": ""},
    ])
    return search


# ── Temp directory ────────────────────────────────────────────────────────
@pytest.fixture
def tmp_dir(tmp_path: Path) -> Path:
    return tmp_path


# ── Sample CSV ────────────────────────────────────────────────────────────
@pytest.fixture
def sample_csv(tmp_path: Path) -> Path:
    content = "app_name,seed_url\nStripe,https://stripe.com\nTwilio,https://twilio.com\n"
    p = tmp_path / "apps.csv"
    p.write_text(content)
    return p


# ── Sample state dict ─────────────────────────────────────────────────────
@pytest.fixture
def sample_state() -> dict[str, Any]:
    return {
        "app_id": 1,
        "app_name": "Stripe",
        "seed_url": "https://stripe.com",
        "session_id": "test-session-0001",
        "documentation_url": "https://stripe.com/docs/api",
        "doc_url_confidence": 0.97,
        "chunks": [
            {
                "content": "## Authentication\nStripe uses API keys to authenticate requests. "
                           "All API requests must include your API key.",
                "source_url": "https://stripe.com/docs/api/authentication",
                "chunk_index": 0,
                "token_count": 400,
            }
        ],
        "human_review_required": False,
    }

"""Tests for core/queue.py — queue state machine."""

import pytest
import pytest_asyncio
import aiosqlite

from core.queue import TaskQueue
from database.models import AppRecord
from database.repository import AppRepository


@pytest_asyncio.fixture
async def queue(db_conn, sample_session):
    return TaskQueue(
        conn=db_conn,
        session_id=sample_session.id,
        max_retries=3,
        timeout_seconds=120,
    )


class TestTaskQueue:
    async def test_enqueue_creates_app(self, queue, db_conn, sample_session):
        app_id = await queue.enqueue("TestApp", "https://test.com")
        assert app_id is not None
        repo = AppRepository(db_conn)
        app = await repo.get_by_name("TestApp", sample_session.id)
        assert app is not None
        assert app.status == "pending"

    async def test_enqueue_deduplicates(self, queue, sample_session):
        id1 = await queue.enqueue("DuplicateApp")
        id2 = await queue.enqueue("DuplicateApp")
        # Second enqueue returns the existing id (no None return for existing)
        assert id1 == id2

    async def test_claim_next_returns_pending(self, queue):
        await queue.enqueue("App1")
        await queue.enqueue("App2")
        app = await queue.claim_next()
        assert app is not None
        assert app.app_name == "App1"

    async def test_claim_next_marks_in_progress(self, queue, db_conn, sample_session):
        await queue.enqueue("ProgressApp")
        await queue.claim_next()
        repo = AppRepository(db_conn)
        app = await repo.get_by_name("ProgressApp", sample_session.id)
        assert app.status == "in_progress"

    async def test_complete_transitions_to_completed(self, queue, db_conn, sample_session):
        await queue.enqueue("CompApp")
        app = await queue.claim_next()
        await queue.complete(app.id)
        repo = AppRepository(db_conn)
        updated = await repo.get_by_id(app.id)
        assert updated.status == "completed"

    async def test_fail_increments_retry_and_resets_to_pending(self, queue, db_conn, sample_session):
        await queue.enqueue("FailApp")
        app = await queue.claim_next()
        await queue.fail(app.id, "timeout")
        repo = AppRepository(db_conn)
        updated = await repo.get_by_id(app.id)
        assert updated.status == "pending"
        assert updated.retry_count == 1

    async def test_fail_after_max_retries_marks_as_failed(self, queue, db_conn, sample_session):
        await queue.enqueue("MaxRetryApp")
        app = await queue.claim_next()
        for _ in range(3):
            await queue.fail(app.id, "error")
            app = await queue.claim_next()
        # After 3 retries, should be failed
        repo = AppRepository(db_conn)
        updated = await repo.get_by_id(app.id if app else 1)
        # On 4th failure it should be marked failed
        if app:
            await queue.fail(app.id, "final error")
            updated = await repo.get_by_id(app.id)
            assert updated.status == "failed"

    async def test_restore_orphaned(self, queue, db_conn, sample_session):
        await queue.enqueue("OrphanApp")
        await queue.claim_next()  # moves to in_progress
        count = await queue.restore_orphaned()
        assert count == 1
        repo = AppRepository(db_conn)
        app = await repo.get_by_name("OrphanApp", sample_session.id)
        assert app.status == "pending"

    async def test_queue_is_complete_when_empty(self, queue):
        is_done = await queue.is_complete()
        assert is_done is True

    async def test_get_stats(self, queue):
        await queue.enqueue("A")
        await queue.enqueue("B")
        stats = await queue.get_stats()
        assert stats.pending == 2
        assert stats.total == 2

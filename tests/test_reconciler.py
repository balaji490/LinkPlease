import pytest
import time
from unittest.mock import AsyncMock
from app.services.dm_worker import DMWorker
from app.services.reconciler import StatusReconciler
from app.services.rate_limiter import AsyncRateLimiter

@pytest.mark.asyncio
async def test_reconciliation_delivers_successfully(test_app):
    db = test_app["db"]
    mock_client = test_app["mock_client"]

    # 1. Insert a job in 'sent_to_api' state
    now = time.time()
    async with db.get_connection() as conn:
        await conn.execute("""
            INSERT INTO dm_jobs (
                rule_id, recipient_user_id, comment_id, message,
                status, dm_id, attempts, max_attempts, next_attempt_at,
                created_at, updated_at
            ) VALUES ('r1', 'u1', 'c1', 'hello', 'sent_to_api', 'dm_123', 1, 5, ?, ?, ?)
        """, (now, now, now))
        await conn.commit()

    # Initial stats: 1 queued, 0 sent
    stats1 = await db.get_stats()
    assert stats1["queued"] == 1
    assert stats1["sent"] == 0

    # 2. Mock GET status returning 'delivered'
    mock_client.get_dm_status = AsyncMock(return_value=(True, "delivered", 200))

    reconciler = StatusReconciler(db, mock_client)
    await reconciler._reconcile_batch()

    # Stats now: 1 sent, 0 queued
    stats2 = await db.get_stats()
    assert stats2["sent"] == 1
    assert stats2["queued"] == 0
    assert stats2["failed"] == 0

@pytest.mark.asyncio
async def test_reconciliation_retries_on_delayed_failure(test_app):
    db = test_app["db"]
    mock_client = test_app["mock_client"]

    # 1. Insert a job in 'sent_to_api' state (attempt 1 of 5)
    now = time.time()
    async with db.get_connection() as conn:
        await conn.execute("""
            INSERT INTO dm_jobs (
                rule_id, recipient_user_id, comment_id, message,
                status, dm_id, attempts, max_attempts, next_attempt_at,
                created_at, updated_at
            ) VALUES ('r2', 'u2', 'c2', 'hello', 'sent_to_api', 'dm_456', 1, 5, ?, ?, ?)
        """, (now, now, now))
        await conn.commit()

    # 2. Mock GET status returning 'failed' (the 15% delayed failure scenario)
    mock_client.get_dm_status = AsyncMock(return_value=(True, "failed", 200))

    reconciler = StatusReconciler(db, mock_client)
    await reconciler._reconcile_batch()

    # Job should be re-enqueued to 'pending' with attempts = 2
    stats = await db.get_stats()
    assert stats["queued"] == 1
    assert stats["failed"] == 0

    async with db.get_connection() as conn:
        async with conn.execute("SELECT status, attempts, dm_id FROM dm_jobs WHERE recipient_user_id = 'u2'") as cursor:
            row = await cursor.fetchone()
            assert row["status"] == "pending"
            assert row["attempts"] == 2
            assert row["dm_id"] is None

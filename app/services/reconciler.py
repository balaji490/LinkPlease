import asyncio
import time
import random
import logging
from typing import Optional, List
from app.config import settings
from app.database import Database
from app.services.pseudogram import PseudoGramClient

logger = logging.getLogger(__name__)

class StatusReconciler:
    """
    Background worker that polls GET /v1/dm/{dm_id} for accepted DMs to catch
    terminal delivered/failed states and re-enqueue failed DMs for retry.
    Note: Reads do not consume rate limit quota.
    """
    def __init__(self, db: Database, client: PseudoGramClient):
        self.db = db
        self.client = client
        self._running = False
        self._task: Optional[asyncio.Task] = None

    def start(self):
        if not self._running:
            self._running = True
            self._task = asyncio.create_task(self._run_loop())
            logger.info("StatusReconciler background task started.")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            logger.info("StatusReconciler background task stopped.")

    async def _run_loop(self):
        while self._running:
            try:
                await self._reconcile_batch()
                await asyncio.sleep(settings.RECONCILER_INTERVAL)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"Error in StatusReconciler loop: {exc}", exc_info=True)
                await asyncio.sleep(2.0)

    async def _reconcile_batch(self):
        jobs: List[dict] = []
        async with self.db.get_connection() as conn:
            async with conn.execute("""
                SELECT id, rule_id, recipient_user_id, comment_id, dm_id, attempts, max_attempts
                FROM dm_jobs
                WHERE status = 'sent_to_api' AND dm_id IS NOT NULL
                ORDER BY updated_at ASC
                LIMIT ?
            """, (settings.RECONCILER_BATCH_SIZE,)) as cursor:
                rows = await cursor.fetchall()
                jobs = [dict(row) for row in rows]

        if not jobs:
            return

        for job in jobs:
            job_id = job["id"]
            dm_id = job["dm_id"]
            attempts = job["attempts"]
            max_attempts = job["max_attempts"]

            success, status, status_code = await self.client.get_dm_status(dm_id)
            if not success or not status:
                continue

            now = time.time()
            async with self.db.get_connection() as conn:
                if status == "delivered":
                    # Terminal success
                    await conn.execute("""
                        UPDATE dm_jobs
                        SET status = 'delivered',
                            updated_at = ?
                        WHERE id = ?
                    """, (now, job_id))
                    await conn.commit()
                    logger.info(f"Reconciled job {job_id} ({dm_id}) -> DELIVERED")

                elif status == "failed":
                    # Accepted but later failed by upstream platform!
                    new_attempts = attempts + 1
                    if new_attempts >= max_attempts:
                        await conn.execute("""
                            UPDATE dm_jobs
                            SET status = 'failed',
                                attempts = ?,
                                last_error = 'upstream_terminal_failure',
                                updated_at = ?
                            WHERE id = ?
                        """, (new_attempts, now, job_id))
                        await conn.commit()
                        logger.error(f"Reconciled job {job_id} ({dm_id}) -> PERMANENT FAILED after {new_attempts} attempts")
                    else:
                        # Re-enqueue for retry
                        backoff = min(
                            settings.MAX_RETRY_BACKOFF_SECONDS,
                            settings.INITIAL_RETRY_BACKOFF_SECONDS * (2 ** (new_attempts - 1))
                        )
                        jitter = random.uniform(0.1, 0.5)
                        next_time = now + backoff + jitter
                        await conn.execute("""
                            UPDATE dm_jobs
                            SET status = 'pending',
                                dm_id = NULL,
                                attempts = ?,
                                next_attempt_at = ?,
                                last_error = 'upstream_accepted_failed_retry',
                                updated_at = ?
                            WHERE id = ?
                        """, (new_attempts, next_time, now, job_id))
                        await conn.commit()
                        logger.warning(f"Reconciled job {job_id} ({dm_id}) -> Upstream failed. Re-queued for retry {new_attempts}/{max_attempts}")

                elif status == "queued":
                    # Still queued on upstream
                    pass

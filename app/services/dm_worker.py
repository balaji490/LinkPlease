import asyncio
import time
import random
import logging
from typing import Optional
from app.config import settings
from app.database import Database
from app.services.rate_limiter import AsyncRateLimiter
from app.services.pseudogram import PseudoGramClient

logger = logging.getLogger(__name__)

class DMWorker:
    def __init__(
        self,
        db: Database,
        rate_limiter: AsyncRateLimiter,
        client: PseudoGramClient
    ):
        self.db = db
        self.rate_limiter = rate_limiter
        self.client = client
        self._running = False
        self._task: Optional[asyncio.Task] = None

    def start(self):
        if not self._running:
            self._running = True
            self._task = asyncio.create_task(self._run_loop())
            logger.info("DMWorker background task started.")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            logger.info("DMWorker background task stopped.")

    async def _run_loop(self):
        while self._running:
            try:
                processed = await self._process_next_job()
                if not processed:
                    await asyncio.sleep(settings.WORKER_POLL_INTERVAL)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"Error in DMWorker loop: {exc}", exc_info=True)
                await asyncio.sleep(1.0)

    async def _process_next_job(self) -> bool:
        now = time.time()
        job = None

        async with self.db.get_connection() as conn:
            async with conn.execute("""
                SELECT id, rule_id, recipient_user_id, comment_id, message, attempts, max_attempts
                FROM dm_jobs
                WHERE status = 'pending' AND next_attempt_at <= ?
                ORDER BY id ASC
                LIMIT 1
            """, (now,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    job = dict(row)

        if not job:
            return False

        # Acquire rate limit slot before making outbound API call
        await self.rate_limiter.acquire()

        job_id = job["id"]
        rule_id = job["rule_id"]
        recipient_user_id = job["recipient_user_id"]
        comment_id = job["comment_id"]
        message = job["message"]
        attempts = job["attempts"]
        max_attempts = job["max_attempts"]

        # Deterministic idempotency key for mock API deduplication
        idempotency_key = f"lp_{rule_id}_{recipient_user_id}"

        logger.info(f"Dispatching DM job {job_id} to user {recipient_user_id}")
        is_accepted, dm_id, status_code, retry_after = await self.client.send_dm(
            recipient_user_id=recipient_user_id,
            message=message,
            comment_id=comment_id,
            idempotency_key=idempotency_key
        )

        now = time.time()
        async with self.db.get_connection() as conn:
            if is_accepted and status_code in (200, 201, 202):
                # Successfully accepted by PseudoGram API
                await conn.execute("""
                    UPDATE dm_jobs
                    SET status = 'sent_to_api',
                        dm_id = ?,
                        updated_at = ?
                    WHERE id = ?
                """, (dm_id, now, job_id))
                await conn.commit()
                logger.info(f"Job {job_id} accepted with dm_id {dm_id}")
                return True

            if status_code == 429:
                # Rate limit exceeded on PseudoGram
                pause_time = retry_after or 5.0
                await self.rate_limiter.pause(pause_time)
                await conn.execute("""
                    UPDATE dm_jobs
                    SET next_attempt_at = ?,
                        last_error = 'rate_limited_429',
                        updated_at = ?
                    WHERE id = ?
                """, (now + pause_time, now, job_id))
                await conn.commit()
                return True

            if status_code == 400:
                # Invalid request - permanent failure
                await conn.execute("""
                    UPDATE dm_jobs
                    SET status = 'failed',
                        last_error = 'invalid_request_400',
                        updated_at = ?
                    WHERE id = ?
                """, (now, job_id))
                await conn.commit()
                logger.error(f"Job {job_id} permanently failed: 400 Invalid Request")
                return True

            # 500 Internal Error, connection failure, or other 5xx
            new_attempts = attempts + 1
            if new_attempts >= max_attempts:
                # Max retries exhausted
                await conn.execute("""
                    UPDATE dm_jobs
                    SET status = 'failed',
                        attempts = ?,
                        last_error = ?,
                        updated_at = ?
                    WHERE id = ?
                """, (new_attempts, f"status_{status_code}_max_retries_exhausted", now, job_id))
                await conn.commit()
                logger.error(f"Job {job_id} permanently failed after {new_attempts} attempts")
            else:
                # Schedule retry with exponential backoff + jitter
                backoff = min(
                    settings.MAX_RETRY_BACKOFF_SECONDS,
                    settings.INITIAL_RETRY_BACKOFF_SECONDS * (2 ** (new_attempts - 1))
                )
                jitter = random.uniform(0.1, 0.5)
                next_time = now + backoff + jitter
                await conn.execute("""
                    UPDATE dm_jobs
                    SET attempts = ?,
                        next_attempt_at = ?,
                        last_error = ?,
                        updated_at = ?
                    WHERE id = ?
                """, (new_attempts, next_time, f"retry_after_status_{status_code}", now, job_id))
                await conn.commit()
                logger.warning(f"Job {job_id} scheduled retry {new_attempts}/{max_attempts} in {backoff:.2f}s")

            return True

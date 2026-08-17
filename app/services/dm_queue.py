import time
import sqlite3
import aiosqlite
import logging
from typing import Optional
from app.database import Database
from app.models import WebhookPayload
from app.services.rule_engine import RuleEngine

logger = logging.getLogger(__name__)

class DMQueueService:
    def __init__(self, db: Database, rule_engine: RuleEngine):
        self.db = db
        self.rule_engine = rule_engine

    async def handle_webhook(self, payload: WebhookPayload) -> dict:
        """
        Processes incoming webhook event. Fast, non-blocking, and serialized for SQLite concurrency.
        """
        now = time.time()
        event_id = payload.event_id
        event_type = payload.event_type
        data = payload.data

        async with self.db.write_lock:
            async with self.db.get_connection() as conn:
                # 1. Check event deduplication
                try:
                    await conn.execute(
                        "INSERT INTO processed_events (event_id, event_type, received_at) VALUES (?, ?, ?)",
                        (event_id, event_type, now)
                    )
                    await conn.commit()
                except sqlite3.IntegrityError:
                    # Duplicate event_id received
                    logger.info(f"Duplicate event_id received: {event_id}")
                    # If this was a comment creation with a matching rule, mark duplicate blocked
                    if event_type == "comment.created" and data.text:
                        matched_rules = await self.rule_engine.match_rules(data.text)
                        if matched_rules:
                            await self.db.increment_duplicates_blocked(len(matched_rules), conn=conn)
                    return {"status": "duplicate_event_skipped"}

                # 2. Handle comment.deleted event
                if event_type == "comment.deleted":
                    comment_id = data.comment_id
                    logger.info(f"Processing comment.deleted for comment_id: {comment_id}")
                    # Add to tombstones
                    await conn.execute(
                        "INSERT OR IGNORE INTO tombstones (comment_id, deleted_at) VALUES (?, ?)",
                        (comment_id, now)
                    )
                    # Cancel any pending DM jobs that haven't been dispatched to API yet
                    await conn.execute(
                        "UPDATE dm_jobs SET status = 'cancelled', last_error = 'comment_deleted', updated_at = ? WHERE comment_id = ? AND status = 'pending'",
                        (now, comment_id)
                    )
                    await conn.commit()
                    return {"status": "comment_deleted_processed"}

                # 3. Handle comment.created event
                if event_type == "comment.created":
                    comment_id = data.comment_id
                    recipient_user_id = data.from_user.user_id if data.from_user else None
                    text = data.text

                    if not recipient_user_id:
                        logger.warning(f"Comment {comment_id} missing user_id. Dropping.")
                        return {"status": "missing_user_id"}

                    # Check if this comment was already deleted (out-of-order arrival)
                    async with conn.execute("SELECT comment_id FROM tombstones WHERE comment_id = ?", (comment_id,)) as cursor:
                        tombstone = await cursor.fetchone()
                        if tombstone:
                            logger.info(f"Comment {comment_id} already tombstoned. Skipping DM dispatch.")
                            return {"status": "comment_already_deleted"}

                    # Match rules
                    matched_rules = await self.rule_engine.match_rules(text)
                    if not matched_rules:
                        return {"status": "no_rules_matched"}

                    queued_count = 0
                    for rule in matched_rules:
                        rule_id = rule["rule_id"]
                        dm_message = rule["dm_message"]

                        # Attempt atomic insert into dm_jobs
                        try:
                            await conn.execute("""
                                INSERT INTO dm_jobs (
                                rule_id, recipient_user_id, comment_id, message,
                                status, attempts, max_attempts, next_attempt_at,
                                created_at, updated_at
                            ) VALUES (?, ?, ?, ?, 'pending', 0, 5, ?, ?, ?)
                        """, (rule_id, recipient_user_id, comment_id, dm_message, now, now, now))
                            await conn.commit()
                            queued_count += 1
                            logger.info(f"Queued DM for user {recipient_user_id} on rule {rule_id}")
                        except sqlite3.IntegrityError:
                            # User already received / queued a DM for this rule!
                            logger.info(f"Duplicate DM blocked for user {recipient_user_id} on rule {rule_id}")
                            await self.db.increment_duplicates_blocked(1, conn=conn)

                    return {"status": "processed", "queued": queued_count}

                return {"status": "unsupported_event_type"}

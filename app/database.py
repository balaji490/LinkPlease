import aiosqlite
import asyncio
from contextlib import asynccontextmanager
from typing import Optional, List, Dict, Any, Tuple
import time

class Database:
    def __init__(self, db_path: str = "linkplease.db"):
        self.db_path = db_path
        self.write_lock = asyncio.Lock()

    @asynccontextmanager
    async def get_connection(self):
        async with aiosqlite.connect(self.db_path, timeout=30.0) as conn:
            conn.row_factory = aiosqlite.Row
            await conn.execute("PRAGMA journal_mode = WAL;")
            await conn.execute("PRAGMA synchronous = NORMAL;")
            await conn.execute("PRAGMA busy_timeout = 30000;")
            await conn.execute("PRAGMA foreign_keys = ON;")
            yield conn

    async def init_db(self):
        async with self.write_lock:
            async with self.get_connection() as conn:
                await conn.executescript("""
                    CREATE TABLE IF NOT EXISTS rules (
                        rule_id TEXT PRIMARY KEY,
                        keyword TEXT NOT NULL,
                        dm_message TEXT NOT NULL,
                        created_at REAL NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS processed_events (
                        event_id TEXT PRIMARY KEY,
                        event_type TEXT NOT NULL,
                        received_at REAL NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS tombstones (
                        comment_id TEXT PRIMARY KEY,
                        deleted_at REAL NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS dm_jobs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        rule_id TEXT NOT NULL,
                        recipient_user_id TEXT NOT NULL,
                        comment_id TEXT NOT NULL,
                        message TEXT NOT NULL,
                        dm_id TEXT,
                        status TEXT NOT NULL,
                        attempts INTEGER DEFAULT 0,
                        max_attempts INTEGER DEFAULT 5,
                        next_attempt_at REAL DEFAULT 0,
                        last_error TEXT,
                        created_at REAL NOT NULL,
                        updated_at REAL NOT NULL,
                        UNIQUE(rule_id, recipient_user_id)
                    );

                    CREATE INDEX IF NOT EXISTS idx_dm_jobs_status_next ON dm_jobs(status, next_attempt_at);
                    CREATE INDEX IF NOT EXISTS idx_dm_jobs_dm_id ON dm_jobs(dm_id);
                    CREATE INDEX IF NOT EXISTS idx_dm_jobs_comment_id ON dm_jobs(comment_id);

                    CREATE TABLE IF NOT EXISTS stats_counters (
                        key TEXT PRIMARY KEY,
                        value INTEGER NOT NULL DEFAULT 0
                    );

                    INSERT OR IGNORE INTO stats_counters (key, value) VALUES ('duplicates_blocked', 0);
                """)
                await conn.commit()

    async def increment_duplicates_blocked(self, count: int = 1, conn: Optional[aiosqlite.Connection] = None):
        if conn is not None:
            await conn.execute(
                "UPDATE stats_counters SET value = value + ? WHERE key = 'duplicates_blocked'",
                (count,)
            )
            await conn.commit()
        else:
            async with self.write_lock:
                async with self.get_connection() as c:
                    await c.execute(
                        "UPDATE stats_counters SET value = value + ? WHERE key = 'duplicates_blocked'",
                        (count,)
                    )
                    await c.commit()

    async def get_stats(self) -> Dict[str, int]:
        async with self.get_connection() as conn:
            # Query counts grouped by status
            async with conn.execute("""
                SELECT status, COUNT(*) as cnt 
                FROM dm_jobs 
                GROUP BY status
            """) as cursor:
                rows = await cursor.fetchall()
                counts = {row["status"]: row["cnt"] for row in rows}

            # Query duplicates_blocked counter
            async with conn.execute(
                "SELECT value FROM stats_counters WHERE key = 'duplicates_blocked'"
            ) as cursor:
                row = await cursor.fetchone()
                duplicates_blocked = row["value"] if row else 0

            sent = counts.get("delivered", 0)
            failed = counts.get("failed", 0)
            queued = counts.get("pending", 0) + counts.get("sent_to_api", 0)

            return {
                "sent": sent,
                "failed": failed,
                "queued": queued,
                "duplicates_blocked": duplicates_blocked
            }

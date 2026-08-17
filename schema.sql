-- ==========================================================
-- LinkPlease Database Schema (SQLite with WAL mode)
-- ==========================================================

PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA busy_timeout = 30000;
PRAGMA foreign_keys = ON;

-- 1. Rules Table: stores creator-configured keyword rules
CREATE TABLE IF NOT EXISTS rules (
    rule_id TEXT PRIMARY KEY,
    keyword TEXT NOT NULL,
    dm_message TEXT NOT NULL,
    created_at REAL NOT NULL
);

-- 2. Processed Events Table: deduplicates redelivered webhook event_ids
CREATE TABLE IF NOT EXISTS processed_events (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    received_at REAL NOT NULL
);

-- 3. Tombstones Table: tracks deleted comments for out-of-order event protection
CREATE TABLE IF NOT EXISTS tombstones (
    comment_id TEXT PRIMARY KEY,
    deleted_at REAL NOT NULL
);

-- 4. DM Jobs Table: persistent queue for outgoing DMs with strict user-rule idempotency
CREATE TABLE IF NOT EXISTS dm_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_id TEXT NOT NULL,
    recipient_user_id TEXT NOT NULL,
    comment_id TEXT NOT NULL,
    message TEXT NOT NULL,
    dm_id TEXT,
    status TEXT NOT NULL,          -- 'pending', 'sent_to_api', 'delivered', 'failed', 'cancelled'
    attempts INTEGER DEFAULT 0,
    max_attempts INTEGER DEFAULT 5,
    next_attempt_at REAL DEFAULT 0,
    last_error TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    UNIQUE(rule_id, recipient_user_id) -- Strict idempotency: same user never gets DMed twice for same rule
);

-- Indexes for lightning-fast queue polling and status reconciliation
CREATE INDEX IF NOT EXISTS idx_dm_jobs_status_next ON dm_jobs(status, next_attempt_at);
CREATE INDEX IF NOT EXISTS idx_dm_jobs_dm_id ON dm_jobs(dm_id);
CREATE INDEX IF NOT EXISTS idx_dm_jobs_comment_id ON dm_jobs(comment_id);

-- 5. Stats Counters Table: tracks global blocked duplicates atomically
CREATE TABLE IF NOT EXISTS stats_counters (
    key TEXT PRIMARY KEY,
    value INTEGER NOT NULL DEFAULT 0
);

INSERT OR IGNORE INTO stats_counters (key, value) VALUES ('duplicates_blocked', 0);

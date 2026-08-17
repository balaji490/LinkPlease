# FAILURES.md — Known Failure Modes & Reliability Analysis

This document details every specific scenario in which this system can still lose a DM, send a duplicate DM, or report an inaccurate number under hostile conditions, crashes, or load spikes.

---

### 1. In-Flight Network Crash During `POST /v1/dm/send` Can Trigger a Duplicate DM (At-Least-Once Risk)
* **Condition:** The worker dispatches `POST /v1/dm/send` with an `Idempotency-Key`. The upstream PseudoGram server accepts and records the DM, but the HTTP connection drops (TCP reset / socket timeout) before our client receives the `202 Accepted` response.
* **Result:** Our system treats the network drop as a transient 5xx/transport failure and re-enqueues the job with an exponential backoff.
* **Why it can duplicate:** Even though we send an `Idempotency-Key`, if the upstream platform's mock idempotency cache has a short TTL or encounters an internal cache miss, retrying the dispatch will create a second DM execution.

---

### 2. `comment.deleted` Arriving After Outbound Dispatch (Race Window with Platform Ingestion)
* **Condition:** A user comments `PRICE` and deletes it 300ms later. Our worker picks up the job and sends `POST /v1/dm/send` at $t=200\text{ms}$. The `comment.deleted` webhook arrives at $t=300\text{ms}$.
* **Result:** The DM was already accepted by PseudoGram (`status: sent_to_api`). Our tombstone catches the deleted comment, but because the message has already left our boundary and entered PseudoGram's queue, the DM is delivered to the user anyway.
* **Tradeoff:** To completely eliminate this, we would have to artificially delay all DM dispatches by several seconds to wait for potential deletions, severely degrading user responsiveness for the 99% legitimate comments.

---

### 3. Server Crash / Hard Kill During Retry Backoff In SQLite WAL Checkpoint
* **Condition:** A DM receives a `500 Internal Error` or `429 Too Many Requests` from PseudoGram, and the worker schedules a retry by updating `next_attempt_at = now + 15.0`. If the host process is abruptly killed (`SIGKILL` / power loss) before SQLite flushes the WAL buffer to disk (or during a corrupted WAL checkpoint), the state reverts to before the update or corrupts the single-file database.
* **Result:** While persistent jobs in the DB survive regular process restarts (since the background worker polls `next_attempt_at <= now()`), an uncheckpointed hard crash can cause jobs stuck in `sent_to_api` to remain perpetually un-reconciled if the `dm_id` write was lost.

---

### 4. Upstream Rate Limit Starvation Under Sustained Ingestion Storms (Queue Lag & Event Expiration)
* **Condition:** 5,000 comments arrive over 60 seconds (83 comments/sec), but PseudoGram strictly enforces **10 requests per 60 seconds** (1 send every 6 seconds).
* **Result:** The 5,000 jobs are durably queued in SQLite, but the drain rate is fixed at 10 DMs/minute. The 5,000th DM will take $\frac{5000}{10} \times 60 = 30,000\text{ seconds}$ ($\approx 8.3\text{ hours}$) to send.
* **Why numbers or delivery can fail:** In a real Instagram production environment, Instagram comment tokens or user context expire within hours. Furthermore, if a user changes their username or blocks the creator during those 8 hours, delivery will fail terminally when eventually dispatched.

---

### 5. Delayed Reconciliation Zombie State on 404 / Vanished `dm_id`
* **Condition:** A DM receives `202 Accepted` with `dm_id: "dm_abc"`. However, when our reconciler polls `GET /v1/dm/dm_abc`, the upstream server returns `404 Not Found` (e.g. due to internal upstream node desynchronization or partitioned replica).
* **Result:** The current reconciler ignores non-200 responses to avoid premature failure during upstream outages. If the upstream never recovers `dm_abc`, that job remains in `queued` (`status: sent_to_api`) forever and is never counted in `sent` or `failed`, causing `/stats` to permanently report an inflated `queued` count.

---

### 6. SQLite Concurrency Ceiling on Massive Scale (Single Writer Bottleneck)
* **Condition:** While SQLite with WAL mode handles hundreds of concurrent reads seamlessly, write transactions are serialized by a single file lock. If incoming webhooks exceed $\approx 1,500\text{ req/sec}$ on a constrained single-core cloud instance, write lock wait times will exceed `busy_timeout` (30s), throwing `sqlite3.OperationalError: database is locked` and dropping webhook acknowledgments.
* **Fix for Week 2:** Migrate the persistence layer to PostgreSQL with a Redis-backed queue (`Celery` / `BullMQ` / `ARQ`) with partitioned locks on `(rule_id, user_id)`.

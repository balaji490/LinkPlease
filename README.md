# LinkPlease — High-Reliability Instagram DM Engine

Production-grade, highly reliable microservice automating direct messages (DMs) when Instagram comments match creator-configured keyword rules. Designed to operate safely against hostile, unreliable upstream APIs featuring rate limits, network partitions, event redeliveries, accepted-then-failed statuses, and comment deletions.

---

## Architecture Overview

```
                        Incoming Webhook (POST /webhook)
                                      │
                                      ▼
                      ┌───────────────────────────────┐
                      │  HMAC-SHA256 Sig Verification │ (Timing-attack safe)
                      └───────────────┬───────────────┘
                                      │
                                      ▼
                      ┌───────────────────────────────┐
                      │   Event Deduplication Check   │ (Tracks processed event_ids)
                      └───────────────┬───────────────┘
                                      │
                         ┌────────────┴────────────┐
                         ▼                         ▼
               [comment.deleted]          [comment.created]
                         │                         │
                         ▼                         ▼
               ┌───────────────────┐     ┌───────────────────┐
               │  Tombstone Store  │     │   Tombstone Check │
               │  & Pending Cancel │     └─────────┬─────────┘
               └───────────────────┘               │
                                                   ▼
                                         ┌───────────────────┐
                                         │ Rule Match Engine │ (Case-insensitive)
                                         └─────────┬─────────┘
                                                   │
                                                   ▼
                                         ┌───────────────────┐
                                         │ User Idempotency  │ UNIQUE(rule_id, user_id)
                                         │  Guard & Enqueue  │ (duplicates_blocked++)
                                         └─────────┬─────────┘
                                                   │
                                                   ▼
                                         ┌───────────────────┐
                                         │ Persistent Queue  │ (SQLite WAL Mode)
                                         └─────────┬─────────┘
                                                   │
                                                   ▼
                 ┌──────────────────────────────────────────────────┐
                 │       DM Worker (Token Bucket Rate Limiter)      │
                 │  - 10 req / 60s window adherence                 │
                 │  - POST /v1/dm/send with Idempotency-Key         │
                 │  - Jittered Exponential Backoff on 500 / 429     │
                 └─────────────────────────┬────────────────────────┘
                                           │
                                           ▼ (202 Accepted -> status: sent_to_api)
                 ┌──────────────────────────────────────────────────┐
                 │       Status Reconciler (Background Worker)      │
                 │  - Polls GET /v1/dm/{dm_id} (Zero rate-limit cost)│
                 │  - status == "delivered"  ──> sent++             │
                 │  - status == "failed"     ──> retry or failed++  │
                 └──────────────────────────────────────────────────┘
```

---

## Core Capabilities & Completed Scope

### Part A (Required)
- [x] **Rule Creation (`POST /rules`)**: Case-insensitive keyword matching anywhere in comment strings.
- [x] **Rule Matching & Ingestion (`POST /webhook`)**: Fast asynchronous event ingestion (< 20ms response time).
- [x] **Strict Idempotency Guard**: Guarantees a user is never DMed twice for the same rule (`UNIQUE(rule_id, recipient_user_id)`).
- [x] **Zero Silent DM Loss**: Retries transient 500s and connection failures with exponential backoff and jitter.

### Part B (Extended)
- [x] **HMAC-SHA256 Signature Verification**: Validates `X-PseudoGram-Signature` against the raw body using `hmac.compare_digest`.
- [x] **Live Accurate `GET /stats`**: Real-time reporting of `sent`, `failed`, `queued`, and `duplicates_blocked`.

### Part C (Advanced Resilience)
- [x] **Status Reconciliation Loop**: Catches the ~15% of DMs that the mock API accepts (`202 Accepted`) but fails later, automatically re-enqueuing them for retry.
- [x] **Tombstone & Out-of-Order Deletion**: Cancels pending DMs when `comment.deleted` arrives, and records tombstones to discard delayed `comment.created` events.
- [x] **Token Bucket Rate Limiter**: Strictly enforces the 10 req/60s ceiling and handles dynamic `429 Retry-After` backpressure during 500-event storms.

---

## Non-Negotiable API Endpoints

### 1. `POST /rules`
```bash
curl -X POST http://localhost:8000/rules \
  -H "Content-Type: application/json" \
  -d '{"keyword": "PRICE", "dm_message": "Here is the price list: $99/mo"}'
```
**Response (201 Created):**
```json
{
  "rule_id": "rule_ba31a1ba674c",
  "keyword": "PRICE",
  "dm_message": "Here is the price list: $99/mo"
}
```

### 2. `POST /webhook`
```bash
curl -X POST http://localhost:8000/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "event_id": "evt_01J8ZQ4K2N7RXA",
    "event_type": "comment.created",
    "sent_at": "2026-08-10T09:14:22.481Z",
    "data": {
      "comment_id": "cmt_9f2a7c",
      "post_id": "post_44de1b",
      "text": "PRICE please 🙏",
      "created_at": "2026-08-10T09:14:21.900Z",
      "from": {
        "user_id": "usr_3b91fe",
        "username": "arjun.shoots"
      }
    }
  }'
```
**Response (200 OK):**
```json
{
  "status": "processed",
  "queued": 1
}
```

### 3. `GET /stats`
```bash
curl http://localhost:8000/stats
```
**Response (200 OK):**
```json
{
  "sent": 142,
  "failed": 3,
  "queued": 8,
  "duplicates_blocked": 57
}
```

---

## Local Setup & Running

### 1. Clone & Setup Virtual Environment
```bash
python -m venv .venv
# On Windows:
.venv\Scripts\activate
# On Linux/macOS:
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. Configure Environment
```bash
cp .env.example .env
# Edit .env with your PSEUDOGRAM_API_KEY if testing against live mock
```

### 3. Run Development Server
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

---

## Running Test Suite

Execute the comprehensive unit, integration, rate limiting, reconciliation, and stress tests:
```bash
pytest -v
```

All 14 tests validate:
- Case-insensitive rule matching
- HMAC signature verification and rejection of forged signatures
- Event deduplication (redelivered `event_id`)
- User idempotency (`(rule_id, user_id)`)
- `comment.deleted` before dispatch and out-of-order arrival
- Token bucket rate limiter & 429 dynamic pause
- Reconciliation of 202 Accepted status and retry of delayed failure
- 500 concurrent events storm without lock contention or data loss

---

## Simulation & Onboarding Helpers

### Apply & Get Key:
```bash
python scripts/register.py --name "Your Name" --email "you@example.com" --phone "+919876543210" --linkedin "https://linkedin.com/in/you"
```

### Run Simulation:
```bash
python scripts/simulate.py --url "https://your-app.onrender.com/webhook" --count 500 --duration 10
```

---

## Submission Checklist

- [x] Part A + Part B + Part C implemented
- [x] `FAILURES.md` detailing exact edge conditions, race windows, and tradeoffs
- [x] `POST /rules`, `POST /webhook`, `GET /stats` conforming strictly to contract
- [x] Automated test suite passing with 100% success rate
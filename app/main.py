import os
import logging
import sys
from contextlib import asynccontextmanager
from typing import List, Any
from fastapi import FastAPI, Request, HTTPException, status
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import Database
from app.models import RuleCreateRequest, RuleResponse, StatsResponse, WebhookPayload
from app.services.rate_limiter import AsyncRateLimiter
from app.services.pseudogram import PseudoGramClient
from app.services.rule_engine import RuleEngine
from app.services.dm_queue import DMQueueService
from app.services.dm_worker import DMWorker
from app.services.reconciler import StatusReconciler
from app.services.security import verify_signature

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("linkplease")

# Global singletons
db = Database(settings.DATABASE_PATH)
rate_limiter = AsyncRateLimiter(
    max_requests=settings.RATE_LIMIT_REQUESTS,
    window_seconds=settings.RATE_LIMIT_WINDOW_SECONDS
)
pseudogram_client = PseudoGramClient(
    base_url=settings.PSEUDOGRAM_BASE_URL,
    api_key=settings.PSEUDOGRAM_API_KEY
)
rule_engine = RuleEngine(db)
queue_service = DMQueueService(db, rule_engine)
dm_worker = DMWorker(db, rate_limiter, pseudogram_client)
reconciler = StatusReconciler(db, pseudogram_client)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Initializing database...")
    await db.init_db()
    await rule_engine.reload_cache()
    
    logger.info("Starting background DM worker & reconciler...")
    dm_worker.start()
    reconciler.start()
    
    yield
    
    # Shutdown
    logger.info("Shutting down workers and clients...")
    await dm_worker.stop()
    await reconciler.stop()
    await pseudogram_client.close()


app = FastAPI(
    title="LinkPlease Mini-Engine",
    description="Automated Instagram DM platform for creators with strict idempotency and resilience",
    version="1.0.0",
    lifespan=lifespan
)

# Serve static files (banner image, etc.)
_static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=_static_dir), name="static")


@app.get("/")
async def serve_dashboard():
    """Serves the interactive web dashboard."""
    html_path = os.path.join(os.path.dirname(__file__), "static", "index.html")
    if os.path.exists(html_path):
        return FileResponse(html_path)
    return {"status": "ok", "app": "LinkPlease Mini-Engine"}


@app.get("/health")
async def health_check():
    return {"status": "ok", "app": "LinkPlease"}


@app.post("/rules", response_model=RuleResponse, status_code=status.HTTP_201_CREATED)
async def create_rule(rule_req: RuleCreateRequest):
    """
    Create a new keyword-triggered DM rule.
    Keyword matching is case-insensitive and matches anywhere in the comment text.
    """
    if not rule_req.keyword or not rule_req.dm_message:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="keyword and dm_message cannot be empty"
        )
    rule = await rule_engine.create_rule(
        keyword=rule_req.keyword.strip(),
        dm_message=rule_req.dm_message
    )
    return rule


@app.post("/webhook")
async def receive_webhook(request: Request):
    """
    Ingest incoming comment events. Must respond with 200 within 5 seconds.
    Verifies HMAC-SHA256 signature if enabled or signature header is provided.
    """
    raw_body = await request.body()
    signature = request.headers.get("X-PseudoGram-Signature")

    # Verify signature if configured in settings or header present
    if settings.VERIFY_SIGNATURE or (signature and settings.PSEUDOGRAM_API_KEY):
        if not verify_signature(raw_body, signature, settings.PSEUDOGRAM_API_KEY):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid webhook signature"
            )

    try:
        payload_dict = await request.json()
        payload = WebhookPayload(**payload_dict)
    except Exception as exc:
        logger.error(f"Failed to parse webhook JSON payload: {exc}")
        return JSONResponse(status_code=status.HTTP_200_OK, content={"status": "invalid_payload_dropped"})

    # Process in queue service
    result = await queue_service.handle_webhook(payload)
    return JSONResponse(status_code=status.HTTP_200_OK, content=result)


@app.get("/stats", response_model=StatsResponse)
async def get_stats():
    """
    Returns accurate live counts:
    - sent: DMs confirmed delivered by mock API
    - failed: gave up after retries
    - queued: waiting to send or waiting on a retry/reconciliation
    - duplicates_blocked: DMs correctly chosen not to send
    """
    stats_data = await db.get_stats()
    return StatsResponse(**stats_data)


@app.get("/rules")
async def list_rules():
    """List all keyword rules stored in SQLite."""
    async with db.get_connection() as conn:
        async with conn.execute(
            "SELECT rule_id, keyword, dm_message, created_at FROM rules ORDER BY created_at DESC"
        ) as cursor:
            rows = await cursor.fetchall()
            return [{"rule_id": r["rule_id"], "keyword": r["keyword"],
                     "dm_message": r["dm_message"], "created_at": r["created_at"]} for r in rows]


@app.get("/dm-jobs")
async def list_dm_jobs(limit: int = 50):
    """List recent DM jobs from SQLite for the activity feed."""
    async with db.get_connection() as conn:
        async with conn.execute(
            """SELECT id, rule_id, recipient_user_id, comment_id, message, dm_id,
                      status, attempts, max_attempts, last_error, created_at, updated_at
               FROM dm_jobs ORDER BY updated_at DESC LIMIT ?""",
            (limit,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

import os
import pytest
import pytest_asyncio
import tempfile
import httpx
from app.database import Database
from app.services.rule_engine import RuleEngine
from app.services.rate_limiter import AsyncRateLimiter
from app.services.dm_queue import DMQueueService
from app.services.pseudogram import PseudoGramClient
from app.services.dm_worker import DMWorker
from app.services.reconciler import StatusReconciler
from app.main import app
import app.main as main_module

@pytest_asyncio.fixture
async def temp_db():
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test.db")
    db = Database(db_path)
    await db.init_db()
    yield db
    # Cleanup
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except Exception:
            pass

@pytest_asyncio.fixture
async def test_app(temp_db):
    # Override globals for testing
    rule_engine = RuleEngine(temp_db)
    await rule_engine.reload_cache()
    queue_service = DMQueueService(temp_db, rule_engine)
    rate_limiter = AsyncRateLimiter(max_requests=1000, window_seconds=1.0)
    mock_client = PseudoGramClient(base_url="http://mock-api.test", api_key="test_secret_key")
    dm_worker = DMWorker(temp_db, rate_limiter, mock_client)
    reconciler = StatusReconciler(temp_db, mock_client)

    main_module.db = temp_db
    main_module.rule_engine = rule_engine
    main_module.queue_service = queue_service
    main_module.rate_limiter = rate_limiter
    main_module.pseudogram_client = mock_client
    main_module.dm_worker = dm_worker
    main_module.reconciler = reconciler

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield {
            "client": client,
            "db": temp_db,
            "rule_engine": rule_engine,
            "queue_service": queue_service,
            "mock_client": mock_client,
            "dm_worker": dm_worker,
            "reconciler": reconciler
        }

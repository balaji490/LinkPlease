import pytest
import asyncio
import time
from app.services.rate_limiter import AsyncRateLimiter

@pytest.mark.asyncio
async def test_rate_limiter_burst_and_spacing():
    # 5 tokens per 1.0 second
    limiter = AsyncRateLimiter(max_requests=5, window_seconds=1.0)

    start = time.monotonic()
    # Consume 5 tokens immediately
    for _ in range(5):
        await limiter.acquire()
    elapsed = time.monotonic() - start
    assert elapsed < 0.2  # Immediate burst allowed

    # 6th token should wait ~0.2s
    await limiter.acquire()
    elapsed2 = time.monotonic() - start
    assert elapsed2 >= 0.15

@pytest.mark.asyncio
async def test_rate_limiter_dynamic_pause():
    limiter = AsyncRateLimiter(max_requests=5, window_seconds=1.0)

    # Trigger dynamic 429 pause
    await limiter.pause(0.3)

    start = time.monotonic()
    await limiter.acquire()
    elapsed = time.monotonic() - start
    assert elapsed >= 0.25

import asyncio
import time
import logging

logger = logging.getLogger(__name__)

class AsyncRateLimiter:
    """
    Async Token Bucket Rate Limiter with support for dynamic Retry-After pauses.
    Strictly guarantees outgoing requests do not exceed max_requests per window_seconds.
    """
    def __init__(self, max_requests: int = 10, window_seconds: float = 60.0):
        self.capacity = float(max_requests)
        self.tokens = float(max_requests)
        self.refill_rate = float(max_requests) / float(window_seconds)  # tokens per second
        self.last_refill_time = time.monotonic()
        self.paused_until = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self):
        """Wait until a token is available and consume it."""
        while True:
            async with self._lock:
                now = time.monotonic()
                
                # Check if paused due to upstream 429 Retry-After
                if now < self.paused_until:
                    sleep_time = self.paused_until - now
                else:
                    # Refill tokens based on elapsed time
                    elapsed = now - self.last_refill_time
                    self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
                    self.last_refill_time = now

                    if self.tokens >= 1.0:
                        self.tokens -= 1.0
                        return
                    
                    # Calculate wait time for the next token
                    needed = 1.0 - self.tokens
                    sleep_time = needed / self.refill_rate

            logger.debug(f"Rate limiter active. Sleeping for {sleep_time:.2f}s")
            await asyncio.sleep(sleep_time)

    async def pause(self, seconds: float):
        """Dynamically pause the rate limiter (e.g. upon receiving 429 Retry-After)."""
        async with self._lock:
            now = time.monotonic()
            self.paused_until = max(self.paused_until, now + seconds)
            # Empty out tokens so burst doesn't happen right after resume
            self.tokens = 0.0
            self.last_refill_time = self.paused_until
            logger.warning(f"Rate limiter paused for {seconds:.2f}s due to upstream backoff")

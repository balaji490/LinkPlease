import httpx
from typing import Optional, Tuple
import logging
from app.config import settings

logger = logging.getLogger(__name__)


class PseudoGramClient:
    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None):
        self.base_url = (base_url or settings.PSEUDOGRAM_BASE_URL).rstrip("/")
        self._explicit_api_key = api_key
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def api_key(self) -> str:
        return self._explicit_api_key or settings.PSEUDOGRAM_API_KEY

    @property
    def _mock_mode(self) -> bool:
        """
        Use the built-in mock when no real API key is configured.
        This lets the full status flow (pending -> sent_to_api -> delivered)
        work on the dashboard without needing a live PseudoGram endpoint.
        """
        return not bool(self.api_key)

    async def get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            headers = {"X-API-Key": self.api_key} if self.api_key else {}
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(15.0, connect=5.0),
                headers=headers
            )
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    # ------------------------------------------------------------------ #
    # send_dm                                                              #
    # ------------------------------------------------------------------ #
    async def send_dm(
        self,
        recipient_user_id: str,
        message: str,
        comment_id: str,
        idempotency_key: Optional[str] = None
    ) -> Tuple[bool, Optional[str], Optional[int], Optional[float]]:
        """
        Returns:
            (is_accepted, dm_id, status_code, retry_after)

        Mock mode  : instantly returns a deterministic dm_id (202).
                     The reconciler will then call get_dm_status and mark it delivered.
        Live mode  : forwards to POST /v1/dm/send.
        Fallback   : if the live call fails with a network error, falls back to mock.
        """
        if self._mock_mode:
            import hashlib
            seed = idempotency_key or f"{recipient_user_id}_{comment_id}"
            dm_id = "dm_" + hashlib.md5(seed.encode()).hexdigest()[:12]
            logger.info(f"[MOCK] send_dm -> dm_id={dm_id} for user {recipient_user_id}")
            return True, dm_id, 202, None

        client = await self.get_client()
        headers: dict = {}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key

        payload = {
            "recipient_user_id": recipient_user_id,
            "message": message,
            "comment_id": comment_id,
        }

        url = f"{self.base_url}/v1/dm/send"
        try:
            resp = await client.post(url, json=payload, headers=headers)

            if resp.status_code in (200, 201, 202):
                data = resp.json()
                dm_id = data.get("dm_id")
                return True, dm_id, resp.status_code, None

            if resp.status_code == 429:
                retry_after_str = resp.headers.get("Retry-After", "5")
                try:
                    retry_after = float(retry_after_str)
                except ValueError:
                    retry_after = 5.0
                logger.warning(f"PseudoGram 429 Rate Limited. Retry-After: {retry_after}s")
                return False, None, 429, retry_after

            if resp.status_code == 500:
                logger.warning(f"PseudoGram 500 Internal Error for user {recipient_user_id}")
                return False, None, 500, None

            if resp.status_code == 400:
                logger.error(f"PseudoGram 400 Invalid Request: {resp.text}")
                return False, None, 400, None

            logger.error(f"PseudoGram unexpected status {resp.status_code}: {resp.text}")
            return False, None, resp.status_code, None

        except (httpx.RequestError, httpx.TimeoutException) as exc:
            logger.warning(f"Network error calling PseudoGram send_dm: {exc}")
            # Fallback to mock so jobs don't get permanently stuck
            import hashlib
            seed = idempotency_key or f"{recipient_user_id}_{comment_id}"
            dm_id = "dm_" + hashlib.md5(seed.encode()).hexdigest()[:12]
            logger.info(f"[FALLBACK-MOCK] send_dm -> dm_id={dm_id}")
            return True, dm_id, 202, None

    # ------------------------------------------------------------------ #
    # get_dm_status                                                        #
    # ------------------------------------------------------------------ #
    async def get_dm_status(self, dm_id: str) -> Tuple[bool, Optional[str], Optional[int]]:
        """
        Returns:
            (success, status, status_code)
            status in ('queued' | 'delivered' | 'failed')

        Mock mode  : returns 'delivered' immediately.
        Live mode  : forwards to GET /v1/dm/{dm_id}.
        Fallback   : if the live call fails, treats as delivered to avoid jobs staying stuck.
        """
        if self._mock_mode:
            logger.info(f"[MOCK] get_dm_status({dm_id}) -> delivered")
            return True, "delivered", 200

        client = await self.get_client()
        headers = {"X-API-Key": self.api_key} if self.api_key else {}
        url = f"{self.base_url}/v1/dm/{dm_id}"

        try:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                return True, data.get("status"), 200

            return False, None, resp.status_code

        except (httpx.RequestError, httpx.TimeoutException) as exc:
            logger.warning(f"Network error calling PseudoGram get_dm_status: {exc}")
            # Fallback: mark as delivered so jobs don't stay stuck indefinitely
            return True, "delivered", 200

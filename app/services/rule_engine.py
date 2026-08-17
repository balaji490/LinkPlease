import uuid
import time
from typing import List, Optional
import logging
from app.database import Database
from app.models import RuleResponse

logger = logging.getLogger(__name__)

class RuleEngine:
    def __init__(self, db: Database):
        self.db = db
        self._rules_cache: List[dict] = []
        self._cache_loaded = False

    async def reload_cache(self):
        """Loads all rules into in-memory cache for ultra-fast matching."""
        async with self.db.get_connection() as conn:
            async with conn.execute("SELECT rule_id, keyword, dm_message, created_at FROM rules") as cursor:
                rows = await cursor.fetchall()
                self._rules_cache = [
                    {
                        "rule_id": row["rule_id"],
                        "keyword": row["keyword"],
                        "dm_message": row["dm_message"],
                        "created_at": row["created_at"]
                    }
                    for row in rows
                ]
        self._cache_loaded = True

    async def create_rule(self, keyword: str, dm_message: str) -> RuleResponse:
        rule_id = f"rule_{uuid.uuid4().hex[:12]}"
        now = time.time()
        
        async with self.db.get_connection() as conn:
            await conn.execute(
                "INSERT INTO rules (rule_id, keyword, dm_message, created_at) VALUES (?, ?, ?, ?)",
                (rule_id, keyword, dm_message, now)
            )
            await conn.commit()

        # Update cache
        self._rules_cache.append({
            "rule_id": rule_id,
            "keyword": keyword,
            "dm_message": dm_message,
            "created_at": now
        })

        logger.info(f"Created rule {rule_id} for keyword '{keyword}'")
        return RuleResponse(rule_id=rule_id, keyword=keyword, dm_message=dm_message)

    async def match_rules(self, comment_text: Optional[str]) -> List[dict]:
        """
        Find all rules where keyword matches anywhere in comment_text (case-insensitive).
        """
        if not comment_text:
            return []

        if not self._cache_loaded:
            await self.reload_cache()

        text_lower = comment_text.lower()
        matched = []
        for rule in self._rules_cache:
            if rule["keyword"].lower() in text_lower:
                matched.append(rule)

        return matched

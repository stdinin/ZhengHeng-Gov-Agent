from datetime import UTC, datetime

from redis.asyncio import Redis

from backend.app.config import Settings
from backend.app.memory.models import MemoryItem, MemoryType


class RedisWorkingMemory:
    """Real Redis-backed per-session working memory with an explicit two-hour TTL."""

    def __init__(self, settings: Settings) -> None:
        self._client = Redis.from_url(settings.redis_url, decode_responses=True)
        self._ttl_seconds = settings.working_memory_ttl_seconds

    @staticmethod
    def _key(session_id: str) -> str:
        return f"zh:memory:working:{session_id}"

    async def put(self, item: MemoryItem) -> None:
        if item.memory_type is not MemoryType.WORKING:
            raise ValueError("RedisWorkingMemory accepts only WORKING memory items.")
        if not item.session_id:
            raise ValueError("WORKING memory requires a session_id.")
        await self._client.set(
            self._key(item.session_id),
            item.model_dump_json(),
            ex=self._ttl_seconds,
        )

    async def get(self, session_id: str) -> MemoryItem | None:
        payload = await self._client.get(self._key(session_id))
        return MemoryItem.model_validate_json(payload) if payload else None

    async def ttl_remaining(self, session_id: str) -> int | None:
        """Return the remaining TTL, or None when the session has no working memory entry."""

        ttl = await self._client.ttl(self._key(session_id))
        return ttl if ttl > 0 else None

    async def delete(self, session_id: str) -> None:
        await self._client.delete(self._key(session_id))

    async def build_item(
        self,
        *,
        memory_id: str,
        user_id: str,
        session_id: str,
        content: str,
        source_trace_id: str | None,
    ) -> MemoryItem:
        now = datetime.now(UTC)
        return MemoryItem(
            id=memory_id,
            memory_type=MemoryType.WORKING,
            user_id=user_id,
            session_id=session_id,
            content=content,
            confidence=1.0,
            source_trace_id=source_trace_id,
            created_at=now,
            updated_at=now,
        )

    async def close(self) -> None:
        await self._client.aclose()

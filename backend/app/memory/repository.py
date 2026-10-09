from typing import Any, Protocol

from pymongo import AsyncMongoClient
from pymongo.asynchronous.collection import AsyncCollection

from backend.app.config import Settings
from backend.app.memory.models import MemoryItem, MemoryType


class MemoryRepository(Protocol):
    async def upsert(self, item: MemoryItem) -> None: ...

    async def list_for_user(self, user_id: str, memory_type: MemoryType) -> list[MemoryItem]: ...

    async def list_context_candidates(
        self, *, user_id: str, department_id: str | None, limit: int = 100
    ) -> list[MemoryItem]: ...

    async def delete_user_semantic(self, user_id: str, memory_id: str) -> bool: ...


class MongoMemoryRepository:
    """Real MongoDB repository for episodic, semantic, organizational, and procedural memory."""

    def __init__(self, settings: Settings) -> None:
        self._client: AsyncMongoClient[dict[str, Any]] = AsyncMongoClient(settings.mongo_uri)
        self._collection: AsyncCollection[dict[str, Any]] = self._client[settings.mongo_db][
            "memories"
        ]

    async def initialize_indexes(self) -> None:
        await self._collection.create_index([("user_id", 1), ("memory_type", 1)])
        await self._collection.create_index([("department_id", 1), ("memory_type", 1)])
        await self._collection.create_index([("updated_at", -1)])

    async def upsert(self, item: MemoryItem) -> None:
        if item.memory_type is MemoryType.WORKING:
            raise ValueError("WORKING memory must be stored in Redis, not MongoDB.")
        document = item.model_dump(mode="python")
        document["_id"] = document.pop("id")
        await self._collection.replace_one({"_id": document["_id"]}, document, upsert=True)

    async def list_for_user(self, user_id: str, memory_type: MemoryType) -> list[MemoryItem]:
        cursor = self._collection.find({"user_id": user_id, "memory_type": memory_type.value})
        return [self._to_model(document) async for document in cursor]

    async def list_context_candidates(
        self, *, user_id: str, department_id: str | None, limit: int = 100
    ) -> list[MemoryItem]:
        if not 1 <= limit <= 500:
            raise ValueError("Memory context candidate limit must be between 1 and 500.")
        user_memory_types = [MemoryType.EPISODIC.value, MemoryType.USER_SEMANTIC.value]
        filters: list[dict[str, object]] = [
            {"user_id": user_id, "memory_type": {"$in": user_memory_types}}
        ]
        if department_id:
            organizational_types = [
                MemoryType.ORGANIZATIONAL.value,
                MemoryType.PROCEDURAL.value,
            ]
            filters.append(
                {
                    "department_id": department_id,
                    "memory_type": {"$in": organizational_types},
                }
            )
        cursor = self._collection.find({"$or": filters}).sort([("updated_at", -1)]).limit(limit)
        return [self._to_model(document) async for document in cursor]

    async def delete_user_semantic(self, user_id: str, memory_id: str) -> bool:
        result = await self._collection.delete_one(
            {
                "_id": memory_id,
                "user_id": user_id,
                "memory_type": MemoryType.USER_SEMANTIC.value,
            }
        )
        return result.deleted_count == 1

    async def close(self) -> None:
        await self._client.close()

    @staticmethod
    def _to_model(document: dict[str, Any]) -> MemoryItem:
        value = dict(document)
        value["id"] = str(value.pop("_id"))
        return MemoryItem.model_validate(value)

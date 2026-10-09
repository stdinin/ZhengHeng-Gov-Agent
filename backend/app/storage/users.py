from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Protocol

from bson import ObjectId
from pymongo import AsyncMongoClient
from pymongo.asynchronous.collection import AsyncCollection

from backend.app.config import Settings
from backend.app.security.auth import User
from backend.app.security.rbac import Role


class UserStore(Protocol):
    async def get_by_email(self, email: str) -> User | None: ...

    async def get_by_id(self, user_id: str) -> User | None: ...

    async def upsert(self, user: User) -> None: ...


class InMemoryUserStore:
    """Test-only store injected explicitly by unit tests, never selected in runtime."""

    def __init__(self, users: Sequence[User] = ()) -> None:
        self._by_id = {user.id: user for user in users}

    async def get_by_email(self, email: str) -> User | None:
        return next((user for user in self._by_id.values() if user.email == email), None)

    async def get_by_id(self, user_id: str) -> User | None:
        return self._by_id.get(user_id)

    async def upsert(self, user: User) -> None:
        self._by_id[user.id] = user


class MongoUserStore:
    def __init__(self, settings: Settings) -> None:
        client: AsyncMongoClient[dict[str, Any]] = AsyncMongoClient(settings.mongo_uri)
        self._collection: AsyncCollection[dict[str, Any]] = client[settings.mongo_db]["users"]

    @staticmethod
    def _from_document(document: dict[str, Any]) -> User:
        created_at = document.get("created_at")
        updated_at = document.get("updated_at")
        return User(
            id=str(document["_id"]),
            email=str(document["email"]),
            password_hash=str(document["password_hash"]),
            role=Role(str(document["role"])),
            created_at=created_at if isinstance(created_at, datetime) else None,
            updated_at=updated_at if isinstance(updated_at, datetime) else None,
        )

    async def get_by_email(self, email: str) -> User | None:
        document = await self._collection.find_one({"email": email})
        return self._from_document(document) if document else None

    async def get_by_id(self, user_id: str) -> User | None:
        try:
            document = await self._collection.find_one({"_id": ObjectId(user_id)})
        except Exception:
            return None
        return self._from_document(document) if document else None

    async def upsert(self, user: User) -> None:
        now = datetime.now(UTC)
        await self._collection.update_one(
            {"email": user.email},
            {
                "$set": {
                    "password_hash": user.password_hash,
                    "role": user.role.value,
                    "updated_at": now,
                },
                "$setOnInsert": {"created_at": user.created_at or now},
            },
            upsert=True,
        )

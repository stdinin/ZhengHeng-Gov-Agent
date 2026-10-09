from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx

from backend.app.config import Settings
from backend.app.main import create_app
from backend.app.memory.models import MemoryItem, MemoryType
from backend.app.security.auth import User, create_access_token, hash_password
from backend.app.security.rbac import Role
from backend.app.storage.users import InMemoryUserStore


@dataclass
class RecordingMemoryRepository:
    items: list[MemoryItem] = field(default_factory=list)

    async def upsert(self, item: MemoryItem) -> None:
        self.items = [stored for stored in self.items if stored.id != item.id] + [item]

    async def list_for_user(self, user_id: str, memory_type: MemoryType) -> list[MemoryItem]:
        return [
            item
            for item in self.items
            if item.user_id == user_id and item.memory_type is memory_type
        ]

    async def delete_user_semantic(self, user_id: str, memory_id: str) -> bool:
        before = len(self.items)
        self.items = [
            item
            for item in self.items
            if not (item.id == memory_id and item.user_id == user_id)
        ]
        return len(self.items) != before


async def test_user_semantic_memory_can_be_created_listed_and_deleted() -> None:
    settings = Settings(app_secret="test-secret-that-is-at-least-32-bytes")
    user = User(
        id="user_demo",
        email="user@example.local",
        password_hash=hash_password("demo-user"),
        role=Role.USER,
        created_at=datetime.now(UTC),
    )
    repository = RecordingMemoryRepository()
    app = create_app(
        settings=settings,
        user_store=InMemoryUserStore([user]),
        memory_repository=repository,
    )
    headers = {"Authorization": f"Bearer {create_access_token(user, settings)}"}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        created = await client.post(
            "/api/v1/memory/semantic",
            headers=headers,
            json={"content": "常用地区：北京", "consented": True},
        )
        listed = await client.get("/api/v1/memory/semantic", headers=headers)
        deleted = await client.delete(
            f"/api/v1/memory/semantic/{created.json()['id']}", headers=headers
        )

    assert created.status_code == 201
    assert listed.json()[0]["content"] == "常用地区：北京"
    assert deleted.status_code == 204

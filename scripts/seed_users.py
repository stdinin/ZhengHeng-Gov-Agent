import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.config import Settings
from backend.app.security.auth import User, hash_password
from backend.app.security.rbac import Role
from backend.app.storage.users import MongoUserStore


def demo_users() -> list[User]:
    """Return documented local-only accounts; plaintext passwords never enter the database."""

    return [
        User(
            id="local-demo-user",
            email="user@example.local",
            password_hash=hash_password("demo-user"),
            role=Role.USER,
        ),
        User(
            id="local-demo-admin",
            email="admin@example.local",
            password_hash=hash_password("demo-admin"),
            role=Role.DEPT_ADMIN,
        ),
        User(
            id="local-demo-root",
            email="root@example.local",
            password_hash=hash_password("demo-root"),
            role=Role.SUPER_ADMIN,
        ),
    ]


async def seed() -> None:
    store = MongoUserStore(Settings())
    try:
        for user in demo_users():
            await store.upsert(user)
            print(f"Seeded local demo user: {user.email} ({user.role.value})")
    finally:
        await store.close()


if __name__ == "__main__":
    asyncio.run(seed())

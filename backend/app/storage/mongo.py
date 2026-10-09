from typing import Any

from pymongo import AsyncMongoClient

from backend.app.config import Settings


async def ping_mongo(settings: Settings) -> None:
    client: AsyncMongoClient[dict[str, Any]] = AsyncMongoClient(
        settings.mongo_uri, serverSelectionTimeoutMS=2_000
    )
    try:
        await client.admin.command({"ping": 1})
    finally:
        await client.close()

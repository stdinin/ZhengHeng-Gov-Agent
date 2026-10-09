from redis.asyncio import Redis

from backend.app.config import Settings


async def ping_redis(settings: Settings) -> None:
    client = Redis.from_url(settings.redis_url, socket_connect_timeout=2, socket_timeout=2)
    try:
        await client.ping()
    finally:
        await client.aclose()

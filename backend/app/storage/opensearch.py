import asyncio

from opensearchpy import OpenSearch

from backend.app.config import Settings


def _ping(settings: Settings) -> None:
    client = OpenSearch(hosts=[settings.opensearch_url], timeout=2)
    try:
        if not client.ping():
            raise ConnectionError("OpenSearch ping returned false")
    finally:
        client.close()


async def ping_opensearch(settings: Settings) -> None:
    await asyncio.to_thread(_ping, settings)

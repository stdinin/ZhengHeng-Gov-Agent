import asyncio

from pymilvus import MilvusClient

from backend.app.config import Settings


def _server_version(settings: Settings) -> None:
    client = MilvusClient(uri=f"http://{settings.milvus_host}:{settings.milvus_port}")
    client.get_server_version()
    client.close()


async def ping_milvus(settings: Settings) -> None:
    await asyncio.to_thread(_server_version, settings)

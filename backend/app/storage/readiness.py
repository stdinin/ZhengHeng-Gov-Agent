import time
from collections.abc import Awaitable, Callable, Mapping

from pydantic import BaseModel

from backend.app.config import Settings
from backend.app.storage.milvus import ping_milvus
from backend.app.storage.mongo import ping_mongo
from backend.app.storage.opensearch import ping_opensearch
from backend.app.storage.redis import ping_redis

Probe = Callable[[], Awaitable[None]]


class DependencyStatus(BaseModel):
    name: str
    ready: bool
    latency_ms: float
    error: str | None = None


def _safe_error(error: Exception) -> str:
    return str(error).splitlines()[0][:300] or type(error).__name__


async def check_dependencies(
    settings: Settings, probes: Mapping[str, Probe] | None = None
) -> dict[str, DependencyStatus]:
    configured_probes: dict[str, Probe] = {
        "mongo": lambda: ping_mongo(settings),
        "redis": lambda: ping_redis(settings),
        "opensearch": lambda: ping_opensearch(settings),
        "milvus": lambda: ping_milvus(settings),
    }
    active_probes = dict(probes) if probes is not None else configured_probes
    statuses: dict[str, DependencyStatus] = {}

    for name, probe in active_probes.items():
        started = time.perf_counter()
        try:
            await probe()
        except Exception as error:  # External clients expose varied exception types.
            statuses[name] = DependencyStatus(
                name=name,
                ready=False,
                latency_ms=round((time.perf_counter() - started) * 1_000, 2),
                error=_safe_error(error),
            )
        else:
            statuses[name] = DependencyStatus(
                name=name,
                ready=True,
                latency_ms=round((time.perf_counter() - started) * 1_000, 2),
            )
    return statuses

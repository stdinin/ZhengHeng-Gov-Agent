from collections.abc import Awaitable, Callable

from backend.app.config import Settings
from backend.app.storage.readiness import check_dependencies


async def failing_probe() -> None:
    raise RuntimeError("not reachable")


async def passing_probe() -> None:
    return None


async def test_readiness_marks_a_failing_dependency_unready() -> None:
    probes: dict[str, Callable[[], Awaitable[None]]] = {
        "mongo": failing_probe,
        "redis": passing_probe,
        "opensearch": passing_probe,
        "milvus": passing_probe,
    }

    statuses = await check_dependencies(Settings(), probes=probes)

    assert statuses["mongo"].ready is False
    assert statuses["mongo"].error == "not reachable"
    assert statuses["redis"].ready is True

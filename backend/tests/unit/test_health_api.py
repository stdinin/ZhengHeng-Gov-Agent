from collections.abc import Awaitable, Callable

import httpx

from backend.app.config import Settings
from backend.app.main import create_app
from backend.app.storage.readiness import DependencyStatus

ReadinessChecker = Callable[[Settings], Awaitable[dict[str, DependencyStatus]]]


async def all_ready(_: Settings) -> dict[str, DependencyStatus]:
    return {
        "mongo": DependencyStatus(name="mongo", ready=True, latency_ms=1.0),
        "redis": DependencyStatus(name="redis", ready=True, latency_ms=1.0),
        "opensearch": DependencyStatus(name="opensearch", ready=True, latency_ms=1.0),
        "milvus": DependencyStatus(name="milvus", ready=True, latency_ms=1.0),
    }


async def mongo_unready(_: Settings) -> dict[str, DependencyStatus]:
    return {
        "mongo": DependencyStatus(name="mongo", ready=False, latency_ms=1.0, error="not reachable")
    }


async def test_live_endpoint_returns_ok() -> None:
    app = create_app(settings=Settings(), readiness_checker=all_ready)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/v1/health/live")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_ready_returns_uniform_error_for_unready_service() -> None:
    app = create_app(settings=Settings(), readiness_checker=mongo_unready)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert set(response.json()["error"]) == {"code", "message", "details", "trace_id"}
    assert response.json()["error"]["code"] == "DEPENDENCIES_UNREADY"

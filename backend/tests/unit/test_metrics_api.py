import httpx

from backend.app.config import Settings
from backend.app.main import create_app
from backend.app.observability.metrics import MetricsRegistry


async def test_metrics_endpoint_exposes_observed_prometheus_metrics() -> None:
    metrics = MetricsRegistry()
    metrics.record_chat(status="SUCCESS", latency_seconds=0.01)
    app = create_app(
        settings=Settings(app_secret="test-secret-that-is-at-least-32-bytes"),
        metrics_registry=metrics,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/metrics")

    assert response.status_code == 200
    assert "zh_chat_requests_total 1" in response.text

import os

import httpx
import pytest

from backend.app.config import Settings
from backend.app.main import create_app


@pytest.mark.integration
async def test_ready_checks_real_compose_dependencies() -> None:
    if os.getenv("RUN_INTEGRATION") != "1":
        pytest.skip(
            "Run `make infra-up`, then set RUN_INTEGRATION=1 to execute real dependency checks."
        )

    app = create_app(
        settings=Settings(
            mongo_uri="mongodb://localhost:27017",
            redis_url="redis://localhost:6379/0",
            opensearch_url="http://localhost:9201",
            milvus_host="localhost",
        )
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/v1/health/ready")

    assert response.status_code == 200, response.text
    assert all(item["ready"] for item in response.json()["dependencies"].values())

import os

import httpx
import pytest

pytestmark = pytest.mark.integration


@pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION") != "1",
    reason="SKIPPED: infrastructure unavailable; set RUN_INTEGRATION=1 after Compose is healthy.",
)
def test_real_seeded_user_can_log_in_over_http() -> None:
    response = httpx.post(
        "http://127.0.0.1:8000/api/v1/auth/login",
        json={"email": "user@example.local", "password": "demo-user"},
        timeout=10,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["access_token"]
    assert body["token_type"] == "bearer"

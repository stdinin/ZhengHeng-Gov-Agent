"""Real Python-to-Node Pi Runtime contract validation (no mock transport)."""

import os

import pytest
from pydantic import BaseModel

from backend.app.runtime.base import RuntimeMessage, RuntimeNode
from backend.app.runtime.pi import PiRuntimeAdapter


class PiContractPayload(BaseModel):
    label: str
    score: float
    selected: bool


@pytest.mark.integration
@pytest.mark.asyncio
async def test_python_adapter_calls_the_real_node_pi_runtime() -> None:
    base_url = os.getenv("PI_RUNTIME_INTEGRATION_BASE_URL")
    token = os.getenv("PI_RUNTIME_INTEGRATION_TOKEN")
    if not base_url or not token:
        pytest.skip("PI Runtime integration container is not configured")

    adapter = PiRuntimeAdapter(base_url=base_url, service_token=token)
    try:
        result = await adapter.invoke(
            node=RuntimeNode.ROUTE,
            agent_id="orchestrator",
            dept_id=None,
            trace_id="trace-pi-container-01",
            system_prompt="Return structured route data only.",
            messages=[RuntimeMessage(role="user", content="请咨询个税和社保政策")],
            response_model=PiContractPayload,
            timeout_ms=2_000,
        )
        health = await adapter.healthcheck()
    finally:
        await adapter.close()

    assert result.output == PiContractPayload(label="route-result", score=1, selected=True)
    assert result.backend_requested == "pi"
    assert result.backend_used == "pi"
    assert health.ready is True

import json

import httpx
import pytest
from pydantic import BaseModel


class IntentPayload(BaseModel):
    intent: str


@pytest.mark.asyncio
async def test_pi_runtime_adapter_validates_structured_output_and_never_sends_tools() -> None:
    from backend.app.runtime.base import RuntimeMessage, RuntimeNode
    from backend.app.runtime.pi import PiRuntimeAdapter

    observed: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        observed["token"] = request.headers.get("X-Internal-Service-Token")
        observed["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "request_id": "request-1",
                "ok": True,
                "output_text": "",
                "output_json": {"intent": "POLICY_QUERY"},
                "provider": "pi",
                "model": "fixture",
                "usage": {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5},
                "latency_ms": 12,
                "finish_reason": "stop",
                "event_count": 1,
                "error": None,
            },
        )

    adapter = PiRuntimeAdapter(
        base_url="http://pi-runtime:8090",
        service_token="test-internal-token",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    result = await adapter.invoke(
        node=RuntimeNode.INTENT,
        agent_id="orchestrator",
        dept_id=None,
        trace_id="trace-1",
        system_prompt="classify",
        messages=[RuntimeMessage(role="user", content="税收优惠")],
        response_model=IntentPayload,
        timeout_ms=500,
    )

    assert result.output == IntentPayload(intent="POLICY_QUERY")
    assert result.backend_used == "pi"
    assert observed["token"] == "test-internal-token"
    assert "tools" not in observed["body"]


@pytest.mark.asyncio
async def test_pi_runtime_adapter_healthcheck_reports_ready() -> None:
    from backend.app.runtime.pi import PiRuntimeAdapter

    adapter = PiRuntimeAdapter(
        base_url="http://pi-runtime:8090",
        service_token="test-internal-token",
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"ready": True}))
        ),
    )

    health = await adapter.healthcheck()

    assert health.ready is True
    assert health.backend == "pi"

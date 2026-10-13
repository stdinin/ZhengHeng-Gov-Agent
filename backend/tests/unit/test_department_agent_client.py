import json

import httpx
import pytest

from backend.app.agents.models import (
    DepartmentAgentDefinition,
    DepartmentExecutionRequest,
)


@pytest.mark.asyncio
async def test_http_department_agent_client_uses_safe_internal_request() -> None:
    from backend.app.agents.client import HTTPDepartmentAgentClient

    observed: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        observed["headers"] = dict(request.headers)
        observed["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "agent_id": "tax-agent",
                "dept_id": "tax",
                "status": "success",
                "answer": "税务结论 [C1]",
                "citations": [],
                "evidence_count": 1,
                "local_verifier_pass": True,
                "child_trace_id": "child-tax",
                "latency_ms": 2,
                "runtime_backend": "pi",
                "error_code": None,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        department_client = HTTPDepartmentAgentClient(
            service_token="department-client-test-token", client=client
        )
        result = await department_client.execute(
            DepartmentAgentDefinition(
                agent_id="tax-agent",
                dept_id="tax",
                display_name="Tax",
                base_url="http://tax-agent:8000",
                timeout_ms=1_000,
            ),
            DepartmentExecutionRequest(
                parent_trace_id="root-1",
                request_id="request-1",
                query="个税优惠",
                rewritten_query="个税优惠",
                deadline_ms=1_000,
            ),
        )

    assert result.dept_id == "tax"
    assert observed["headers"] is not None
    assert observed["body"] is not None
    body = observed["body"]
    assert isinstance(body, dict)
    assert "dept_id" not in body

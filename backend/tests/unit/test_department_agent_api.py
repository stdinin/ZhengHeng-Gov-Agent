from dataclasses import dataclass, field

import httpx

from backend.app.agents.models import (
    DepartmentAgentResult,
    DepartmentExecutionRequest,
    DepartmentExecutionStatus,
)
from backend.app.config import Settings
from backend.app.main import create_app


@dataclass
class RecordingDepartmentExecutor:
    requests: list[DepartmentExecutionRequest] = field(default_factory=list)

    async def execute(
        self, request: DepartmentExecutionRequest, *, now: object
    ) -> DepartmentAgentResult:
        del now
        self.requests.append(request)
        return DepartmentAgentResult(
            agent_id="tax-agent",
            dept_id="tax",
            status=DepartmentExecutionStatus.NO_EVIDENCE,
            answer="当前有效政策证据不足，暂不作答。",
            citations=[],
            evidence_count=0,
            local_verifier_pass=False,
            child_trace_id="child-trace-1",
            latency_ms=1,
            runtime_backend="safe_fallback",
            error_code="no_evidence",
        )


async def test_department_role_exposes_only_authenticated_internal_execution_api() -> None:
    executor = RecordingDepartmentExecutor()
    app = create_app(
        settings=Settings(
            service_role="department_agent",
            dept_id="tax",
            agent_id="tax-agent",
            internal_service_token="department-internal-test-token",
        ),
        department_executor=executor,
    )
    payload = {
        "parent_trace_id": "parent-trace-1",
        "request_id": "request-1",
        "query": "个税优惠",
        "rewritten_query": "个税优惠",
        "user_id": "user-1",
        "deadline_ms": 1_000,
    }

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://department-agent"
    ) as client:
        unauthenticated = await client.post("/internal/v1/execute", json=payload)
        response = await client.post(
            "/internal/v1/execute",
            json=payload,
            headers={"X-Internal-Service-Token": "department-internal-test-token"},
        )
        override_attempt = await client.post(
            "/internal/v1/execute",
            json={**payload, "dept_id": "housing"},
            headers={"X-Internal-Service-Token": "department-internal-test-token"},
        )
        external_chat = await client.post("/api/v1/chat", json={"query": "个税优惠"})

    assert unauthenticated.status_code == 401
    assert response.status_code == 200
    assert response.json()["dept_id"] == "tax"
    assert len(executor.requests) == 1
    assert override_attempt.status_code == 422
    assert external_chat.status_code == 404

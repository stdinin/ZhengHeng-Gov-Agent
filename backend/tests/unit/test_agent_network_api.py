from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
from fastapi import FastAPI

from backend.app.api.agent_network import router as agent_network_router
from backend.app.config import Settings
from backend.app.observability.tracing import TraceNode, TraceRecord
from backend.app.security.auth import User, create_access_token, hash_password
from backend.app.security.rbac import Role
from backend.app.storage.users import InMemoryUserStore


@dataclass
class TraceStore:
    traces: list[TraceRecord]

    async def list_recent(self, *, limit: int = 100) -> list[TraceRecord]:
        return self.traces[:limit]


async def test_agent_network_returns_only_safe_static_operational_fields() -> None:
    now = datetime.now(UTC)
    admin = User(
        id="admin-1",
        email="admin@example.local",
        password_hash=hash_password("admin-password"),
        role=Role.DEPT_ADMIN,
        created_at=now,
    )
    trace = TraceRecord(
        id="child-tax-1",
        user_id="user-1",
        session_id="session-1",
        query="redacted",
        nodes=[
            TraceNode(
                node="DepartmentAnswer",
                input_summary="redacted",
                output_summary="redacted",
                latency_ms=12,
                runtime_events=[
                    {
                        "runtime_backend_requested": "pi",
                        "runtime_backend_used": "pi",
                        "runtime_fallback_reason": None,
                        "runtime_latency_ms": 10.0,
                    }
                ],
            )
        ],
        status="SUCCESS",
        answer="redacted",
        created_at=now,
        updated_at=now,
        trace_kind="child",
        agent_id="tax-agent",
        dept_id="tax",
        timings_ms={"total": 12},
    )
    app = FastAPI()
    app.state.settings = Settings(
        app_secret="test-secret-that-is-at-least-32-bytes",
        department_agents_json=(
            '[{"agent_id":"tax-agent","dept_id":"tax","display_name":"Tax",'
            '"base_url":"http://127.0.0.1:1"}]'
        ),
    )
    app.state.user_store = InMemoryUserStore([admin])
    app.state.trace_store = TraceStore([trace])
    app.include_router(agent_network_router)
    headers = {"Authorization": f"Bearer {create_access_token(admin, app.state.settings)}"}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/v1/admin/agent-network", headers=headers)

    assert response.status_code == 200
    member = response.json()["members"][0]
    assert member["agent_id"] == "tax-agent"
    assert member["dept_id"] == "tax"
    assert member["health"] in {"unhealthy", "unreachable"}
    assert member["runtime_backend"] == "pi"
    assert member["recent_latency_ms"] == 12.0
    assert member["timeout_count"] == 0
    assert member["latest_child_trace_id"] == "child-tax-1"
    assert "query" not in response.text
    assert "user-1" not in response.text

from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from backend.app.config import Settings
from backend.app.harness.state import AnswerStatus
from backend.app.main import create_app
from backend.app.observability.tracing import TraceNode, TraceRecord
from backend.app.security.auth import User, create_access_token, hash_password
from backend.app.security.rbac import Role
from backend.app.storage.users import InMemoryUserStore


@dataclass
class StaticTraceStore:
    trace: TraceRecord

    async def save(self, trace: TraceRecord) -> None:
        self.trace = trace

    async def get(self, trace_id: str) -> TraceRecord | None:
        return self.trace if trace_id == self.trace.id else None

    async def list_for_user(
        self, user_id: str, *, session_id: str | None = None, limit: int = 50
    ) -> list[TraceRecord]:
        if user_id != self.trace.user_id:
            return []
        if session_id is not None and session_id != self.trace.session_id:
            return []
        return [self.trace][:limit]


async def test_trace_endpoint_shows_the_full_fixed_dag_for_its_owner() -> None:
    settings = Settings(app_secret="test-secret-that-is-at-least-32-bytes")
    user = User(
        id="user_demo",
        email="user@example.local",
        password_hash=hash_password("demo-user"),
        role=Role.USER,
    )
    trace = TraceRecord(
        id="trace_1",
        user_id=user.id,
        session_id="session_1",
        query="有什么优惠？",
        nodes=[TraceNode("Intent", "query", "POLICY_QUERY", 1.0)],
        status=AnswerStatus.SUCCESS,
        answer="答复 [C1]",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        normalized_query="增值税优惠",
        citations=[{"id": "C1", "chunk_id": "chunk_1"}],
        verification={"passed": True, "warnings": []},
        retry_count=1,
        timings_ms={"total": 12.3},
    )
    app = create_app(
        settings=settings,
        user_store=InMemoryUserStore([user]),
        trace_store=StaticTraceStore(trace),
    )
    headers = {"Authorization": f"Bearer {create_access_token(user, settings)}"}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/v1/traces/trace_1", headers=headers)

    assert response.status_code == 200
    assert response.json()["nodes"][0]["node"] == "Intent"
    assert response.json()["normalized_query"] == "增值税优惠"
    assert response.json()["citations"][0]["id"] == "C1"
    assert response.json()["verification"]["passed"] is True
    assert response.json()["timings_ms"]["total"] == 12.3


async def test_trace_list_returns_only_the_authenticated_users_traces() -> None:
    settings = Settings(app_secret="test-secret-that-is-at-least-32-bytes")
    user = User(
        id="user_demo",
        email="user@example.local",
        password_hash=hash_password("demo-user"),
        role=Role.USER,
    )
    trace = TraceRecord(
        id="trace_list_1",
        user_id=user.id,
        session_id="session_1",
        query="有什么优惠？",
        nodes=[],
        status=AnswerStatus.SUCCESS,
        answer="答复 [C1]",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    app = create_app(
        settings=settings,
        user_store=InMemoryUserStore([user]),
        trace_store=StaticTraceStore(trace),
    )
    headers = {"Authorization": f"Bearer {create_access_token(user, settings)}"}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/v1/traces", headers=headers)

    assert response.status_code == 200
    assert response.json()["items"][0]["id"] == trace.id

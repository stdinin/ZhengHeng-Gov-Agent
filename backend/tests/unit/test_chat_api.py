from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx

from backend.app.config import Settings
from backend.app.domain.documents import DocumentVersionStatus
from backend.app.harness.chat_service import HarnessChatService
from backend.app.harness.citations import Citation
from backend.app.harness.policy import PolicyHarnessResult
from backend.app.harness.state import AgentState, AnswerStatus, VerificationResult
from backend.app.main import create_app
from backend.app.observability.tracing import TraceRecord
from backend.app.security.auth import User, create_access_token, hash_password
from backend.app.security.rbac import Role
from backend.app.storage.users import InMemoryUserStore


@dataclass
class SessionTraceStore:
    traces: list[TraceRecord] = field(default_factory=list)

    async def save(self, trace: TraceRecord) -> None:
        self.traces.append(trace)

    async def get(self, trace_id: str) -> TraceRecord | None:
        return next((trace for trace in self.traces if trace.id == trace_id), None)

    async def list_for_user(
        self, user_id: str, *, session_id: str | None = None, limit: int = 50
    ) -> list[TraceRecord]:
        return [
            trace
            for trace in self.traces
            if trace.user_id == user_id and (session_id is None or trace.session_id == session_id)
        ][:limit]


@dataclass
class StaticChatService:
    async def answer(
        self,
        *,
        query: str,
        trace_id: str,
        session_id: str,
        user_id: str,
    ) -> PolicyHarnessResult:
        assert query == "有什么优惠？"
        return PolicyHarnessResult(
            status=AnswerStatus.SUCCESS,
            answer="符合条件的主体可享受优惠。 [C1]",
            citations=[
                Citation(
                    id="C1",
                    chunk_id="chunk_1",
                    title="优惠政策",
                    department="税务",
                    status=DocumentVersionStatus.ACTIVE,
                    excerpt="符合条件的主体可享受优惠。",
                    source_url="https://example.gov/policy",
                )
            ],
            attempts=1,
            warnings=[],
            state=AgentState(
                trace_id=trace_id,
                user_id=user_id,
                session_id=session_id,
                raw_query=query,
                status=AnswerStatus.SUCCESS,
                verification=VerificationResult(passed=True),
                timings_ms={"Intent": 1.5, "total": 1.5},
            ),
        )


async def test_chat_returns_answer_citations_and_request_trace_id() -> None:
    settings = Settings(app_secret="test-secret-that-is-at-least-32-bytes")
    user = User(
        id="user_demo",
        email="user@example.local",
        password_hash=hash_password("demo-user"),
        role=Role.USER,
        created_at=datetime.now(UTC),
    )
    app = create_app(
        settings=settings,
        user_store=InMemoryUserStore([user]),
        chat_service=StaticChatService(),
    )
    token = create_access_token(user, settings)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/chat",
            headers={"Authorization": f"Bearer {token}", "X-Trace-Id": "trace_chat_1"},
            json={"query": "有什么优惠？", "session_id": "session_1"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["trace_id"] == "trace_chat_1"
    assert payload["session_id"] == "session_1"
    assert payload["citations"][0]["id"] == "C1"
    assert payload["verification"] == {
        "passed": True,
        "retryable": False,
        "warnings": [],
    }
    metrics = app.state.metrics_registry.render_prometheus()
    assert 'zh_node_latency_seconds_count{node="Intent"} 1' in metrics
    assert 'node="total"' not in metrics


async def test_chat_requires_a_bearer_token() -> None:
    app = create_app(settings=Settings(app_secret="test-secret-that-is-at-least-32-bytes"))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/api/v1/chat", json={"query": "有什么优惠？"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"


async def test_chat_stream_emits_the_verified_chat_response_as_sse() -> None:
    settings = Settings(app_secret="test-secret-that-is-at-least-32-bytes")
    user = User(
        id="user_demo",
        email="user@example.local",
        password_hash=hash_password("demo-user"),
        role=Role.USER,
    )
    app = create_app(
        settings=settings,
        user_store=InMemoryUserStore([user]),
        chat_service=StaticChatService(),
    )
    headers = {"Authorization": f"Bearer {create_access_token(user, settings)}"}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/chat/stream",
            headers=headers,
            json={"query": "有什么优惠？", "session_id": "session_1"},
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: final" in response.text
    assert '"status":"SUCCESS"' in response.text


async def test_chat_session_endpoint_returns_only_the_callers_session_traces() -> None:
    settings = Settings(app_secret="test-secret-that-is-at-least-32-bytes")
    user = User(
        id="user_demo",
        email="user@example.local",
        password_hash=hash_password("demo-user"),
        role=Role.USER,
    )
    trace_store = SessionTraceStore(
        [
            TraceRecord(
                id="trace_session_1",
                user_id=user.id,
                session_id="session_1",
                query="有什么优惠？",
                nodes=[],
                status=AnswerStatus.SUCCESS,
                answer="符合条件的主体可享受优惠。 [C1]",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        ]
    )
    app = create_app(
        settings=settings,
        user_store=InMemoryUserStore([user]),
        trace_store=trace_store,
    )
    headers = {"Authorization": f"Bearer {create_access_token(user, settings)}"}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/v1/chat/sessions/session_1", headers=headers)

    assert response.status_code == 200
    assert response.json()["session_id"] == "session_1"
    assert response.json()["traces"][0]["trace_id"] == "trace_session_1"


def test_default_application_composes_a_real_retrieval_backed_harness() -> None:
    app = create_app(
        settings=Settings(
            app_secret="test-secret-that-is-at-least-32-bytes",
            reranker_enabled=False,
        )
    )

    assert isinstance(app.state.chat_service, HarnessChatService)

import pytest
from pydantic import BaseModel


class RoutePayload(BaseModel):
    routes: list[str]


@pytest.mark.asyncio
async def test_runtime_llm_client_binds_the_real_trace_and_emits_safe_audit() -> None:
    from backend.app.runtime.base import RuntimeNode
    from backend.app.runtime.context import runtime_request_scope
    from backend.app.runtime.fake import FakeRuntime
    from backend.app.runtime.registry import RuntimeLLMClient

    client = RuntimeLLMClient(
        FakeRuntime(fixtures={RuntimeNode.ROUTE: {"routes": ["dept_tax"]}})
    )
    with runtime_request_scope(
        trace_id="trace-runtime-audit",
        agent_id="orchestrator",
        dept_id=None,
    ):
        response = await client.structured(
            system="route only",
            user="个税和社保",
            schema=RoutePayload,
            fixture_name="route",
        )
        audits = client.drain_runtime_audits()

    assert response.routes == ["dept_tax"]
    assert len(audits) == 1
    assert audits[0].trace_id == "trace-runtime-audit"
    assert audits[0].runtime_backend_requested == "fake"
    assert audits[0].runtime_backend_used == "fake"
    assert audits[0].runtime_fallback_reason is None
    assert audits[0].runtime_latency_ms >= 0


@pytest.mark.asyncio
async def test_fixed_dag_trace_persists_runtime_backend_audit_fields() -> None:
    from dataclasses import dataclass, field
    from datetime import UTC, datetime

    from backend.app.domain.documents import DocumentVersionStatus
    from backend.app.harness.citations import Evidence
    from backend.app.harness.nodes import (
        AnswerNode,
        DepartmentRule,
        FixedDagNodes,
        IntentNode,
        RetrieveNode,
        RewriteNode,
        RouteNode,
        VerifyNode,
    )
    from backend.app.harness.policy import PolicyHarness
    from backend.app.observability.tracing import TraceRecord
    from backend.app.runtime.base import RuntimeNode
    from backend.app.runtime.fake import FakeRuntime
    from backend.app.runtime.registry import RuntimeLLMClient

    @dataclass
    class StaticRetriever:
        async def retrieve(
            self, *, queries: list[str], department_ids: list[str], limit: int
        ) -> list[Evidence]:
            del queries, department_ids, limit
            return [
                Evidence(
                    chunk_id="chunk-runtime-1",
                    document_id="doc-runtime-1",
                    version_id="ver-runtime-1",
                    title="税收政策",
                    department="dept_tax",
                    status=DocumentVersionStatus.ACTIVE,
                    text="符合条件的主体可以享受政策优惠。",
                )
            ]

    @dataclass
    class TraceStore:
        traces: list[TraceRecord] = field(default_factory=list)

        async def save(self, trace: TraceRecord) -> None:
            self.traces.append(trace)

        async def get(self, trace_id: str) -> TraceRecord | None:
            return next((trace for trace in self.traces if trace.id == trace_id), None)

        async def list_for_user(
            self, user_id: str, *, session_id: str | None = None, limit: int = 50
        ) -> list[TraceRecord]:
            traces = [trace for trace in self.traces if trace.user_id == user_id]
            if session_id is not None:
                traces = [trace for trace in traces if trace.session_id == session_id]
            return traces[:limit]

    runtime = RuntimeLLMClient(
        FakeRuntime(
            fixtures={
                RuntimeNode.INTENT: {"intent": "POLICY_QUERY", "confidence": 1},
                RuntimeNode.REWRITE: {"queries": ["税收优惠"]},
                RuntimeNode.ROUTE: {
                    "routes": [{"department_id": "dept_tax", "score": 1, "reason": "fixture"}]
                },
                RuntimeNode.ANSWER: {
                    "answer": "符合条件的主体可以享受政策优惠。",
                    "claims": [
                        {"text": "符合条件的主体可以享受政策优惠。", "citation_ids": ["C1"]}
                    ],
                },
                RuntimeNode.VERIFY: {
                    "supported": True,
                    "support_score": 1,
                    "contradiction": False,
                    "reason": "supported by canonical evidence",
                },
            }
        )
    )
    nodes = FixedDagNodes(
        intent=IntentNode(runtime),
        rewrite=RewriteNode(runtime),
        route=RouteNode(runtime, rules=[DepartmentRule("dept_tax", ("税",))]),
        retrieve=RetrieveNode(StaticRetriever()),
        answer=AnswerNode(runtime),
        verify=VerifyNode(runtime),
    )
    trace_store = TraceStore()

    result = await PolicyHarness(nodes, trace_store=trace_store).run(
        query="税收优惠",
        trace_id="trace-runtime-dag",
        session_id="session-runtime-dag",
        user_id="user-runtime-dag",
        now=datetime.now(UTC),
    )

    assert result.status.value == "SUCCESS"
    trace = trace_store.traces[0]
    route_trace = next(node for node in trace.nodes if node.node == "Route")
    assert len(route_trace.runtime_events) == 1
    runtime_event = route_trace.runtime_events[0]
    assert runtime_event["runtime_backend_requested"] == "fake"
    assert runtime_event["runtime_backend_used"] == "fake"
    assert runtime_event["runtime_fallback_reason"] is None
    assert isinstance(runtime_event["runtime_latency_ms"], float)
    assert runtime_event["runtime_latency_ms"] >= 0

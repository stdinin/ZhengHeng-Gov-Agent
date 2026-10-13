import asyncio
import time
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from backend.app.agents.models import (
    DepartmentAgentDefinition,
    DepartmentAgentResult,
    DepartmentExecutionRequest,
    DepartmentExecutionStatus,
)
from backend.app.domain.documents import DocumentVersionStatus
from backend.app.harness.state import IntentDecision, IntentKind, RewriteDecision
from backend.app.observability.tracing import TraceRecord


def definition(dept_id: str) -> DepartmentAgentDefinition:
    return DepartmentAgentDefinition(
        agent_id=f"{dept_id}-agent",
        dept_id=dept_id,
        display_name=dept_id,
        base_url=f"http://{dept_id}-agent:8000",
        timeout_ms=100,
    )


def success(dept_id: str) -> DepartmentAgentResult:
    return DepartmentAgentResult(
        agent_id=f"{dept_id}-agent",
        dept_id=dept_id,
        status=DepartmentExecutionStatus.SUCCESS,
        answer=f"{dept_id} verified answer [C1]",
        citations=[],
        evidence_count=1,
        local_verifier_pass=True,
        child_trace_id=f"child-{dept_id}",
        latency_ms=1,
        runtime_backend="pi",
    )


@pytest.mark.asyncio
async def test_parallel_dispatch_isolates_one_timeout_and_keeps_verified_results() -> None:
    from backend.app.agents.orchestrator import DepartmentDispatcher

    @dataclass
    class ControlledClient:
        async def execute(
            self,
            definition: DepartmentAgentDefinition,
            request: DepartmentExecutionRequest,
        ) -> DepartmentAgentResult:
            del request
            if definition.dept_id == "hrss":
                await asyncio.sleep(0.3)
            else:
                await asyncio.sleep(0.02)
            return success(definition.dept_id)

    started = time.perf_counter()
    outcome = await DepartmentDispatcher(client=ControlledClient(), max_parallel=3).dispatch(
        definitions=[definition("tax"), definition("hrss"), definition("housing")],
        request=DepartmentExecutionRequest(
            parent_trace_id="root-1",
            request_id="request-1",
            query="跨部门问题",
            rewritten_query="跨部门问题",
            deadline_ms=100,
        ),
    )
    elapsed = time.perf_counter() - started

    assert elapsed < 0.2
    assert [result.dept_id for result in outcome.successes] == ["tax", "housing"]
    assert outcome.failed_departments == [{"dept_id": "hrss", "reason": "timeout"}]
    assert outcome.partial is True


@pytest.mark.asyncio
async def test_dispatch_reports_abstain_when_every_department_fails() -> None:
    from backend.app.agents.orchestrator import DepartmentDispatcher

    @dataclass
    class FailingClient:
        async def execute(
            self,
            definition: DepartmentAgentDefinition,
            request: DepartmentExecutionRequest,
        ) -> DepartmentAgentResult:
            del definition, request
            raise ConnectionError("department unavailable")

    outcome = await DepartmentDispatcher(client=FailingClient(), max_parallel=2).dispatch(
        definitions=[definition("tax"), definition("hrss")],
        request=DepartmentExecutionRequest(
            parent_trace_id="root-2",
            request_id="request-2",
            query="跨部门问题",
            rewritten_query="跨部门问题",
            deadline_ms=100,
        ),
    )

    assert outcome.successes == []
    assert outcome.failed_departments == [
        {"dept_id": "tax", "reason": "client_error"},
        {"dept_id": "hrss", "reason": "client_error"},
    ]
    assert outcome.should_abstain is True


@pytest.mark.asyncio
async def test_global_orchestrator_persists_partial_root_child_trace() -> None:
    from backend.app.agents.aggregator import MultiAgentAggregator
    from backend.app.agents.models import DepartmentCitation, MultiAgentRouteDecision
    from backend.app.agents.orchestrator import DepartmentDispatcher, GlobalOrchestrator
    from backend.app.agents.registry import default_department_agent_registry

    @dataclass
    class StaticNodes:
        async def intent(self, query: str) -> IntentDecision:
            del query
            return IntentDecision(intent=IntentKind.CROSS_DEPT_QUERY, confidence=1)

        async def rewrite(self, query: str, intent: IntentDecision) -> RewriteDecision:
            del intent
            return RewriteDecision(queries=[query])

        async def route(
            self, queries: list[str], intent: IntentDecision
        ) -> MultiAgentRouteDecision:
            del queries, intent
            return MultiAgentRouteDecision(
                mode="multi",
                departments=["tax", "not-registered", "hrss"],
                confidence=0.9,
                reason="cross department",
            )

    @dataclass
    class PartialClient:
        async def execute(
            self,
            agent_definition: DepartmentAgentDefinition,
            request: DepartmentExecutionRequest,
        ) -> DepartmentAgentResult:
            del request
            if agent_definition.dept_id == "hrss":
                raise ConnectionError("unavailable")
            return DepartmentAgentResult(
                agent_id="tax-agent",
                dept_id="tax",
                status=DepartmentExecutionStatus.SUCCESS,
                answer="税务结论 [C1]",
                citations=[
                    DepartmentCitation(
                        id="C1",
                        chunk_id="tax-chunk",
                        document_id="tax-doc",
                        version_id="tax-version",
                        title="税务政策",
                        department="tax",
                        status=DocumentVersionStatus.ACTIVE.value,
                        excerpt="税务依据",
                    )
                ],
                evidence_count=1,
                local_verifier_pass=True,
                child_trace_id="child-tax",
                latency_ms=1,
                runtime_backend="pi",
            )

    @dataclass
    class TraceStore:
        traces: list[TraceRecord]

        async def save(self, trace: TraceRecord) -> None:
            self.traces.append(trace)

        async def get(self, trace_id: str) -> TraceRecord | None:
            return next((trace for trace in self.traces if trace.id == trace_id), None)

        async def list_for_user(
            self, user_id: str, *, session_id: str | None = None, limit: int = 50
        ) -> list[TraceRecord]:
            traces = [trace for trace in self.traces if trace.user_id == user_id]
            return [
                trace for trace in traces if session_id is None or trace.session_id == session_id
            ][:limit]

    trace_store = TraceStore(traces=[])
    orchestrator = GlobalOrchestrator(
        nodes=StaticNodes(),
        registry=default_department_agent_registry(),
        dispatcher=DepartmentDispatcher(client=PartialClient(), max_parallel=2),
        aggregator=MultiAgentAggregator(),
        trace_store=trace_store,
        max_departments=3,
    )

    result = await orchestrator.run(
        query="个税和社保如何办理",
        trace_id="root-trace-1",
        session_id="session-1",
        user_id="user-1",
        now=datetime.now(UTC),
    )

    assert result.status.value == "SUCCESS"
    assert result.orchestration == {
        "mode": "multi",
        "requested_departments": ["tax", "hrss"],
        "completed_departments": ["tax"],
        "failed_departments": [{"dept_id": "hrss", "reason": "client_error"}],
        "partial": True,
        "fanout": 2,
    }
    root_trace = trace_store.traces[0]
    assert root_trace.execution_mode == "multi_agent"
    assert root_trace.selected_departments == ["tax", "hrss"]
    assert root_trace.child_trace_ids == ["child-tax"]
    assert root_trace.partial is True
    assert root_trace.final_verification == {"passed": True, "warnings": []}


@pytest.mark.asyncio
async def test_registry_filtered_empty_route_is_a_traced_safe_abstain() -> None:
    from backend.app.agents.aggregator import MultiAgentAggregator
    from backend.app.agents.models import MultiAgentRouteDecision
    from backend.app.agents.orchestrator import DepartmentDispatcher, GlobalOrchestrator
    from backend.app.agents.registry import default_department_agent_registry

    @dataclass
    class AbstainingNodes:
        async def intent(self, query: str) -> IntentDecision:
            del query
            return IntentDecision(intent=IntentKind.POLICY_QUERY, confidence=1)

        async def rewrite(self, query: str, intent: IntentDecision) -> RewriteDecision:
            del intent
            return RewriteDecision(queries=[query])

        async def route(
            self, queries: list[str], intent: IntentDecision
        ) -> MultiAgentRouteDecision:
            del queries, intent
            return MultiAgentRouteDecision(
                mode="abstain",
                departments=[],
                confidence=0,
                reason="no registered department",
            )

    @dataclass
    class NoCallClient:
        async def execute(
            self,
            definition: DepartmentAgentDefinition,
            request: DepartmentExecutionRequest,
        ) -> DepartmentAgentResult:
            del definition, request
            raise AssertionError("an abstaining route must not dispatch a department")

    @dataclass
    class TraceStore:
        traces: list[TraceRecord]

        async def save(self, trace: TraceRecord) -> None:
            self.traces.append(trace)

        async def get(self, trace_id: str) -> TraceRecord | None:
            return next((trace for trace in self.traces if trace.id == trace_id), None)

        async def list_for_user(
            self, user_id: str, *, session_id: str | None = None, limit: int = 50
        ) -> list[TraceRecord]:
            del user_id, session_id, limit
            return []

    trace_store = TraceStore(traces=[])
    orchestrator = GlobalOrchestrator(
        nodes=AbstainingNodes(),
        registry=default_department_agent_registry(),
        dispatcher=DepartmentDispatcher(client=NoCallClient(), max_parallel=1),
        aggregator=MultiAgentAggregator(),
        trace_store=trace_store,
        max_departments=3,
    )

    result = await orchestrator.run(
        query="没有可匹配部门的问题",
        trace_id="root-abstain-1",
        session_id="session-1",
        user_id="user-1",
        now=datetime.now(UTC),
    )

    assert result.status.value == "ABSTAIN"
    assert trace_store.traces[0].department_routes == [
        {
            "department_id": "other",
            "score": 0.0,
            "reason": "No registered enabled department matched the route.",
        }
    ]

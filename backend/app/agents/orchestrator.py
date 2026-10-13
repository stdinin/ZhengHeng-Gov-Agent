"""Bounded, concurrent department fan-out for the global orchestrator role."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Protocol
from uuid import uuid4

from backend.app.agents.aggregator import MultiAgentAggregator
from backend.app.agents.memory import memory_trace_summary, scope_memory_snapshot
from backend.app.agents.models import (
    DepartmentAgentDefinition,
    DepartmentAgentResult,
    DepartmentExecutionRequest,
    DepartmentExecutionStatus,
    MultiAgentRouteDecision,
)
from backend.app.agents.registry import DepartmentAgentRegistry
from backend.app.harness.citations import Citation
from backend.app.harness.nodes import RouteNode
from backend.app.harness.policy import PolicyHarnessResult
from backend.app.harness.state import (
    AgentState,
    AnswerStatus,
    DepartmentRoute,
    IntentDecision,
    RewriteDecision,
    RouteDecision,
    VerificationResult,
)
from backend.app.observability.tracing import TraceRecorder
from backend.app.runtime.context import runtime_request_scope
from backend.app.storage.trace_repository import TraceStore


class DepartmentAgentClient(Protocol):
    async def execute(
        self, definition: DepartmentAgentDefinition, request: DepartmentExecutionRequest
    ) -> DepartmentAgentResult: ...


class GlobalSemanticNodes(Protocol):
    async def intent(self, query: str) -> IntentDecision: ...

    async def rewrite(self, query: str, intent: IntentDecision) -> RewriteDecision: ...

    async def route(
        self, queries: list[str], intent: IntentDecision
    ) -> MultiAgentRouteDecision: ...


class RegistryRouteNode:
    """Convert the fixed-DAG route output into only enabled static departments."""

    def __init__(
        self,
        *,
        route_node: RouteNode,
        registry: DepartmentAgentRegistry,
        max_departments: int,
        aliases: dict[str, str] | None = None,
    ) -> None:
        self._route_node = route_node
        self._registry = registry
        self._max_departments = max_departments
        self._aliases = aliases or {}

    async def route(
        self, queries: list[str], intent: IntentDecision
    ) -> MultiAgentRouteDecision:
        route = await self._route_node.run(queries, intent)
        departments: list[str] = []
        for item in route.routes:
            candidate = self._aliases.get(item.department_id, item.department_id)
            is_enabled = self._registry.get_by_department(candidate) is not None
            if is_enabled and candidate not in departments:
                departments.append(candidate)
            if len(departments) == self._max_departments:
                break
        if not departments:
            return MultiAgentRouteDecision(
                mode="abstain",
                departments=[],
                confidence=0,
                reason="No registered enabled department matched the route.",
            )
        return MultiAgentRouteDecision(
            mode="single" if len(departments) == 1 else "multi",
            departments=departments,
            confidence=max(item.score for item in route.routes),
            reason="Validated fixed-DAG route against static department registry.",
        )


@dataclass(frozen=True, slots=True)
class DispatchOutcome:
    successes: list[DepartmentAgentResult]
    failed_departments: list[dict[str, str]]

    @property
    def partial(self) -> bool:
        return bool(self.successes and self.failed_departments)

    @property
    def should_abstain(self) -> bool:
        return not self.successes


class DepartmentDispatcher:
    """Fan out in parallel and convert each local failure into a scoped outcome."""

    def __init__(self, *, client: DepartmentAgentClient, max_parallel: int) -> None:
        if max_parallel < 1:
            raise ValueError("max_parallel must be positive.")
        self._client = client
        self._max_parallel = max_parallel

    async def dispatch(
        self,
        *,
        definitions: list[DepartmentAgentDefinition],
        request: DepartmentExecutionRequest,
    ) -> DispatchOutcome:
        semaphore = asyncio.Semaphore(self._max_parallel)

        async def invoke(
            definition: DepartmentAgentDefinition,
        ) -> DepartmentAgentResult | dict[str, str]:
            try:
                async with semaphore, asyncio.timeout(definition.timeout_ms / 1_000):
                    scoped_request = request.model_copy(
                        update={
                            "memory_snapshot": scope_memory_snapshot(
                                request.memory_snapshot, definition.dept_id
                            )
                        }
                    )
                    result = await self._client.execute(definition, scoped_request)
            except TimeoutError:
                return {"dept_id": definition.dept_id, "reason": "timeout"}
            except Exception:
                return {"dept_id": definition.dept_id, "reason": "client_error"}
            if (
                result.status is not DepartmentExecutionStatus.SUCCESS
                or not result.local_verifier_pass
            ):
                return {"dept_id": definition.dept_id, "reason": result.status.value}
            return result

        outcomes = await asyncio.gather(
            *(invoke(definition) for definition in definitions),
            return_exceptions=True,
        )
        successes: list[DepartmentAgentResult] = []
        failures: list[dict[str, str]] = []
        for definition, outcome in zip(definitions, outcomes, strict=True):
            if isinstance(outcome, DepartmentAgentResult):
                successes.append(outcome)
            elif isinstance(outcome, dict):
                failures.append(outcome)
            else:
                failures.append({"dept_id": definition.dept_id, "reason": "client_error"})
        return DispatchOutcome(successes=successes, failed_departments=failures)


class GlobalOrchestrator:
    """Root execution: fixed semantic routing, bounded fan-out, aggregate, global verify."""

    def __init__(
        self,
        *,
        nodes: GlobalSemanticNodes,
        registry: DepartmentAgentRegistry,
        dispatcher: DepartmentDispatcher,
        aggregator: MultiAgentAggregator,
        trace_store: TraceStore,
        max_departments: int,
    ) -> None:
        if max_departments < 1:
            raise ValueError("max_departments must be positive.")
        self._nodes = nodes
        self._registry = registry
        self._dispatcher = dispatcher
        self._aggregator = aggregator
        self._trace_store = trace_store
        self._max_departments = max_departments

    async def run(
        self,
        *,
        query: str,
        trace_id: str,
        session_id: str,
        user_id: str | None,
        now: datetime,
        memory_snapshot: dict[str, object] | None = None,
        strategy_snapshot: dict[str, object] | None = None,
    ) -> PolicyHarnessResult:
        recorder = TraceRecorder(
            trace_id=trace_id,
            user_id=user_id,
            session_id=session_id,
            query=query,
            created_at=now,
        )
        state = AgentState(
            trace_id=trace_id,
            user_id=user_id,
            session_id=session_id,
            raw_query=query,
            memory_context=memory_trace_summary(memory_snapshot or {}),
        )
        started = time.perf_counter()
        warnings: list[str] = []

        with runtime_request_scope(trace_id=trace_id, agent_id="orchestrator", dept_id=None):
            intent_started = time.perf_counter()
            intent = await self._nodes.intent(query)
            state.intent = intent
            recorder.record_node(
                node="Intent",
                input_summary=query,
                output_summary=intent.intent.value,
                latency_ms=(time.perf_counter() - intent_started) * 1_000,
                fallback=intent.used_fallback,
            )
            rewrite_started = time.perf_counter()
            rewrite = await self._nodes.rewrite(query, intent)
            state.rewritten_queries = rewrite.queries
            state.normalized_query = rewrite.queries[0]
            recorder.record_node(
                node="Rewrite",
                input_summary=query,
                output_summary="; ".join(rewrite.queries),
                latency_ms=(time.perf_counter() - rewrite_started) * 1_000,
                fallback=rewrite.used_fallback,
            )
            route_started = time.perf_counter()
            requested_route = await self._nodes.route(rewrite.queries, intent)
            definitions = self._validate_route(requested_route)
            selected_departments = [definition.dept_id for definition in definitions]
            route_entries = [
                DepartmentRoute(
                    department_id=definition.dept_id,
                    score=requested_route.confidence,
                    reason=requested_route.reason,
                )
                for definition in definitions
            ]
            # ``RouteDecision`` is intentionally non-empty for trace
            # compatibility.  A registry-filtered empty route is represented
            # by the same safe sentinel used by the V1.0 harness, then the
            # multi-agent flow persists an ABSTAIN root trace below.
            if not route_entries:
                route_entries = [
                    DepartmentRoute(
                        department_id="other",
                        score=0,
                        reason="No registered enabled department matched the route.",
                    )
                ]
            state.department_routes = RouteDecision(
                routes=route_entries,
                routing_uncertain=requested_route.mode == "abstain",
            )
            recorder.record_node(
                node="Route",
                input_summary="; ".join(rewrite.queries),
                output_summary=", ".join(selected_departments) or "abstain",
                latency_ms=(time.perf_counter() - route_started) * 1_000,
                fallback=requested_route.mode == "abstain",
            )

            if not definitions:
                return await self._abstain(
                    recorder=recorder,
                    state=state,
                    requested_route=requested_route,
                    selected_departments=[],
                    warnings=["No enabled department agent matched the route."],
                    now=now,
                    started=started,
                )

            dispatch_started = time.perf_counter()
            dispatch = await self._dispatcher.dispatch(
                definitions=definitions,
                request=DepartmentExecutionRequest(
                    parent_trace_id=trace_id,
                    request_id=str(uuid4()),
                    query=query,
                    rewritten_query=state.normalized_query,
                    user_id=user_id,
                    memory_snapshot=memory_snapshot or {},
                    strategy_snapshot=strategy_snapshot or {},
                    deadline_ms=max(definition.timeout_ms for definition in definitions),
                ),
            )
            recorder.record_node(
                node="Dispatch",
                input_summary=", ".join(selected_departments),
                output_summary=(
                    f"{len(dispatch.successes)} successes / "
                    f"{len(dispatch.failed_departments)} failures"
                ),
                latency_ms=(time.perf_counter() - dispatch_started) * 1_000,
                fallback=dispatch.should_abstain,
            )
            if dispatch.should_abstain:
                return await self._abstain(
                    recorder=recorder,
                    state=state,
                    requested_route=requested_route,
                    selected_departments=selected_departments,
                    warnings=["All selected department agents failed or produced no evidence."],
                    failed_departments=dispatch.failed_departments,
                    child_trace_ids=[result.child_trace_id for result in dispatch.successes],
                    now=now,
                    started=started,
                )

            aggregate_started = time.perf_counter()
            aggregation = await self._aggregator.aggregate(dispatch.successes)
            recorder.record_node(
                node="Aggregate",
                input_summary=f"{len(dispatch.successes)} verified department results",
                output_summary=(
                    "passed"
                    if aggregation.global_verifier_pass
                    else "; ".join(aggregation.warnings)
                ),
                latency_ms=(time.perf_counter() - aggregate_started) * 1_000,
                fallback=not aggregation.global_verifier_pass or aggregation.used_fallback,
                runtime_events=aggregation.runtime_events,
            )
            warnings.extend(aggregation.warnings)
            if not aggregation.global_verifier_pass:
                return await self._abstain(
                    recorder=recorder,
                    state=state,
                    requested_route=requested_route,
                    selected_departments=selected_departments,
                    warnings=warnings,
                    failed_departments=dispatch.failed_departments,
                    child_trace_ids=[result.child_trace_id for result in dispatch.successes],
                    now=now,
                    started=started,
                )

            state.answer = aggregation.answer
            state.citations = [citation.id for citation in aggregation.citations]
            state.verification = VerificationResult(passed=True, retryable=False, warnings=[])
            state.status = AnswerStatus.SUCCESS
            state.errors = list(warnings)
            state.timings_ms = self._timings(recorder, started)
            result = PolicyHarnessResult(
                status=AnswerStatus.SUCCESS,
                answer=aggregation.answer,
                citations=aggregation.citations,
                attempts=1,
                warnings=warnings,
                state=state,
                orchestration={
                    "mode": requested_route.mode,
                    "requested_departments": selected_departments,
                    "completed_departments": [item.dept_id for item in dispatch.successes],
                    "failed_departments": dispatch.failed_departments,
                    "partial": dispatch.partial,
                    "fanout": len(definitions),
                },
            )
            await self._save_root_trace(
                recorder=recorder,
                result=result,
                requested_route=requested_route,
                selected_departments=selected_departments,
                failed_departments=dispatch.failed_departments,
                child_trace_ids=[item.child_trace_id for item in dispatch.successes],
                aggregation={
                    "sections": [section.dept_id for section in aggregation.sections],
                    "global_verifier_pass": aggregation.global_verifier_pass,
                    "presentation_runtime_fallback": aggregation.used_fallback,
                },
                final_verification={
                    "passed": aggregation.global_verifier_pass,
                    "warnings": aggregation.warnings,
                },
            )
            return result

    def _validate_route(
        self, route: MultiAgentRouteDecision
    ) -> list[DepartmentAgentDefinition]:
        if route.mode == "abstain":
            return []
        selected: list[DepartmentAgentDefinition] = []
        for dept_id in route.departments:
            definition = self._registry.get_by_department(dept_id)
            if definition is not None and definition not in selected:
                selected.append(definition)
            if len(selected) == self._max_departments:
                break
        return selected

    async def _abstain(
        self,
        *,
        recorder: TraceRecorder,
        state: AgentState,
        requested_route: MultiAgentRouteDecision,
        selected_departments: list[str],
        warnings: list[str],
        now: datetime,
        started: float,
        failed_departments: list[dict[str, str]] | None = None,
        child_trace_ids: list[str] | None = None,
    ) -> PolicyHarnessResult:
        answer = "当前有效政策证据不足，暂不作答。"
        state.answer = answer
        state.citations = []
        state.verification = VerificationResult(passed=False, retryable=False, warnings=warnings)
        state.status = AnswerStatus.ABSTAIN
        state.errors = list(warnings)
        state.timings_ms = self._timings(recorder, started)
        result = PolicyHarnessResult(
            status=AnswerStatus.ABSTAIN,
            answer=answer,
            citations=[],
            attempts=1,
            warnings=warnings,
            state=state,
            orchestration={
                "mode": requested_route.mode,
                "requested_departments": selected_departments,
                "completed_departments": [],
                "failed_departments": failed_departments or [],
                "partial": False,
                "fanout": len(selected_departments),
            },
        )
        await self._save_root_trace(
            recorder=recorder,
            result=result,
            requested_route=requested_route,
            selected_departments=selected_departments,
            failed_departments=failed_departments or [],
            child_trace_ids=child_trace_ids or [],
            aggregation={"sections": [], "global_verifier_pass": False},
            final_verification={"passed": False, "warnings": warnings},
        )
        return result

    async def _save_root_trace(
        self,
        *,
        recorder: TraceRecorder,
        result: PolicyHarnessResult,
        requested_route: MultiAgentRouteDecision,
        selected_departments: list[str],
        failed_departments: list[dict[str, str]],
        child_trace_ids: list[str],
        aggregation: dict[str, object],
        final_verification: dict[str, object],
    ) -> None:
        trace = recorder.finish(
            status=result.status,
            answer=result.answer,
            state=result.state,
            citation_cards=[self._citation_card(citation) for citation in result.citations],
        )
        trace = replace(
            trace,
            execution_mode="multi_agent",
            route_decision=requested_route.model_dump(mode="json"),
            selected_departments=selected_departments,
            child_trace_ids=child_trace_ids,
            aggregation=aggregation,
            partial=bool(result.orchestration and result.orchestration["partial"]),
            failed_departments=failed_departments,
            final_verification=final_verification,
        )
        await self._trace_store.save(trace)

    @staticmethod
    def _timings(recorder: TraceRecorder, started: float) -> dict[str, float]:
        trace = recorder.finish(status=AnswerStatus.SUCCESS, answer="")
        timings = {node.node: node.latency_ms for node in trace.nodes}
        timings["total"] = round((time.perf_counter() - started) * 1_000, 2)
        return timings

    @staticmethod
    def _citation_card(citation: Citation) -> dict[str, object]:
        return {
            "id": citation.id,
            "chunk_id": citation.chunk_id,
            "document_id": citation.document_id,
            "version_id": citation.version_id,
            "title": citation.title,
            "department": citation.department,
            "status": citation.status.value,
            "excerpt": citation.excerpt,
            "document_number": citation.document_number,
            "written_date": citation.written_date,
            "source_url": citation.source_url,
        }

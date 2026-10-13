import time
from collections.abc import Awaitable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, TypeVar, runtime_checkable

from backend.app.evolution.models import ActionType, StrategyCandidate
from backend.app.harness.citations import Citation, Evidence, render_cited_answer
from backend.app.harness.state import (
    AgentState,
    AnswerClaim,
    AnswerStatus,
    DepartmentRoute,
    IntentDecision,
    RewriteDecision,
    RouteDecision,
    VerificationResult,
)
from backend.app.observability.tracing import TraceRecorder
from backend.app.runtime.context import RuntimeInvocationAudit, runtime_request_scope
from backend.app.storage.trace_repository import TraceStore

NodeValue = TypeVar("NodeValue")


@dataclass(frozen=True, slots=True)
class AnswerDraft:
    content: str
    claims: list[AnswerClaim] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class PolicyHarnessResult:
    status: AnswerStatus
    answer: str
    citations: list[Citation]
    attempts: int
    warnings: list[str]
    state: AgentState
    orchestration: dict[str, object] | None = None


class PolicyHarnessNodes(Protocol):
    async def intent(self, query: str) -> IntentDecision: ...

    async def rewrite(self, query: str, intent: IntentDecision) -> RewriteDecision: ...

    async def route(self, queries: list[str], intent: IntentDecision) -> RouteDecision: ...

    async def retrieve(self, queries: list[str], route: RouteDecision) -> list[Evidence]: ...

    async def answer(self, query: str, evidence: list[Evidence]) -> AnswerDraft: ...

    async def verify(
        self,
        *,
        answer: str,
        citations: list[Citation],
        evidence: list[Evidence],
        claims: list[AnswerClaim],
    ) -> VerificationResult: ...


@runtime_checkable
class TraceablePolicyHarnessNodes(Protocol):
    async def retrieve_with_trace(
        self, queries: list[str], route: RouteDecision
    ) -> tuple[list[Evidence], dict[str, object]]: ...


class PolicyHarness:
    """The production-shaped fixed DAG with deterministic citation and trace gates."""

    def __init__(
        self,
        nodes: PolicyHarnessNodes,
        *,
        trace_store: TraceStore,
    ) -> None:
        self._nodes = nodes
        self._trace_store = trace_store

    async def run(
        self,
        *,
        query: str,
        trace_id: str,
        session_id: str,
        user_id: str | None,
        now: datetime,
        strategy: StrategyCandidate | None = None,
    ) -> PolicyHarnessResult:
        with runtime_request_scope(
            trace_id=trace_id,
            agent_id="orchestrator",
            dept_id=None,
        ):
            return await self._run_scoped(
                query=query,
                trace_id=trace_id,
                session_id=session_id,
                user_id=user_id,
                now=now,
                strategy=strategy,
            )

    async def _run_scoped(
        self,
        *,
        query: str,
        trace_id: str,
        session_id: str,
        user_id: str | None,
        now: datetime,
        strategy: StrategyCandidate | None = None,
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
        )
        warnings: list[str] = []
        last_citations: list[Citation] = []
        for attempt in range(1, 3):
            intent = await self._run_node(recorder, "Intent", query, self._nodes.intent(query))
            state.intent = intent
            rewritten = await self._run_node(
                recorder, "Rewrite", query, self._nodes.rewrite(query, intent)
            )
            replay_queries = self._apply_query_actions(rewritten.queries, strategy)
            state.rewritten_queries = replay_queries
            state.normalized_query = replay_queries[0]
            route = await self._run_node(
                recorder,
                "Route",
                "; ".join(replay_queries),
                self._nodes.route(replay_queries, intent),
            )
            route = self._apply_route_actions(route, strategy)
            if strategy is not None:
                state.matched_strategies = [f"{strategy.id}:v{strategy.version}"]
            state.department_routes = route
            evidence, retrieval_metadata = await self._run_node(
                recorder,
                "Retrieve",
                "; ".join(replay_queries),
                self._retrieve(replay_queries, route),
            )
            state.retrieval_hits = [item.chunk_id for item in evidence]
            state.retrieval_metadata = retrieval_metadata
            draft = await self._run_node(
                recorder,
                "Answer",
                state.normalized_query,
                self._nodes.answer(state.normalized_query, evidence),
            )
            verification, answer, citations = await self._run_node(
                recorder,
                "Verify",
                f"{len(evidence)} evidence / {len(draft.claims)} claims",
                self._verify(draft, evidence),
            )
            warnings.extend(verification.warnings)
            state.answer = answer
            state.citations = [citation.id for citation in citations]
            state.verification = verification
            state.retry_count = attempt - 1
            state.errors = list(warnings)
            last_citations = citations
            if verification.passed:
                state.status = AnswerStatus.SUCCESS
                state.timings_ms = self._timings(recorder)
                result = PolicyHarnessResult(
                    status=AnswerStatus.SUCCESS,
                    answer=answer,
                    citations=citations,
                    attempts=attempt,
                    warnings=warnings,
                    state=state,
                )
                trace = recorder.finish(
                    status=result.status,
                    answer=result.answer,
                    state=state,
                    citation_cards=[self._citation_card(citation) for citation in citations],
                )
                await self._trace_store.save(trace)
                return result
            if not verification.retryable:
                break
        result = PolicyHarnessResult(
            status=AnswerStatus.ABSTAIN,
            answer="当前有效政策证据不足，暂不作答。",
            citations=[],
            attempts=attempt,
            warnings=warnings,
            state=state,
        )
        state.status = AnswerStatus.ABSTAIN
        state.answer = result.answer
        state.errors = list(warnings)
        state.timings_ms = self._timings(recorder)
        await self._trace_store.save(
            recorder.finish(
                status=result.status,
                answer=result.answer,
                state=state,
                citation_cards=[self._citation_card(citation) for citation in last_citations],
            )
        )
        return result

    @staticmethod
    def _apply_query_actions(
        queries: list[str], strategy: StrategyCandidate | None
    ) -> list[str]:
        if strategy is None:
            return queries
        updated = list(queries)
        for action in strategy.actions:
            if action.action_type is ActionType.QUERY_EXPAND:
                expanded = " ".join([updated[0], *action.terms]).strip()
                updated = list(dict.fromkeys([*updated, expanded]))[:3]
            elif action.action_type is ActionType.QUERY_REPLACE_TERM:
                updated = [
                    query.replace(action.source_term, action.replacement_term)
                    for query in updated
                ]
            elif action.action_type is ActionType.TERM_ALIAS:
                for alias in action.aliases:
                    updated = [query.replace(alias, action.canonical_term) for query in updated]
        return updated

    @staticmethod
    def _apply_route_actions(
        route: RouteDecision, strategy: StrategyCandidate | None
    ) -> RouteDecision:
        if strategy is None:
            return route
        department_ids = [
            action.department_id
            for action in strategy.actions
            if action.action_type is ActionType.DEPARTMENT_HINT
        ]
        if not department_ids:
            return route
        return RouteDecision(
            routes=[
                DepartmentRoute(
                    department_id=department_id,
                    score=1.0,
                    reason=f"strategy {strategy.id}:v{strategy.version}",
                )
                for department_id in dict.fromkeys(department_ids)
            ][:3],
            routing_uncertain=False,
        )

    async def _run_node(
        self,
        recorder: TraceRecorder,
        node: str,
        input_summary: str,
        operation: Awaitable[NodeValue],
    ) -> NodeValue:
        started = time.perf_counter()
        result = await operation
        runtime_events = self._drain_runtime_audits()
        recorder.record_node(
            node=node,
            input_summary=input_summary[:500],
            output_summary=self._summarize(result),
            latency_ms=round((time.perf_counter() - started) * 1_000, 2),
            fallback=bool(getattr(result, "used_fallback", False)),
            runtime_events=runtime_events,
        )
        return result

    def _drain_runtime_audits(self) -> list[dict[str, str | float | None]]:
        drain = getattr(self._nodes, "drain_runtime_audits", None)
        if not callable(drain):
            return []
        return [
            audit.as_trace_metadata()
            for audit in drain()
            if isinstance(audit, RuntimeInvocationAudit)
        ]

    async def _verify(
        self, draft: AnswerDraft, evidence: list[Evidence]
    ) -> tuple[VerificationResult, str, list[Citation]]:
        try:
            answer, citations = render_cited_answer(
                draft.content,
                evidence,
                claims=draft.claims,
            )
        except ValueError:
            return (
                VerificationResult(
                    passed=False,
                    retryable=False,
                    warnings=["No active evidence is available for a factual answer."],
                ),
                "",
                [],
            )
        return (
            await self._nodes.verify(
                answer=answer,
                citations=citations,
                evidence=evidence,
                claims=draft.claims,
            ),
            answer,
            citations,
        )

    async def _retrieve(
        self, queries: list[str], route: RouteDecision
    ) -> tuple[list[Evidence], dict[str, object]]:
        if isinstance(self._nodes, TraceablePolicyHarnessNodes):
            return await self._nodes.retrieve_with_trace(queries, route)
        return await self._nodes.retrieve(queries, route), {}

    @staticmethod
    def _summarize(value: object) -> str:
        if isinstance(value, tuple) and value and isinstance(value[0], VerificationResult):
            verification = value[0]
            return "passed" if verification.passed else "; ".join(verification.warnings)
        if (
            isinstance(value, tuple)
            and len(value) == 2
            and isinstance(value[0], list)
            and isinstance(value[1], dict)
        ):
            return f"{len(value[0])} items / retrieval metadata={value[1]}"
        if isinstance(value, list):
            return f"{len(value)} items"
        return str(value)[:500]

    @staticmethod
    def _timings(recorder: TraceRecorder) -> dict[str, float]:
        trace = recorder.finish(status=AnswerStatus.SUCCESS, answer="")
        timings = {node.node: node.latency_ms for node in trace.nodes}
        timings["total"] = round(sum(timings.values()), 2)
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

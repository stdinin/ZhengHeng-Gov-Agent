from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast

from backend.app.harness.state import AgentState, AnswerStatus
from backend.app.observability.logging import redact_pii


def _redact_structure(value: Any) -> Any:
    if isinstance(value, str):
        return redact_pii(value)
    if isinstance(value, dict):
        return {key: _redact_structure(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_structure(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_structure(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class TraceNode:
    node: str
    input_summary: str
    output_summary: str
    latency_ms: float
    fallback: bool = False
    token_usage: int | None = None
    applied_strategy_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class TraceRecord:
    id: str
    user_id: str | None
    session_id: str
    query: str
    nodes: list[TraceNode]
    status: AnswerStatus
    answer: str
    created_at: datetime
    updated_at: datetime
    normalized_query: str | None = None
    intent: dict[str, Any] | None = None
    rewritten_queries: list[str] = field(default_factory=list)
    department_routes: list[dict[str, Any]] = field(default_factory=list)
    memory_context: list[str] = field(default_factory=list)
    matched_strategies: list[str] = field(default_factory=list)
    retrieval_hits: list[str] = field(default_factory=list)
    retrieval_metadata: dict[str, Any] = field(default_factory=dict)
    citations: list[dict[str, Any]] = field(default_factory=list)
    verification: dict[str, Any] | None = None
    retry_count: int = 0
    errors: list[str] = field(default_factory=list)
    timings_ms: dict[str, float] = field(default_factory=dict)


class TraceRecorder:
    """Build an immutable request trace with only redacted/summarized node payloads."""

    def __init__(
        self,
        *,
        trace_id: str,
        user_id: str | None,
        session_id: str,
        query: str,
        created_at: datetime,
    ) -> None:
        self._trace_id = trace_id
        self._user_id = user_id
        self._session_id = session_id
        self._query = redact_pii(query)
        self._created_at = created_at
        self._nodes: list[TraceNode] = []

    def record_node(
        self,
        *,
        node: str,
        input_summary: str,
        output_summary: str,
        latency_ms: float,
        fallback: bool = False,
        token_usage: int | None = None,
        applied_strategy_ids: list[str] | None = None,
    ) -> None:
        if latency_ms < 0:
            raise ValueError("Node latency cannot be negative.")
        self._nodes.append(
            TraceNode(
                node=node,
                input_summary=redact_pii(input_summary),
                output_summary=redact_pii(output_summary),
                latency_ms=latency_ms,
                fallback=fallback,
                token_usage=token_usage,
                applied_strategy_ids=applied_strategy_ids or [],
            )
        )

    def finish(
        self,
        *,
        status: AnswerStatus,
        answer: str,
        state: AgentState | None = None,
        citation_cards: list[dict[str, Any]] | None = None,
    ) -> TraceRecord:
        intent = (
            cast(dict[str, Any], _redact_structure(state.intent.model_dump(mode="json")))
            if state and state.intent
            else None
        )
        routes_raw = (
            state.department_routes.model_dump(mode="json")["routes"]
            if state and state.department_routes
            else []
        )
        routes = cast(list[dict[str, Any]], _redact_structure(routes_raw))
        verification = (
            cast(
                dict[str, Any],
                _redact_structure(
                    {
                        "passed": state.verification.passed,
                        "retryable": state.verification.retryable,
                        "warnings": state.verification.warnings,
                    }
                ),
            )
            if state and state.verification
            else None
        )
        default_cards = (
            [{"id": citation_id} for citation_id in state.citations] if state else []
        )
        cards = cast(
            list[dict[str, Any]],
            _redact_structure(citation_cards or default_cards),
        )
        normalized_query = (
            redact_pii(state.normalized_query)
            if state and state.normalized_query is not None
            else None
        )
        rewritten_queries = (
            [redact_pii(query) for query in state.rewritten_queries] if state else []
        )
        memory_context = (
            [redact_pii(item) for item in state.memory_context] if state else []
        )
        retrieval_metadata = (
            cast(dict[str, Any], _redact_structure(state.retrieval_metadata))
            if state
            else {}
        )
        return TraceRecord(
            id=self._trace_id,
            user_id=self._user_id,
            session_id=self._session_id,
            query=self._query,
            nodes=list(self._nodes),
            status=status,
            answer=redact_pii(answer),
            created_at=self._created_at,
            updated_at=datetime.now(UTC),
            normalized_query=normalized_query,
            intent=intent,
            rewritten_queries=rewritten_queries,
            department_routes=list(routes),
            memory_context=memory_context,
            matched_strategies=list(state.matched_strategies) if state else [],
            retrieval_hits=list(state.retrieval_hits) if state else [],
            retrieval_metadata=retrieval_metadata,
            citations=cards,
            verification=verification,
            retry_count=state.retry_count if state else 0,
            errors=[redact_pii(error) for error in state.errors] if state else [],
            timings_ms=dict(state.timings_ms) if state else {},
        )

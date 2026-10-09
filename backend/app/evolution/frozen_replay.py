from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from math import ceil
from uuid import uuid4

from backend.app.evolution.models import (
    ExperimentBucket,
    FrozenReplayInput,
    StrategyCandidate,
    StrategyExecution,
)
from backend.app.evolution.replay import ReplayMetrics
from backend.app.harness.policy import PolicyHarness
from backend.app.harness.state import AnswerStatus
from backend.app.observability.tracing import TraceRecord
from backend.app.storage.trace_repository import TraceStore


class FrozenReplayError(ValueError):
    """Raised when a real persisted trace cannot be frozen or replayed."""


@dataclass(frozen=True, slots=True)
class FrozenReplayResult:
    baseline: ReplayMetrics
    candidate: ReplayMetrics
    target_badcases_resolved: int
    frozen_inputs: list[FrozenReplayInput]
    candidate_trace_ids: list[str]


class FrozenTraceReplayExecutor:
    """Replay declarative strategies through the real harness using frozen Mongo traces."""

    def __init__(self, *, harness: PolicyHarness, trace_store: TraceStore) -> None:
        self._harness = harness
        self._trace_store = trace_store

    async def freeze(
        self, strategy: StrategyCandidate, source_trace_ids: list[str]
    ) -> list[FrozenReplayInput]:
        if not source_trace_ids:
            raise FrozenReplayError("At least one persisted source trace is required.")
        frozen: list[FrozenReplayInput] = []
        for trace_id in list(dict.fromkeys(source_trace_ids)):
            trace = await self._trace_store.get(trace_id)
            if trace is None:
                raise FrozenReplayError(f"Persisted source trace not found: {trace_id}")
            baseline_id, baseline_version = _baseline_strategy(trace)
            frozen.append(
                FrozenReplayInput(
                    id=f"frozen_{uuid4().hex}",
                    strategy_id=strategy.id,
                    strategy_version=strategy.version,
                    source_trace_id=trace.id,
                    source_trace_created_at=trace.created_at,
                    user_id=trace.user_id,
                    session_id=trace.session_id,
                    query=trace.query,
                    normalized_query=trace.normalized_query,
                    rewritten_queries=list(trace.rewritten_queries),
                    department_routes=list(trace.department_routes),
                    original_context=list(trace.retrieval_hits),
                    retrieval_metadata=dict(trace.retrieval_metadata),
                    baseline_status=trace.status.value,
                    baseline_citations=list(trace.citations),
                    baseline_verification=(
                        dict(trace.verification) if trace.verification is not None else None
                    ),
                    baseline_errors=list(trace.errors),
                    baseline_timings_ms=dict(trace.timings_ms),
                    baseline_strategy_id=baseline_id,
                    baseline_strategy_version=baseline_version,
                    created_at=datetime.now(UTC),
                )
            )
        return frozen

    async def execute(
        self, strategy: StrategyCandidate, frozen_inputs: list[FrozenReplayInput]
    ) -> FrozenReplayResult:
        candidate_traces: list[TraceRecord] = []
        for replay_input in frozen_inputs:
            trace_id = f"replay_{strategy.id}_v{strategy.version}_{uuid4().hex}"
            await self._harness.run(
                query=replay_input.query,
                trace_id=trace_id,
                session_id=replay_input.session_id,
                user_id=replay_input.user_id,
                now=datetime.now(UTC),
                strategy=strategy,
            )
            candidate_trace = await self._trace_store.get(trace_id)
            if candidate_trace is None:
                raise FrozenReplayError(
                    f"Replay harness did not persist candidate trace: {trace_id}"
                )
            candidate_traces.append(candidate_trace)

        baseline = _metrics_from_frozen_inputs(frozen_inputs)
        candidate_metrics = _metrics_from_traces(candidate_traces)
        resolved = sum(
            not _frozen_success(source) and _trace_success(replayed)
            for source, replayed in zip(frozen_inputs, candidate_traces, strict=True)
        )
        return FrozenReplayResult(
            baseline=baseline,
            candidate=candidate_metrics,
            target_badcases_resolved=resolved,
            frozen_inputs=frozen_inputs,
            candidate_trace_ids=[trace.id for trace in candidate_traces],
        )

    async def execution_from_trace(
        self,
        strategy: StrategyCandidate,
        *,
        trace_id: str,
        bucket: ExperimentBucket,
    ) -> StrategyExecution:
        trace = await self._trace_store.get(trace_id)
        if trace is None:
            raise FrozenReplayError(f"Persisted execution trace not found: {trace_id}")
        success = _trace_success(trace)
        return StrategyExecution(
            id=f"execution_{uuid4().hex}",
            strategy_id=strategy.id,
            strategy_version=strategy.version,
            trace_id=trace.id,
            bucket=bucket,
            success=success,
            citation_ok=not _citation_error(trace.citations, success),
            stale_policy_error=bool(_stale_errors(trace.citations, trace.errors)),
            latency_ms=trace.timings_ms.get("total", 0.0),
            created_at=datetime.now(UTC),
        )


def _baseline_strategy(trace: TraceRecord) -> tuple[str | None, int | None]:
    if not trace.matched_strategies:
        return None, None
    value = trace.matched_strategies[0]
    strategy_id, separator, version = value.rpartition(":v")
    if not separator or not version.isdigit():
        return value, None
    return strategy_id, int(version)


def _frozen_success(item: FrozenReplayInput) -> bool:
    verification = item.baseline_verification or {}
    return item.baseline_status == AnswerStatus.SUCCESS.value and bool(
        verification.get("passed")
    )


def _trace_success(trace: TraceRecord) -> bool:
    verification = trace.verification or {}
    return trace.status is AnswerStatus.SUCCESS and bool(verification.get("passed"))


def _citation_error(citations: list[dict[str, object]], success: bool) -> bool:
    if not success:
        return False
    if not citations:
        return True
    return any(
        not citation.get("chunk_id") or not citation.get("version_id")
        for citation in citations
    )


def _stale_errors(
    citations: list[dict[str, object]], errors: list[str]
) -> int:
    return sum(
        str(citation.get("status", "")).upper() in {"ARCHIVED", "REVOKED"}
        for citation in citations
    ) + sum("stale" in error.lower() for error in errors)


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(0, ceil(len(ordered) * 0.95) - 1)]


def _metrics_from_frozen_inputs(items: list[FrozenReplayInput]) -> ReplayMetrics:
    total = len(items)
    successes = [_frozen_success(item) for item in items]
    return ReplayMetrics(
        success_rate=sum(successes) / total,
        citation_error_rate=sum(
            _citation_error(item.baseline_citations, success)
            for item, success in zip(items, successes, strict=True)
        )
        / total,
        stale_policy_errors=sum(
            _stale_errors(item.baseline_citations, item.baseline_errors) for item in items
        ),
        p95_ms=_p95([item.baseline_timings_ms.get("total", 0.0) for item in items]),
    )


def _metrics_from_traces(traces: list[TraceRecord]) -> ReplayMetrics:
    total = len(traces)
    successes = [_trace_success(trace) for trace in traces]
    return ReplayMetrics(
        success_rate=sum(successes) / total,
        citation_error_rate=sum(
            _citation_error(trace.citations, success)
            for trace, success in zip(traces, successes, strict=True)
        )
        / total,
        stale_policy_errors=sum(_stale_errors(trace.citations, trace.errors) for trace in traces),
        p95_ms=_p95([trace.timings_ms.get("total", 0.0) for trace in traces]),
    )

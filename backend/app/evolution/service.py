from datetime import UTC, datetime
from math import ceil
from uuid import uuid4

from backend.app.evolution.deploy import RollbackDecision, should_rollback
from backend.app.evolution.frozen_replay import FrozenReplayError, FrozenTraceReplayExecutor
from backend.app.evolution.models import (
    BadCase,
    BadCaseStatus,
    ExperimentBucket,
    ExperimentRecord,
    ExperimentStatus,
    Feedback,
    FeedbackType,
    ObservationReason,
    ReplayMetricSnapshot,
    ReplayReport,
    StrategyCandidate,
    StrategyExecution,
    StrategyStatus,
)
from backend.app.evolution.replay import ReplayMetrics, evaluate_replay_gate
from backend.app.evolution.repository import EvolutionRepository


class EvolutionStateError(ValueError):
    """Raised when a strategy transition violates the controlled deployment state machine."""


class FeedbackService:
    """Persist feedback and create a constrained, reviewable bad-case observation."""

    def __init__(self, repository: EvolutionRepository) -> None:
        self._repository = repository

    async def record(self, feedback: Feedback) -> BadCase | None:
        await self._repository.save_feedback(feedback)
        reason = self._reason_for(feedback)
        if reason is None:
            return None
        now = datetime.now(UTC)
        badcase = BadCase(
            id=str(uuid4()),
            trace_id=feedback.trace_id,
            reason=reason,
            confidence=0.5,
            evidence={"feedback_id": feedback.id, "text": feedback.text or ""},
            source="AUTO",
            status=BadCaseStatus.OPEN,
            feedback_id=feedback.id,
            created_at=now,
            updated_at=now,
        )
        await self._repository.save_badcase(badcase)
        return badcase

    @staticmethod
    def _reason_for(feedback: Feedback) -> ObservationReason | None:
        if feedback.feedback_type is FeedbackType.DISLIKE:
            return ObservationReason.CITATION_ERROR
        if feedback.feedback_type is FeedbackType.CORRECTION:
            return ObservationReason.GENERATION_ERROR
        if feedback.feedback_type is FeedbackType.REPORT:
            return ObservationReason.SAFETY_BLOCK
        return None


class EvolutionService:
    """Controlled feedback-to-strategy lifecycle backed by a real repository."""

    def __init__(
        self,
        repository: EvolutionRepository,
        *,
        replay_executor: FrozenTraceReplayExecutor | None = None,
    ) -> None:
        self._repository = repository
        self._replay_executor = replay_executor

    async def review_badcase(
        self, badcase_id: str, *, status: BadCaseStatus = BadCaseStatus.REVIEWED
    ) -> BadCase:
        badcase = await self._repository.get_badcase(badcase_id)
        if badcase is None:
            raise EvolutionStateError(f"Bad case not found: {badcase_id}")
        reviewed = badcase.model_copy(
            update={"status": status, "updated_at": datetime.now(UTC)}
        )
        await self._repository.save_badcase(reviewed)
        return reviewed

    async def propose_strategy(
        self, badcase_id: str, candidate: StrategyCandidate
    ) -> StrategyCandidate:
        badcase = await self._repository.get_badcase(badcase_id)
        if badcase is None:
            raise EvolutionStateError(f"Bad case not found: {badcase_id}")
        if candidate.status is not StrategyStatus.CANDIDATE:
            raise EvolutionStateError("Only CANDIDATE strategies can be proposed.")
        now = datetime.now(UTC)
        created_from = list(dict.fromkeys([*candidate.created_from_badcase_ids, badcase_id]))
        proposed = candidate.model_copy(
            update={"created_from_badcase_ids": created_from, "updated_at": now}
        )
        await self._repository.save_strategy(proposed)
        await self._repository.save_badcase(
            badcase.model_copy(update={"status": BadCaseStatus.REVIEWED, "updated_at": now})
        )
        return proposed

    async def replay_from_frozen_traces(
        self,
        *,
        strategy_id: str,
        source_trace_ids: list[str],
    ) -> StrategyCandidate:
        strategy = await self._require_strategy(strategy_id)
        if strategy.status is not StrategyStatus.CANDIDATE:
            raise EvolutionStateError("Only CANDIDATE strategies may enter replay.")
        if self._replay_executor is None:
            raise EvolutionStateError("Real frozen-trace replay executor is unavailable.")
        try:
            frozen_inputs = await self._replay_executor.freeze(strategy, source_trace_ids)
            for replay_input in frozen_inputs:
                await self._repository.save_frozen_replay_input(replay_input)
            replay = await self._replay_executor.execute(strategy, frozen_inputs)
        except FrozenReplayError as error:
            raise EvolutionStateError(str(error)) from error
        gate = evaluate_replay_gate(
            baseline=replay.baseline,
            candidate=replay.candidate,
            target_badcases_resolved=replay.target_badcases_resolved,
        )
        now = datetime.now(UTC)
        report = ReplayReport(
            id=str(uuid4()),
            strategy_id=strategy.id,
            strategy_version=strategy.version,
            baseline=_snapshot(replay.baseline),
            candidate=_snapshot(replay.candidate),
            target_badcases_resolved=replay.target_badcases_resolved,
            passed=gate.passed,
            reasons=gate.reasons,
            frozen_input_ids=[item.id for item in replay.frozen_inputs],
            source_trace_ids=[item.source_trace_id for item in replay.frozen_inputs],
            candidate_trace_ids=replay.candidate_trace_ids,
            created_at=now,
        )
        next_status = StrategyStatus.REPLAY_PASSED if gate.passed else StrategyStatus.REJECTED
        updated = strategy.model_copy(
            update={
                "status": next_status,
                "replay_report_id": report.id,
                "decision_reason": "; ".join(gate.reasons) or None,
                "updated_at": now,
            }
        )
        await self._repository.save_replay_report(report)
        await self._repository.save_strategy(updated)
        return updated

    async def approve_gray(
        self,
        strategy_id: str,
        *,
        rollout_percent: int = 10,
        approved_by: str | None = None,
    ) -> StrategyCandidate:
        if not 1 <= rollout_percent <= 100:
            raise EvolutionStateError("Gray rollout percent must be between 1 and 100.")
        strategy = await self._require_strategy(strategy_id)
        if strategy.status is not StrategyStatus.REPLAY_PASSED:
            raise EvolutionStateError("Only replay-passed strategies can enter gray rollout.")
        now = datetime.now(UTC)
        grayed = strategy.model_copy(
            update={
                "status": StrategyStatus.GRAY,
                "rollout_percent": rollout_percent,
                "approved_by": approved_by,
                "approved_at": now,
                "updated_at": now,
            }
        )
        await self._repository.save_strategy(grayed)
        return grayed

    async def promote(self, strategy_id: str) -> StrategyCandidate:
        strategy = await self._require_strategy(strategy_id)
        if strategy.status is not StrategyStatus.GRAY:
            raise EvolutionStateError("Only gray strategies can be promoted.")
        promoted = strategy.model_copy(
            update={
                "status": StrategyStatus.ACTIVE,
                "rollout_percent": 100,
                "updated_at": datetime.now(UTC),
            }
        )
        await self._repository.save_strategy(promoted)
        return promoted

    async def record_execution(self, execution: StrategyExecution) -> None:
        strategy = await self._require_strategy(execution.strategy_id)
        if strategy.status not in {StrategyStatus.GRAY, StrategyStatus.ACTIVE}:
            raise EvolutionStateError("Strategy execution requires a gray or active strategy.")
        if strategy.version != execution.strategy_version:
            raise EvolutionStateError(
                "Strategy execution version does not match the current strategy."
            )
        await self._repository.save_execution(execution)

    async def record_execution_from_trace(
        self,
        strategy_id: str,
        *,
        trace_id: str,
        bucket: ExperimentBucket,
    ) -> StrategyExecution:
        strategy = await self._require_strategy(strategy_id)
        if strategy.status not in {StrategyStatus.GRAY, StrategyStatus.ACTIVE}:
            raise EvolutionStateError("Strategy execution requires a gray or active strategy.")
        if self._replay_executor is None:
            raise EvolutionStateError("Real trace-backed execution recorder is unavailable.")
        try:
            execution = await self._replay_executor.execution_from_trace(
                strategy,
                trace_id=trace_id,
                bucket=bucket,
            )
        except FrozenReplayError as error:
            raise EvolutionStateError(str(error)) from error
        await self._repository.save_execution(execution)
        return execution

    async def monitor_gray_and_maybe_rollback(
        self, strategy_id: str, *, manual: bool = False
    ) -> RollbackDecision:
        strategy = await self._require_strategy(strategy_id)
        if strategy.status not in {StrategyStatus.GRAY, StrategyStatus.ACTIVE}:
            raise EvolutionStateError("Only deployed strategies can be monitored for rollback.")
        control = await self._repository.list_executions(strategy_id, ExperimentBucket.CONTROL)
        treatment = await self._repository.list_executions(strategy_id, ExperimentBucket.TREATMENT)
        control_metrics = _metrics_from_executions(control)
        treatment_metrics = _metrics_from_executions(treatment)
        decision = should_rollback(
            control=control_metrics,
            treatment=treatment_metrics,
            control_n=len(control),
            treatment_n=len(treatment),
            manual=manual,
        )
        now = datetime.now(UTC)
        if decision.rollback:
            rolled_back = strategy.model_copy(
                update={
                    "status": StrategyStatus.ROLLED_BACK,
                    "rollout_percent": 0,
                    "decision_reason": "; ".join(decision.reasons),
                    "updated_at": now,
                }
            )
            await self._repository.save_strategy(rolled_back)
            experiment_status = ExperimentStatus.ROLLED_BACK
        else:
            experiment_status = ExperimentStatus.MONITORING
        experiment = ExperimentRecord(
            id=str(uuid4()),
            strategy_id=strategy.id,
            strategy_version=strategy.version,
            status=experiment_status,
            control_n=len(control),
            treatment_n=len(treatment),
            control=_snapshot(control_metrics),
            treatment=_snapshot(treatment_metrics),
            decision_reasons=decision.reasons,
            created_at=now,
            updated_at=now,
        )
        await self._repository.save_experiment(experiment)
        return decision

    async def rollback(self, strategy_id: str, *, reason: str) -> StrategyCandidate:
        if not reason.strip():
            raise EvolutionStateError("Rollback reason must not be blank.")
        strategy = await self._require_strategy(strategy_id)
        rolled_back = strategy.model_copy(
            update={
                "status": StrategyStatus.ROLLED_BACK,
                "rollout_percent": 0,
                "decision_reason": reason.strip(),
                "updated_at": datetime.now(UTC),
            }
        )
        await self._repository.save_strategy(rolled_back)
        return rolled_back

    async def _require_strategy(self, strategy_id: str) -> StrategyCandidate:
        strategy = await self._repository.get_strategy(strategy_id)
        if strategy is None:
            raise EvolutionStateError(f"Strategy not found: {strategy_id}")
        return strategy


def _snapshot(metrics: ReplayMetrics) -> ReplayMetricSnapshot:
    return ReplayMetricSnapshot(
        success_rate=metrics.success_rate,
        citation_error_rate=metrics.citation_error_rate,
        stale_policy_errors=metrics.stale_policy_errors,
        p95_ms=metrics.p95_ms,
    )


def _metrics_from_executions(executions: list[StrategyExecution]) -> ReplayMetrics:
    if not executions:
        return ReplayMetrics(0.0, 0.0, 0, 0.0)
    latencies = sorted(execution.latency_ms for execution in executions)
    p95_index = max(0, ceil(len(latencies) * 0.95) - 1)
    total = len(executions)
    return ReplayMetrics(
        success_rate=sum(execution.success for execution in executions) / total,
        citation_error_rate=sum(not execution.citation_ok for execution in executions) / total,
        stale_policy_errors=sum(execution.stale_policy_error for execution in executions),
        p95_ms=latencies[p95_index],
    )

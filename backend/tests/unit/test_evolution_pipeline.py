from dataclasses import dataclass, field
from datetime import UTC, datetime

from backend.app.evolution.models import (
    ActionType,
    BadCase,
    BadCaseStatus,
    ExperimentBucket,
    ObservationReason,
    StrategyCandidate,
    StrategyExecution,
    StrategyStatus,
)
from backend.app.evolution.service import EvolutionService


@dataclass
class InMemoryEvolutionRepository:
    """Explicit unit-test double; runtime always uses MongoEvolutionRepository."""

    badcases: dict[str, BadCase] = field(default_factory=dict)
    strategies: dict[str, StrategyCandidate] = field(default_factory=dict)
    executions: list[StrategyExecution] = field(default_factory=list)
    replay_reports: list[object] = field(default_factory=list)
    experiments: list[object] = field(default_factory=list)

    async def get_badcase(self, badcase_id: str) -> BadCase | None:
        return self.badcases.get(badcase_id)

    async def save_badcase(self, badcase: BadCase) -> None:
        self.badcases[badcase.id] = badcase

    async def get_strategy(self, strategy_id: str) -> StrategyCandidate | None:
        return self.strategies.get(strategy_id)

    async def save_strategy(self, strategy: StrategyCandidate) -> None:
        self.strategies[strategy.id] = strategy

    async def save_replay_report(self, report: object) -> None:
        self.replay_reports.append(report)

    async def save_execution(self, execution: StrategyExecution) -> None:
        self.executions.append(execution)

    async def list_executions(
        self, strategy_id: str, bucket: ExperimentBucket
    ) -> list[StrategyExecution]:
        return [
            execution
            for execution in self.executions
            if execution.strategy_id == strategy_id and execution.bucket is bucket
        ]

    async def save_experiment(self, experiment: object) -> None:
        self.experiments.append(experiment)


async def test_candidate_persists_replay_gray_and_rollback_state_transitions() -> None:
    now = datetime.now(UTC)
    repository = InMemoryEvolutionRepository(
        badcases={
            "badcase_1": BadCase(
                id="badcase_1",
                trace_id="trace_1",
                reason=ObservationReason.RETRIEVAL_ERROR,
                confidence=0.9,
                evidence={"missing_terms": ["灵活就业"]},
                source="AUTO",
                status=BadCaseStatus.OPEN,
                created_at=now,
                updated_at=now,
            )
        }
    )
    service = EvolutionService(repository)
    candidate = StrategyCandidate(
        id="strategy_1",
        version=1,
        status=StrategyStatus.CANDIDATE,
        name="补充灵活就业检索词",
        actions=[
            {
                "action_type": ActionType.QUERY_EXPAND,
                "terms": ["灵活就业"],
            }
        ],
    )

    proposed = await service.propose_strategy("badcase_1", candidate)
    replayed = proposed.model_copy(
        update={"status": StrategyStatus.REPLAY_PASSED, "updated_at": now}
    )
    await repository.save_strategy(replayed)
    grayed = await service.approve_gray(proposed.id, rollout_percent=10)

    assert proposed.created_from_badcase_ids == ["badcase_1"]
    assert replayed.status is StrategyStatus.REPLAY_PASSED
    assert grayed.status is StrategyStatus.GRAY
    assert grayed.rollout_percent == 10

    for ordinal in range(50):
        await service.record_execution(
            StrategyExecution(
                id=f"control_{ordinal}",
                strategy_id=grayed.id,
                strategy_version=grayed.version,
                trace_id=f"control_trace_{ordinal}",
                bucket=ExperimentBucket.CONTROL,
                success=True,
                citation_ok=True,
                stale_policy_error=False,
                latency_ms=100,
                created_at=now,
            )
        )
        await service.record_execution(
            StrategyExecution(
                id=f"treatment_{ordinal}",
                strategy_id=grayed.id,
                strategy_version=grayed.version,
                trace_id=f"treatment_trace_{ordinal}",
                bucket=ExperimentBucket.TREATMENT,
                success=False,
                citation_ok=False,
                stale_policy_error=True,
                latency_ms=140,
                created_at=now,
            )
        )

    decision = await service.monitor_gray_and_maybe_rollback(grayed.id)
    rolled_back = await repository.get_strategy(grayed.id)

    assert decision.rollback is True
    assert rolled_back is not None
    assert rolled_back.status is StrategyStatus.ROLLED_BACK
    assert rolled_back.rollout_percent == 0

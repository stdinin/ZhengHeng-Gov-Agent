from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx
from fastapi import FastAPI

from backend.app.api.evolution import router as evolution_router
from backend.app.config import Settings
from backend.app.evolution.models import (
    BadCase,
    BadCaseStatus,
    ExperimentBucket,
    ObservationReason,
    StrategyCandidate,
    StrategyExecution,
    StrategyStatus,
)
from backend.app.evolution.service import EvolutionService
from backend.app.security.auth import User, create_access_token, hash_password
from backend.app.security.rbac import Role
from backend.app.storage.users import InMemoryUserStore


@dataclass
class InMemoryEvolutionRepository:
    badcases: dict[str, BadCase] = field(default_factory=dict)
    strategies: dict[str, StrategyCandidate] = field(default_factory=dict)
    reports: list[object] = field(default_factory=list)
    executions: list[StrategyExecution] = field(default_factory=list)
    experiments: list[object] = field(default_factory=list)

    async def save_feedback(self, feedback: object) -> None:
        del feedback

    async def save_badcase(self, badcase: BadCase) -> None:
        self.badcases[badcase.id] = badcase

    async def get_badcase(self, badcase_id: str) -> BadCase | None:
        return self.badcases.get(badcase_id)

    async def list_badcases(self, *, limit: int = 100) -> list[BadCase]:
        return list(self.badcases.values())[:limit]

    async def save_strategy(self, strategy: StrategyCandidate) -> None:
        self.strategies[strategy.id] = strategy

    async def get_strategy(self, strategy_id: str) -> StrategyCandidate | None:
        return self.strategies.get(strategy_id)

    async def list_strategies(self, *, limit: int = 100) -> list[StrategyCandidate]:
        return list(self.strategies.values())[:limit]

    async def save_replay_report(self, report: object) -> None:
        self.reports.append(report)

    async def save_execution(self, execution: StrategyExecution) -> None:
        self.executions.append(execution)

    async def list_executions(
        self, strategy_id: str, bucket: ExperimentBucket
    ) -> list[StrategyExecution]:
        return [
            item
            for item in self.executions
            if item.strategy_id == strategy_id and item.bucket is bucket
        ]

    async def save_experiment(self, experiment: object) -> None:
        self.experiments.append(experiment)


async def test_admin_evolution_api_rejects_metric_injection_and_controls_deployment() -> None:
    settings = Settings(app_secret="test-secret-that-is-at-least-32-bytes")
    admin = User(
        id="admin_1",
        email="admin@example.local",
        password_hash=hash_password("demo-admin"),
        role=Role.DEPT_ADMIN,
        created_at=datetime.now(UTC),
    )
    now = datetime.now(UTC)
    repository = InMemoryEvolutionRepository(
        badcases={
            "badcase_1": BadCase(
                id="badcase_1",
                trace_id="trace_1",
                reason=ObservationReason.RETRIEVAL_ERROR,
                confidence=0.8,
                evidence={"missing_terms": ["灵活就业"]},
                source="AUTO",
                status=BadCaseStatus.OPEN,
                created_at=now,
                updated_at=now,
            )
        }
    )
    app = FastAPI()
    app.state.settings = settings
    app.state.user_store = InMemoryUserStore([admin])
    app.state.evolution_repository = repository
    app.state.evolution_service = EvolutionService(repository)
    app.include_router(evolution_router)
    headers = {"Authorization": f"Bearer {create_access_token(admin, settings)}"}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        proposed = await client.post(
            "/api/v1/badcases/badcase_1/propose-strategy",
            headers=headers,
            json={
                "name": "补充灵活就业检索词",
                "actions": [
                    {"type": "QUERY_EXPAND", "terms": ["灵活就业"]}
                ],
            },
        )
        strategy_id = proposed.json()["id"]
        replayed = await client.post(
            f"/api/v1/strategies/{strategy_id}/replay",
            headers=headers,
            json={
                "baseline": {
                    "success_rate": 0.80,
                    "citation_error_rate": 0.01,
                    "stale_policy_errors": 0,
                    "p95_ms": 100,
                },
                "candidate": {
                    "success_rate": 0.81,
                    "citation_error_rate": 0.01,
                    "stale_policy_errors": 0,
                    "p95_ms": 110,
                },
                "target_badcases_resolved": 1,
            },
        )
        repository.strategies[strategy_id] = repository.strategies[strategy_id].model_copy(
            update={"status": StrategyStatus.REPLAY_PASSED}
        )
        grayed = await client.post(
            f"/api/v1/strategies/{strategy_id}/approve-gray",
            headers=headers,
            json={"rollout_percent": 10},
        )
        rolled_back = await client.post(
            f"/api/v1/strategies/{strategy_id}/rollback",
            headers=headers,
            json={"reason": "管理员人工回滚验证"},
        )

    assert proposed.status_code == 201
    assert proposed.json()["type"] == "SKILL"
    assert proposed.json()["actions"][0]["type"] == "QUERY_EXPAND"
    assert proposed.json()["created_by"] == "admin_1"
    assert replayed.status_code == 422
    assert grayed.json()["status"] == "GRAY"
    assert grayed.json()["approved_by"] == "admin_1"
    assert rolled_back.json()["status"] == "ROLLED_BACK"

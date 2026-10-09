from typing import Any, Protocol

from pydantic import BaseModel
from pymongo import AsyncMongoClient
from pymongo.asynchronous.collection import AsyncCollection

from backend.app.config import Settings
from backend.app.evolution.models import (
    BadCase,
    ExperimentBucket,
    ExperimentRecord,
    Feedback,
    FrozenReplayInput,
    ReplayReport,
    StrategyCandidate,
    StrategyExecution,
)


class EvolutionRepository(Protocol):
    async def save_feedback(self, feedback: Feedback) -> None: ...

    async def save_badcase(self, badcase: BadCase) -> None: ...

    async def get_badcase(self, badcase_id: str) -> BadCase | None: ...

    async def list_badcases(self, *, limit: int = 100) -> list[BadCase]: ...

    async def save_strategy(self, strategy: StrategyCandidate) -> None: ...

    async def get_strategy(self, strategy_id: str) -> StrategyCandidate | None: ...

    async def list_strategies(self, *, limit: int = 100) -> list[StrategyCandidate]: ...

    async def save_replay_report(self, report: ReplayReport) -> None: ...

    async def get_replay_report(self, report_id: str) -> ReplayReport | None: ...

    async def save_frozen_replay_input(self, replay_input: FrozenReplayInput) -> None: ...

    async def save_execution(self, execution: StrategyExecution) -> None: ...

    async def list_executions(
        self, strategy_id: str, bucket: ExperimentBucket
    ) -> list[StrategyExecution]: ...

    async def save_experiment(self, experiment: ExperimentRecord) -> None: ...

    async def list_experiments(
        self, *, strategy_id: str | None = None, limit: int = 100
    ) -> list[ExperimentRecord]: ...


class MongoEvolutionRepository:
    """Real MongoDB persistence for feedback, bad cases, strategies and experiments."""

    def __init__(self, settings: Settings) -> None:
        self._client: AsyncMongoClient[dict[str, Any]] = AsyncMongoClient(settings.mongo_uri)
        database = self._client[settings.mongo_db]
        self._feedback: AsyncCollection[dict[str, Any]] = database["feedback"]
        self._badcases: AsyncCollection[dict[str, Any]] = database["badcases"]
        self._strategies: AsyncCollection[dict[str, Any]] = database["strategies"]
        self._replay_reports: AsyncCollection[dict[str, Any]] = database["strategy_replays"]
        self._frozen_replay_inputs: AsyncCollection[dict[str, Any]] = database[
            "frozen_replay_inputs"
        ]
        self._executions: AsyncCollection[dict[str, Any]] = database["strategy_executions"]
        self._experiments: AsyncCollection[dict[str, Any]] = database["experiments"]

    async def initialize_indexes(self) -> None:
        await self._feedback.create_index([("trace_id", 1), ("created_at", -1)])
        await self._badcases.create_index([("trace_id", 1), ("status", 1)])
        await self._badcases.create_index([("reason", 1), ("created_at", -1)])
        await self._strategies.create_index([("status", 1), ("updated_at", -1)])
        await self._strategies.create_index([("created_from_badcase_ids", 1)])
        await self._replay_reports.create_index([("strategy_id", 1), ("created_at", -1)])
        await self._frozen_replay_inputs.create_index(
            [("strategy_id", 1), ("source_trace_id", 1), ("created_at", -1)]
        )
        await self._executions.create_index(
            [("strategy_id", 1), ("bucket", 1), ("created_at", -1)]
        )
        await self._experiments.create_index([("strategy_id", 1), ("created_at", -1)])

    async def save_feedback(self, feedback: Feedback) -> None:
        await self._replace_model(self._feedback, feedback)

    async def save_badcase(self, badcase: BadCase) -> None:
        await self._replace_model(self._badcases, badcase)

    async def get_badcase(self, badcase_id: str) -> BadCase | None:
        document = await self._badcases.find_one({"_id": badcase_id})
        return BadCase.model_validate(self._with_id(document)) if document else None

    async def list_badcases(self, *, limit: int = 100) -> list[BadCase]:
        cursor = self._badcases.find({}).sort([("created_at", -1)]).limit(limit)
        return [BadCase.model_validate(self._with_id(document)) async for document in cursor]

    async def save_strategy(self, strategy: StrategyCandidate) -> None:
        await self._replace_model(self._strategies, strategy)

    async def get_strategy(self, strategy_id: str) -> StrategyCandidate | None:
        document = await self._strategies.find_one({"_id": strategy_id})
        return StrategyCandidate.model_validate(self._with_id(document)) if document else None

    async def list_strategies(self, *, limit: int = 100) -> list[StrategyCandidate]:
        cursor = self._strategies.find({}).sort([("updated_at", -1)]).limit(limit)
        return [
            StrategyCandidate.model_validate(self._with_id(document)) async for document in cursor
        ]

    async def save_replay_report(self, report: ReplayReport) -> None:
        await self._replace_model(self._replay_reports, report)

    async def get_replay_report(self, report_id: str) -> ReplayReport | None:
        document = await self._replay_reports.find_one({"_id": report_id})
        return ReplayReport.model_validate(self._with_id(document)) if document else None

    async def save_frozen_replay_input(self, replay_input: FrozenReplayInput) -> None:
        await self._replace_model(self._frozen_replay_inputs, replay_input)

    async def save_execution(self, execution: StrategyExecution) -> None:
        await self._replace_model(self._executions, execution)

    async def list_executions(
        self, strategy_id: str, bucket: ExperimentBucket
    ) -> list[StrategyExecution]:
        cursor = self._executions.find(
            {"strategy_id": strategy_id, "bucket": bucket.value}
        ).sort([("created_at", 1)])
        return [
            StrategyExecution.model_validate(self._with_id(document)) async for document in cursor
        ]

    async def save_experiment(self, experiment: ExperimentRecord) -> None:
        await self._replace_model(self._experiments, experiment)

    async def list_experiments(
        self, *, strategy_id: str | None = None, limit: int = 100
    ) -> list[ExperimentRecord]:
        query: dict[str, object] = {"strategy_id": strategy_id} if strategy_id else {}
        cursor = self._experiments.find(query).sort([("created_at", -1)]).limit(limit)
        return [
            ExperimentRecord.model_validate(self._with_id(document)) async for document in cursor
        ]

    async def close(self) -> None:
        await self._client.close()

    @staticmethod
    async def _replace_model(
        collection: AsyncCollection[dict[str, Any]], model: BaseModel
    ) -> None:
        document = model.model_dump(mode="python")
        identifier = str(document.pop("id"))
        document["_id"] = identifier
        await collection.replace_one({"_id": identifier}, document, upsert=True)

    @staticmethod
    def _with_id(document: dict[str, Any]) -> dict[str, Any]:
        value = dict(document)
        value["id"] = str(value.pop("_id"))
        return value

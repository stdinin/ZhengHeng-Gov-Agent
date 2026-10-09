import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pymongo import AsyncMongoClient

from backend.app.config import Settings
from backend.app.evolution.models import (
    ActionType,
    ExperimentBucket,
    Feedback,
    FeedbackType,
    StrategyCandidate,
    StrategyExecution,
    StrategyStatus,
)
from backend.app.evolution.repository import MongoEvolutionRepository
from backend.app.evolution.service import EvolutionService, FeedbackService
from backend.app.memory.models import MemoryItem, MemoryType
from backend.app.memory.repository import MongoMemoryRepository
from backend.app.memory.working import RedisWorkingMemory


def _settings() -> Settings:
    return Settings(
        mongo_uri="mongodb://localhost:27017",
        redis_url="redis://localhost:6379/0",
        opensearch_url="http://localhost:9201",
        milvus_host="localhost",
    )


def _require_infrastructure() -> None:
    if os.getenv("RUN_INTEGRATION") != "1":
        pytest.skip(
            "SKIPPED: infrastructure unavailable; set RUN_INTEGRATION=1 after Compose is healthy."
        )


async def _delete_documents(
    settings: Settings, collection: str, query: dict[str, object]
) -> None:
    client: AsyncMongoClient[dict[str, object]] = AsyncMongoClient(settings.mongo_uri)
    try:
        await client[settings.mongo_db][collection].delete_many(query)
    finally:
        await client.close()


@pytest.mark.integration
async def test_real_redis_and_mongo_memory_repositories_preserve_memory_boundaries() -> None:
    _require_infrastructure()
    settings = _settings()
    suffix = uuid4().hex
    now = datetime.now(UTC)
    user_id = f"it_memory_user_{suffix}"
    session_id = f"it_memory_session_{suffix}"
    department_id = "dept_tax"
    memory_ids = [
        f"it_memory_episodic_{suffix}",
        f"it_memory_semantic_{suffix}",
        f"it_memory_organizational_{suffix}",
        f"it_memory_procedural_{suffix}",
        f"it_memory_other_user_{suffix}",
    ]
    repository = MongoMemoryRepository(settings)
    working = RedisWorkingMemory(settings)
    try:
        await repository.initialize_indexes()
        memories = [
            MemoryItem(
                id=memory_ids[0],
                memory_type=MemoryType.EPISODIC,
                user_id=user_id,
                department_id=department_id,
                content="上次咨询过税务登记。",
                confidence=0.9,
                source_trace_id=f"trace_{suffix}",
                created_at=now,
                updated_at=now,
            ),
            MemoryItem(
                id=memory_ids[1],
                memory_type=MemoryType.USER_SEMANTIC,
                user_id=user_id,
                content="常用地区：北京。",
                confidence=1.0,
                consented=True,
                created_at=now,
                updated_at=now,
            ),
            MemoryItem(
                id=memory_ids[2],
                memory_type=MemoryType.ORGANIZATIONAL,
                department_id=department_id,
                content="税务登记也称开业登记。",
                confidence=0.8,
                source_trace_id=f"trace_{suffix}",
                created_at=now,
                updated_at=now,
            ),
            MemoryItem(
                id=memory_ids[3],
                memory_type=MemoryType.PROCEDURAL,
                department_id=department_id,
                content="查询扩展策略仅影响检索过程。",
                confidence=0.8,
                source_trace_id=f"strategy_{suffix}",
                created_at=now,
                updated_at=now,
            ),
            MemoryItem(
                id=memory_ids[4],
                memory_type=MemoryType.USER_SEMANTIC,
                user_id=f"other_{user_id}",
                content="不得泄漏给当前用户。",
                confidence=1.0,
                consented=True,
                created_at=now,
                updated_at=now,
            ),
        ]
        for memory in memories:
            await repository.upsert(memory)

        context_candidates = await repository.list_context_candidates(
            user_id=user_id,
            department_id=department_id,
        )
        assert {item.id for item in context_candidates} == set(memory_ids[:4])
        assert await repository.delete_user_semantic(user_id, memory_ids[1]) is True
        assert await repository.delete_user_semantic(user_id, memory_ids[4]) is False

        working_item = await working.build_item(
            memory_id=f"it_memory_working_{suffix}",
            user_id=user_id,
            session_id=session_id,
            content="当前办理事项：税务登记。",
            source_trace_id=f"trace_{suffix}",
        )
        await working.put(working_item)
        assert (await working.get(session_id)).id == working_item.id  # type: ignore[union-attr]
        ttl_seconds = await working.ttl_remaining(session_id)
        assert ttl_seconds is not None
        assert 0 < ttl_seconds <= settings.working_memory_ttl_seconds
    finally:
        await working.delete(session_id)
        await working.close()
        await _delete_documents(settings, "memories", {"_id": {"$in": memory_ids}})
        await repository.close()


@pytest.mark.integration
async def test_real_mongo_persists_feedback_through_gray_rollback() -> None:
    _require_infrastructure()
    settings = _settings()
    suffix = uuid4().hex
    now = datetime.now(UTC)
    repository = MongoEvolutionRepository(settings)
    feedback_id = f"it_feedback_{suffix}"
    strategy_id = f"it_strategy_{suffix}"
    trace_id = f"it_trace_{suffix}"
    admin_id = f"it_admin_{suffix}"
    execution_ids: list[str] = []
    try:
        await repository.initialize_indexes()
        feedback = Feedback(
            id=feedback_id,
            trace_id=trace_id,
            user_id=f"it_user_{suffix}",
            feedback_type=FeedbackType.DISLIKE,
            text="该政策的检索证据不完整。",
            created_at=now,
        )
        badcase = await FeedbackService(repository).record(feedback)
        assert badcase is not None
        assert (await repository.get_badcase(badcase.id)).feedback_id == feedback_id  # type: ignore[union-attr]

        service = EvolutionService(repository)
        candidate = StrategyCandidate(
            id=strategy_id,
            version=1,
            status=StrategyStatus.CANDIDATE,
            name="补充政策检索词",
            created_by=admin_id,
            actions=[
                {"action_type": ActionType.QUERY_EXPAND, "terms": ["灵活就业"]}
            ],
        )
        proposed = await service.propose_strategy(badcase.id, candidate)
        replayed = proposed.model_copy(
            update={"status": StrategyStatus.REPLAY_PASSED, "updated_at": now}
        )
        await repository.save_strategy(replayed)
        grayed = await service.approve_gray(
            replayed.id,
            rollout_percent=10,
            approved_by=admin_id,
        )

        for ordinal in range(50):
            control_id = f"it_control_{suffix}_{ordinal}"
            treatment_id = f"it_treatment_{suffix}_{ordinal}"
            execution_ids.extend([control_id, treatment_id])
            await service.record_execution(
                StrategyExecution(
                    id=control_id,
                    strategy_id=grayed.id,
                    strategy_version=grayed.version,
                    trace_id=f"{trace_id}_control_{ordinal}",
                    bucket=ExperimentBucket.CONTROL,
                    success=True,
                    citation_ok=True,
                    latency_ms=100,
                    created_at=now,
                )
            )
            await service.record_execution(
                StrategyExecution(
                    id=treatment_id,
                    strategy_id=grayed.id,
                    strategy_version=grayed.version,
                    trace_id=f"{trace_id}_treatment_{ordinal}",
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
        assert rolled_back.created_by == admin_id
        assert rolled_back.approved_by == admin_id
    finally:
        await _delete_documents(settings, "feedback", {"_id": feedback_id})
        await _delete_documents(settings, "badcases", {"trace_id": trace_id})
        await _delete_documents(settings, "strategies", {"_id": strategy_id})
        await _delete_documents(settings, "strategy_replays", {"strategy_id": strategy_id})
        await _delete_documents(settings, "strategy_executions", {"_id": {"$in": execution_ids}})
        await _delete_documents(settings, "experiments", {"strategy_id": strategy_id})
        await repository.close()

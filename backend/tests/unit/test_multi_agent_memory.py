from dataclasses import dataclass, field
from datetime import UTC, datetime

from backend.app.agents.memory import (
    RootMemoryCoordinator,
    memory_trace_summary,
    scope_memory_snapshot,
)
from backend.app.harness.policy import PolicyHarnessResult
from backend.app.harness.state import AgentState, AnswerStatus, VerificationResult
from backend.app.memory.context import MemoryContextService
from backend.app.memory.models import MemoryItem, MemoryType


def item(
    memory_id: str,
    memory_type: MemoryType,
    *,
    department_id: str | None = None,
) -> MemoryItem:
    now = datetime.now(UTC)
    return MemoryItem(
        id=memory_id,
        memory_type=memory_type,
        user_id="user-1",
        session_id="session-1",
        department_id=department_id,
        content=f"content-{memory_id}",
        confidence=0.9,
        source_trace_id="old-trace",
        created_at=now,
        updated_at=now,
    )


@dataclass
class Repository:
    items: list[MemoryItem]
    written: list[MemoryItem] = field(default_factory=list)

    async def list_context_candidates(
        self, *, user_id: str, department_id: str | None, limit: int = 100
    ) -> list[MemoryItem]:
        del user_id, department_id, limit
        return self.items

    async def upsert(self, memory: MemoryItem) -> None:
        self.written = [item for item in self.written if item.id != memory.id] + [memory]

    async def list_for_user(self, user_id: str, memory_type: MemoryType) -> list[MemoryItem]:
        del user_id, memory_type
        return []

    async def delete_user_semantic(self, user_id: str, memory_id: str) -> bool:
        del user_id, memory_id
        return False


@dataclass
class WorkingMemory:
    value: MemoryItem | None

    async def get(self, session_id: str) -> MemoryItem | None:
        assert session_id == "session-1"
        return self.value


async def test_root_builds_one_read_only_snapshot_scopes_it_and_writes_final_episode_once() -> None:
    repository = Repository(
        [
            item("semantic", MemoryType.USER_SEMANTIC),
            item("tax-org", MemoryType.ORGANIZATIONAL, department_id="tax"),
            item("hrss-org", MemoryType.ORGANIZATIONAL, department_id="hrss"),
            item("tax-procedure", MemoryType.PROCEDURAL, department_id="tax"),
        ]
    )
    coordinator = RootMemoryCoordinator(
        context_service=MemoryContextService(
            repository=repository,
            working_memory=WorkingMemory(item("working", MemoryType.WORKING)),
        ),
        repository=repository,
        token_budget=100,
    )

    snapshot = await coordinator.build_snapshot(
        user_id="user-1", session_id="session-1", query="税务和社保办理"
    )
    tax_snapshot = scope_memory_snapshot(snapshot, "tax")

    assert snapshot["read_only"] is True
    assert {entry["id"] for entry in snapshot["items"]} == {
        "working",
        "semantic",
        "tax-org",
        "hrss-org",
        "tax-procedure",
    }
    assert {entry["id"] for entry in tax_snapshot["items"]} == {
        "working",
        "semantic",
        "tax-org",
        "tax-procedure",
    }
    assert memory_trace_summary(snapshot) == [
        "WORKING:working",
        "USER_SEMANTIC:semantic",
        "ORGANIZATIONAL:tax-org",
        "ORGANIZATIONAL:hrss-org",
        "PROCEDURAL:tax-procedure",
    ]

    state = AgentState(
        trace_id="trace-1",
        user_id="user-1",
        session_id="session-1",
        raw_query="税务和社保办理",
        status=AnswerStatus.SUCCESS,
        verification=VerificationResult(passed=True),
    )
    result = PolicyHarnessResult(
        status=AnswerStatus.SUCCESS,
        answer="verified",
        citations=[],
        attempts=1,
        warnings=[],
        state=state,
        orchestration={"completed_departments": ["tax", "hrss"]},
    )
    await coordinator.write_final_episodic(
        user_id="user-1", session_id="session-1", trace_id="trace-1", result=result
    )
    await coordinator.write_final_episodic(
        user_id="user-1", session_id="session-1", trace_id="trace-1", result=result
    )

    assert len(repository.written) == 1
    assert repository.written[0].memory_type is MemoryType.EPISODIC
    assert repository.written[0].source_trace_id == "trace-1"

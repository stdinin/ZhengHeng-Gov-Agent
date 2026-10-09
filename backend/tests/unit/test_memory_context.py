from dataclasses import dataclass
from datetime import UTC, datetime

from backend.app.memory.context import MemoryContextBuilder, MemoryContextService
from backend.app.memory.models import MemoryItem, MemoryType


def _memory(memory_id: str, memory_type: MemoryType, content: str) -> MemoryItem:
    return MemoryItem(
        id=memory_id,
        memory_type=memory_type,
        user_id="user_1",
        content=content,
        confidence=0.9,
        source_trace_id="trace_1",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def test_memory_context_prioritizes_non_procedural_memory_by_priority() -> None:
    context = MemoryContextBuilder().build(
        working=[_memory("working", MemoryType.WORKING, "当前办理事项：税务登记")],
        semantic=[_memory("semantic", MemoryType.USER_SEMANTIC, "用户偏好：北京")],
        episodic=[_memory("episodic", MemoryType.EPISODIC, "上次咨询税务登记")],
        organizational=[_memory("organization", MemoryType.ORGANIZATIONAL, "税务登记别名")],
        procedural=[_memory("skill", MemoryType.PROCEDURAL, "不应进入事实上下文")],
        token_budget=7,
    )

    assert [item.id for item in context.items] == ["working", "semantic", "episodic"]
    assert context.truncated is True
    assert "[memory:" in context.render_for_llm()
    assert "citation" not in context.render_for_llm().lower()


def test_memory_context_rejects_non_positive_budget() -> None:
    try:
        MemoryContextBuilder().build(
            working=[], semantic=[], episodic=[], organizational=[], procedural=[], token_budget=0
        )
    except ValueError as error:
        assert "positive" in str(error)
    else:
        raise AssertionError("A non-positive memory token budget must fail.")


@dataclass
class RecordingMemoryRepository:
    items: list[MemoryItem]
    requested_user_id: str | None = None
    requested_department_id: str | None = None

    async def list_context_candidates(
        self, *, user_id: str, department_id: str | None, limit: int = 100
    ) -> list[MemoryItem]:
        del limit
        self.requested_user_id = user_id
        self.requested_department_id = department_id
        return self.items


@dataclass
class RecordingWorkingMemory:
    item: MemoryItem | None
    requested_session_id: str | None = None

    async def get(self, session_id: str) -> MemoryItem | None:
        self.requested_session_id = session_id
        return self.item


async def test_memory_context_service_collects_all_memory_planes_without_procedural_citations(
) -> None:
    working = _memory("working", MemoryType.WORKING, "当前办理事项：税务登记")
    repository = RecordingMemoryRepository(
        [
            _memory("semantic", MemoryType.USER_SEMANTIC, "常用地区：北京"),
            _memory("episodic", MemoryType.EPISODIC, "上次咨询税务登记"),
            _memory("organization", MemoryType.ORGANIZATIONAL, "税务登记别名"),
            _memory("procedure", MemoryType.PROCEDURAL, "查询扩展策略"),
        ]
    )
    working_memory = RecordingWorkingMemory(working)

    context = await MemoryContextService(
        repository=repository,
        working_memory=working_memory,
    ).build(
        user_id="user_1",
        session_id="session_1",
        query="税务登记怎么办",
        department_id="dept_tax",
        token_budget=100,
    )

    assert [item.id for item in context.items] == [
        "working",
        "semantic",
        "episodic",
        "organization",
    ]
    assert repository.requested_user_id == "user_1"
    assert repository.requested_department_id == "dept_tax"
    assert working_memory.requested_session_id == "session_1"
    assert "procedure" not in context.render_for_llm()

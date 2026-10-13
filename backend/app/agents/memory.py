"""V1.1 root-owned memory hand-off for multi-agent execution.

The coordinator intentionally reuses the V1.0 five-layer memory services. It
does not treat memory as policy evidence and department services never receive
write access to it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

from backend.app.harness.policy import PolicyHarnessResult
from backend.app.memory.context import MemoryContextService
from backend.app.memory.models import MemoryItem, MemoryType
from backend.app.memory.repository import MemoryRepository


class MultiAgentMemoryCoordinator(Protocol):
    async def build_snapshot(
        self, *, user_id: str, session_id: str, query: str
    ) -> dict[str, object]: ...

    async def write_final_episodic(
        self,
        *,
        user_id: str,
        session_id: str,
        trace_id: str,
        result: PolicyHarnessResult,
    ) -> None: ...


class RootMemoryCoordinator:
    """Build once at the root, scope per department in the dispatcher, write once at end."""

    def __init__(
        self,
        *,
        context_service: MemoryContextService,
        repository: MemoryRepository,
        token_budget: int,
    ) -> None:
        self._context_service = context_service
        self._repository = repository
        self._token_budget = token_budget

    async def build_snapshot(
        self, *, user_id: str, session_id: str, query: str
    ) -> dict[str, object]:
        context = await self._context_service.build(
            user_id=user_id,
            session_id=session_id,
            query=query,
            department_id=None,
            token_budget=self._token_budget,
        )
        # The V1.0 builder intentionally omits procedural memory from answer
        # context. Keep that invariant, while carrying its IDs/content in this
        # V1.1 read-only strategy snapshot for department-scoped dispatch.
        candidates = await self._repository.list_context_candidates(
            user_id=user_id,
            department_id=None,
        )
        items = {item.id: item for item in context.items}
        for item in candidates:
            if item.memory_type is MemoryType.PROCEDURAL:
                items.setdefault(item.id, item)
        return {
            "items": [
                {
                    "id": item.id,
                    "memory_type": item.memory_type.value,
                    "department_id": item.department_id,
                    "content": item.content,
                    "confidence": item.confidence,
                }
                for item in items.values()
            ],
            "token_budget": context.token_budget,
            "estimated_tokens": context.estimated_tokens,
            "truncated": context.truncated,
            "read_only": True,
        }

    async def write_final_episodic(
        self,
        *,
        user_id: str,
        session_id: str,
        trace_id: str,
        result: PolicyHarnessResult,
    ) -> None:
        now = datetime.now(UTC)
        orchestration = result.orchestration or {}
        departments = orchestration.get("completed_departments", [])
        if not isinstance(departments, list):
            departments = []
        department_text = ",".join(map(str, departments)) or "none"
        item = MemoryItem(
            id=f"episode:{trace_id}",
            memory_type=MemoryType.EPISODIC,
            user_id=user_id,
            session_id=session_id,
            content=(
                "Multi-agent policy consultation completed; "
                f"status={result.status.value}; departments={department_text}"
            ),
            confidence=1.0,
            source_trace_id=trace_id,
            consented=False,
            created_at=now,
            updated_at=now,
        )
        await self._repository.upsert(item)


def scope_memory_snapshot(snapshot: dict[str, object], dept_id: str) -> dict[str, object]:
    """Filter only organisational/procedural entries by immutable department.

    User, working and episodic records remain root-provided read-only context;
    organisational and procedural entries cannot leak between departments.
    """

    items = snapshot.get("items")
    if not isinstance(items, list):
        return {**snapshot, "items": []}
    scoped: list[dict[str, object]] = []
    for raw_item in items:
        if not isinstance(raw_item, dict):
            continue
        item = {str(key): value for key, value in raw_item.items()}
        memory_type = item.get("memory_type")
        owner_dept = item.get("department_id")
        if memory_type in {
            MemoryType.ORGANIZATIONAL.value,
            MemoryType.PROCEDURAL.value,
        } and owner_dept not in {None, dept_id}:
            continue
        scoped.append(item)
    return {**snapshot, "items": scoped, "department_id": dept_id, "read_only": True}


def memory_trace_summary(snapshot: dict[str, object]) -> list[str]:
    """Persist identity/type only; raw memory content stays out of request traces."""

    items = snapshot.get("items")
    if not isinstance(items, list):
        return []
    values: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        memory_id = item.get("id")
        memory_type = item.get("memory_type")
        if isinstance(memory_id, str) and isinstance(memory_type, str):
            values.append(f"{memory_type}:{memory_id}")
    return values

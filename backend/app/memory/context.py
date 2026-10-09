from collections.abc import Iterable
from typing import Protocol

from backend.app.memory.models import MemoryContext, MemoryItem, MemoryType


def estimate_tokens(text: str) -> int:
    """A conservative deterministic estimate suitable for enforcing a local prompt budget."""

    if not text.strip():
        return 0
    return max(1, (len(text) + 3) // 4)


class MemoryContextBuilder:
    """Combines non-factual memories in the specified priority order under a token budget."""

    def build(
        self,
        *,
        working: Iterable[MemoryItem],
        semantic: Iterable[MemoryItem],
        episodic: Iterable[MemoryItem],
        organizational: Iterable[MemoryItem],
        procedural: Iterable[MemoryItem],
        token_budget: int,
    ) -> MemoryContext:
        if token_budget <= 0:
            raise ValueError("Memory token budget must be positive.")
        del procedural
        accepted: list[MemoryItem] = []
        estimated_tokens = 0
        truncated = False
        for item in [*working, *semantic, *episodic, *organizational]:
            item_tokens = estimate_tokens(item.content)
            if estimated_tokens + item_tokens > token_budget:
                truncated = True
                continue
            accepted.append(item)
            estimated_tokens += item_tokens
        return MemoryContext(
            items=accepted,
            token_budget=token_budget,
            estimated_tokens=estimated_tokens,
            truncated=truncated,
        )


class ContextMemoryRepository(Protocol):
    async def list_context_candidates(
        self, *, user_id: str, department_id: str | None, limit: int = 100
    ) -> list[MemoryItem]: ...


class WorkingMemoryStore(Protocol):
    async def get(self, session_id: str) -> MemoryItem | None: ...


class MemoryContextService:
    """Collect five memory planes while keeping them separate from policy evidence."""

    def __init__(
        self,
        *,
        repository: ContextMemoryRepository,
        working_memory: WorkingMemoryStore,
        builder: MemoryContextBuilder | None = None,
    ) -> None:
        self._repository = repository
        self._working_memory = working_memory
        self._builder = builder or MemoryContextBuilder()

    async def build(
        self,
        *,
        user_id: str,
        session_id: str,
        query: str,
        department_id: str | None,
        token_budget: int,
    ) -> MemoryContext:
        if not query.strip():
            raise ValueError("Memory context query must not be blank.")
        working_item = await self._working_memory.get(session_id)
        candidates = await self._repository.list_context_candidates(
            user_id=user_id,
            department_id=department_id,
        )
        semantic = _items_of_type(candidates, MemoryType.USER_SEMANTIC)
        episodic = _items_of_type(candidates, MemoryType.EPISODIC)
        organizational = _items_of_type(candidates, MemoryType.ORGANIZATIONAL)
        procedural = _items_of_type(candidates, MemoryType.PROCEDURAL)
        return self._builder.build(
            working=[working_item] if working_item else [],
            semantic=semantic,
            episodic=episodic,
            organizational=organizational,
            procedural=procedural,
            token_budget=token_budget,
        )


def _items_of_type(items: Iterable[MemoryItem], memory_type: MemoryType) -> list[MemoryItem]:
    return [item for item in items if item.memory_type is memory_type]

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class MemoryType(StrEnum):
    WORKING = "WORKING"
    EPISODIC = "EPISODIC"
    USER_SEMANTIC = "USER_SEMANTIC"
    ORGANIZATIONAL = "ORGANIZATIONAL"
    PROCEDURAL = "PROCEDURAL"


class MemoryItem(BaseModel):
    id: str
    memory_type: MemoryType
    user_id: str | None = None
    session_id: str | None = None
    department_id: str | None = None
    content: str = Field(min_length=1, max_length=8_000)
    confidence: float = Field(ge=0, le=1)
    source_trace_id: str | None = None
    consented: bool = False
    created_at: datetime
    updated_at: datetime


class MemoryContext(BaseModel):
    items: list[MemoryItem] = Field(default_factory=list)
    token_budget: int = Field(gt=0)
    estimated_tokens: int = Field(ge=0)
    truncated: bool = False

    def render_for_llm(self) -> str:
        """Render memory as non-evidentiary context and never as a citation source."""

        return "\n".join(
            "[memory:"
            f"{item.memory_type.value.lower()} id={item.id} "
            f"confidence={item.confidence:.2f}] {item.content}"
            for item in self.items
        )

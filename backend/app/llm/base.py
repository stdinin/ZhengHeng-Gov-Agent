from dataclasses import dataclass
from typing import Protocol, TypeVar

from pydantic import BaseModel

StructuredModel = TypeVar("StructuredModel", bound=BaseModel)


@dataclass(frozen=True, slots=True)
class LLMTokenUsage:
    """Provider-reported token counts, deliberately excluding credentials and prompts."""

    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    cached_input_tokens: int | None
    uncached_input_tokens: int | None


class LLMClient(Protocol):
    async def structured(
        self,
        *,
        system: str,
        user: str,
        schema: type[StructuredModel],
        fixture_name: str | None = None,
    ) -> StructuredModel: ...

    async def text(self, *, system: str, user: str, fixture_name: str | None = None) -> str: ...

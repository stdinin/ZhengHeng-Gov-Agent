from typing import Protocol, TypeVar

from pydantic import BaseModel

StructuredModel = TypeVar("StructuredModel", bound=BaseModel)


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

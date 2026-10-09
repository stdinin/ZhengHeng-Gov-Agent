from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel

from backend.app.llm.base import StructuredModel


class FakeLLMExhausted(LookupError):
    """The deterministic fixture omitted a response; FakeLLM must not invent one."""


class FakeLLM:
    """Deterministic development provider driven only by named fixture data."""

    def __init__(
        self,
        *,
        structured_fixtures: Mapping[str, Mapping[str, Any] | BaseModel] | None = None,
        text_fixtures: Mapping[str, str] | None = None,
    ) -> None:
        self._structured_fixtures = dict(structured_fixtures or {})
        self._text_fixtures = dict(text_fixtures or {})

    async def structured(
        self,
        *,
        system: str,
        user: str,
        schema: type[StructuredModel],
        fixture_name: str | None = None,
    ) -> StructuredModel:
        fixture = self._structured_fixtures.get(fixture_name or "")
        if fixture is None:
            raise FakeLLMExhausted(f"Structured fixture missing: {fixture_name or '<unnamed>'}.")
        if isinstance(fixture, BaseModel):
            return schema.model_validate(fixture.model_dump(mode="python"))
        return schema.model_validate(fixture)

    async def text(self, *, system: str, user: str, fixture_name: str | None = None) -> str:
        fixture = self._text_fixtures.get(fixture_name or "")
        if fixture is None:
            raise FakeLLMExhausted(f"Text fixture missing: {fixture_name or '<unnamed>'}.")
        return fixture

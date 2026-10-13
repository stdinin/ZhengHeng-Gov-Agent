"""Deterministic runtime used only for unit and fixture-driven integration tests."""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel

from backend.app.runtime.base import (
    RuntimeHealth,
    RuntimeMessage,
    RuntimeNode,
    RuntimeResult,
)
from backend.app.runtime.errors import AgentRuntimeError


class FakeRuntime:
    def __init__(
        self,
        *,
        fixtures: Mapping[RuntimeNode, Mapping[str, Any]] | None = None,
        errors: Mapping[RuntimeNode, Exception] | None = None,
        backend_name: str = "fake",
    ) -> None:
        self._fixtures = dict(fixtures or {})
        self._errors = dict(errors or {})
        self._backend_name = backend_name

    async def invoke[ModelT: BaseModel](
        self,
        *,
        node: RuntimeNode,
        agent_id: str,
        dept_id: str | None,
        trace_id: str,
        system_prompt: str,
        messages: list[RuntimeMessage],
        response_model: type[ModelT],
        timeout_ms: int,
    ) -> RuntimeResult[ModelT]:
        del agent_id, dept_id, trace_id, system_prompt, messages, timeout_ms
        started = time.perf_counter()
        error = self._errors.get(node)
        if error is not None:
            raise error
        fixture = self._fixtures.get(node)
        if fixture is None:
            raise AgentRuntimeError(f"Fake runtime fixture missing: {node.value}.")
        return RuntimeResult(
            output=response_model.model_validate(fixture),
            backend_requested=self._backend_name,
            backend_used=self._backend_name,
            latency_ms=(time.perf_counter() - started) * 1_000,
        )

    async def healthcheck(self) -> RuntimeHealth:
        return RuntimeHealth(backend=self._backend_name, ready=True)

    async def close(self) -> None:
        return None

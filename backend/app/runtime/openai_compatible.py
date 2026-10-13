"""OpenAI-compatible implementation of the controlled semantic runtime."""

from __future__ import annotations

import time

import httpx
from pydantic import BaseModel

from backend.app.config import Settings
from backend.app.llm.openai_compatible import OpenAICompatibleLLM
from backend.app.runtime.base import (
    RuntimeHealth,
    RuntimeMessage,
    RuntimeNode,
    RuntimeResult,
)


class OpenAICompatibleRuntime:
    """Reuse the existing structured provider behind the V1.1 runtime contract."""

    def __init__(self, settings: Settings, *, client: httpx.AsyncClient | None = None) -> None:
        self._provider = OpenAICompatibleLLM(settings, client=client)

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
        del node, agent_id, dept_id, trace_id, timeout_ms
        started = time.perf_counter()
        message_text = "\n\n".join(
            f"[{message.role}] {message.content}" for message in messages
        )
        output = await self._provider.structured(
            system=system_prompt,
            user=message_text,
            schema=response_model,
        )
        return RuntimeResult(
            output=output,
            backend_requested="openai_compatible",
            backend_used="openai_compatible",
            latency_ms=(time.perf_counter() - started) * 1_000,
        )

    async def healthcheck(self) -> RuntimeHealth:
        return RuntimeHealth(backend="openai_compatible", ready=True)

    async def close(self) -> None:
        await self._provider.close()

"""Typed, tool-free boundary between Python governance and semantic runtimes."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, Protocol

from pydantic import BaseModel, Field


class RuntimeNode(StrEnum):
    INTENT = "intent"
    REWRITE = "rewrite"
    ROUTE = "route"
    ANSWER = "answer"
    VERIFY = "verify"
    AGGREGATE = "aggregate"
    REFLECT = "reflect"


class RuntimeMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, max_length=16_000)


class RuntimeHealth(BaseModel):
    backend: str
    ready: bool
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class RuntimeResult[ModelT: BaseModel]:
    output: ModelT
    backend_requested: str
    backend_used: str
    latency_ms: float
    fallback_reason: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


class AgentRuntime(Protocol):
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
    ) -> RuntimeResult[ModelT]: ...

    async def healthcheck(self) -> RuntimeHealth: ...

    async def close(self) -> None: ...

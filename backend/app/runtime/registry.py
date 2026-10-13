"""Fallback composition and compatibility adapter for existing fixed DAG nodes."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from backend.app.llm.base import StructuredModel
from backend.app.runtime.base import (
    AgentRuntime,
    RuntimeHealth,
    RuntimeMessage,
    RuntimeNode,
    RuntimeResult,
)
from backend.app.runtime.context import (
    RuntimeInvocationAudit,
    current_runtime_request,
    drain_runtime_audits,
    record_runtime_audit,
)
from backend.app.runtime.errors import AgentRuntimeError
from backend.app.runtime.fake import FakeRuntime
from backend.app.runtime.openai_compatible import OpenAICompatibleRuntime
from backend.app.runtime.pi import PiRuntimeAdapter

if TYPE_CHECKING:
    from backend.app.config import Settings

_FIXTURE_NODES = {
    "intent": RuntimeNode.INTENT,
    "rewrite": RuntimeNode.REWRITE,
    "route": RuntimeNode.ROUTE,
    "answer": RuntimeNode.ANSWER,
    "verify_claim": RuntimeNode.VERIFY,
    "aggregate": RuntimeNode.AGGREGATE,
    "reflect": RuntimeNode.REFLECT,
}


class FallbackAgentRuntime:
    def __init__(self, *, primary: AgentRuntime, fallback: AgentRuntime) -> None:
        self._primary = primary
        self._fallback = fallback

    @property
    def fallback(self) -> AgentRuntime:
        """Selected fallback adapter, exposed only for non-secret configuration checks."""

        return self._fallback

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
        kwargs: dict[str, Any] = {
            "node": node,
            "agent_id": agent_id,
            "dept_id": dept_id,
            "trace_id": trace_id,
            "system_prompt": system_prompt,
            "messages": messages,
            "response_model": response_model,
            "timeout_ms": timeout_ms,
        }
        try:
            return await self._primary.invoke(**kwargs)
        except Exception as error:
            result = await self._fallback.invoke(**kwargs)
            return replace(
                result,
                backend_requested="pi",
                fallback_reason=type(error).__name__,
            )

    async def healthcheck(self) -> RuntimeHealth:
        primary = await self._primary.healthcheck()
        return primary if primary.ready else await self._fallback.healthcheck()

    async def close(self) -> None:
        await self._primary.close()
        await self._fallback.close()


class _TextResponse(BaseModel):
    content: str


class RuntimeLLMClient:
    """Adapt AgentRuntime to the legacy LLMClient protocol without widening permissions."""

    def __init__(self, runtime: AgentRuntime) -> None:
        self._runtime = runtime

    async def structured(
        self,
        *,
        system: str,
        user: str,
        schema: type[StructuredModel],
        fixture_name: str | None = None,
    ) -> StructuredModel:
        node = _FIXTURE_NODES.get(fixture_name or "")
        if node is None:
            raise AgentRuntimeError(f"No runtime node mapping for {fixture_name!r}.")
        result = await self._invoke(
            node=node,
            system_prompt=system,
            messages=[RuntimeMessage(role="user", content=user)],
            response_model=schema,
            timeout_ms=20_000,
        )
        return result.output

    async def text(self, *, system: str, user: str, fixture_name: str | None = None) -> str:
        node = _FIXTURE_NODES.get(fixture_name or "")
        if node is None:
            raise AgentRuntimeError(f"No runtime node mapping for {fixture_name!r}.")
        result = await self._invoke(
            node=node,
            system_prompt=system,
            messages=[RuntimeMessage(role="user", content=user)],
            response_model=_TextResponse,
            timeout_ms=20_000,
        )
        return result.output.content

    async def close(self) -> None:
        await self._runtime.close()

    @staticmethod
    def drain_runtime_audits() -> list[RuntimeInvocationAudit]:
        return drain_runtime_audits()

    async def _invoke[ModelT: BaseModel](
        self,
        *,
        node: RuntimeNode,
        system_prompt: str,
        messages: list[RuntimeMessage],
        response_model: type[ModelT],
        timeout_ms: int,
    ) -> RuntimeResult[ModelT]:
        context = current_runtime_request()
        result = await self._runtime.invoke(
            node=node,
            agent_id=context.agent_id,
            dept_id=context.dept_id,
            trace_id=context.trace_id,
            system_prompt=system_prompt,
            messages=messages,
            response_model=response_model,
            timeout_ms=timeout_ms,
        )
        record_runtime_audit(
            RuntimeInvocationAudit(
                trace_id=context.trace_id,
                agent_id=context.agent_id,
                dept_id=context.dept_id,
                runtime_backend_requested=result.backend_requested,
                runtime_backend_used=result.backend_used,
                runtime_fallback_reason=result.fallback_reason,
                runtime_latency_ms=result.latency_ms,
            )
        )
        return result


def build_agent_runtime(settings: Settings) -> AgentRuntime:
    """Build an opt-in V1.1 semantic runtime without changing legacy defaults."""

    backend = settings.agent_runtime_backend
    if backend == "fake":
        primary: AgentRuntime = FakeRuntime()
    elif backend == "openai_compatible":
        primary = OpenAICompatibleRuntime(settings)
    elif backend == "pi":
        primary = PiRuntimeAdapter(
            base_url=settings.pi_runtime_base_url,
            service_token=settings.internal_service_token or "",
            connect_timeout_ms=settings.pi_runtime_connect_timeout_ms,
        )
    else:
        raise ValueError("AGENT_RUNTIME_BACKEND=legacy has no runtime adapter.")

    if settings.agent_runtime_fallback == "none":
        return primary
    if settings.agent_runtime_fallback == "fake":
        fallback: AgentRuntime = FakeRuntime()
    else:
        fallback = OpenAICompatibleRuntime(settings)
    return FallbackAgentRuntime(primary=primary, fallback=fallback)

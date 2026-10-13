"""HTTP adapter for the internal, tool-free Node Pi Runtime service."""

from __future__ import annotations

import time
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from backend.app.runtime.base import (
    RuntimeHealth,
    RuntimeMessage,
    RuntimeNode,
    RuntimeResult,
)
from backend.app.runtime.errors import PiRuntimeError

_MAX_SCHEMA_CHARS = 24_000


class PiRuntimeAdapter:
    def __init__(
        self,
        *,
        base_url: str,
        service_token: str,
        connect_timeout_ms: int = 3_000,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._service_token = service_token
        self._connect_timeout_seconds = connect_timeout_ms / 1_000
        self._client = client or httpx.AsyncClient(timeout=self._connect_timeout_seconds)
        self._owns_client = client is None

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
        schema = response_model.model_json_schema()
        if len(str(schema)) > _MAX_SCHEMA_CHARS:
            raise PiRuntimeError("Pi response schema exceeds the internal service limit.")
        body = {
            "request_id": trace_id,
            "trace_id": trace_id,
            "agent_id": agent_id,
            "dept_id": dept_id,
            "node": node.value,
            "system_prompt": system_prompt,
            "messages": [message.model_dump(mode="json") for message in messages],
            "response_schema": schema,
            "timeout_ms": timeout_ms,
            "metadata": {},
        }
        started = time.perf_counter()
        try:
            response = await self._client.post(
                f"{self._base_url}/internal/v1/invoke",
                headers={"X-Internal-Service-Token": self._service_token},
                json=body,
                timeout=httpx.Timeout(
                    timeout=timeout_ms / 1_000,
                    connect=self._connect_timeout_seconds,
                ),
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or payload.get("ok") is not True:
                raise PiRuntimeError("Pi runtime returned a non-success response.")
            output = response_model.model_validate(payload.get("output_json"))
        except (httpx.HTTPError, ValidationError, TypeError, ValueError) as error:
            raise PiRuntimeError("Pi runtime invocation failed.") from error
        usage_value = payload.get("usage")
        usage = usage_value if isinstance(usage_value, dict) else {}
        return RuntimeResult(
            output=output,
            backend_requested="pi",
            backend_used="pi",
            latency_ms=float(payload.get("latency_ms", (time.perf_counter() - started) * 1_000)),
            input_tokens=_nonnegative_int(usage.get("input_tokens")),
            output_tokens=_nonnegative_int(usage.get("output_tokens")),
            total_tokens=_nonnegative_int(usage.get("total_tokens")),
        )

    async def healthcheck(self) -> RuntimeHealth:
        try:
            response = await self._client.get(
                f"{self._base_url}/internal/health/ready",
                headers={"X-Internal-Service-Token": self._service_token},
                timeout=3,
            )
            response.raise_for_status()
            payload: Any = response.json()
        except (httpx.HTTPError, TypeError, ValueError) as error:
            return RuntimeHealth(backend="pi", ready=False, detail=type(error).__name__)
        return RuntimeHealth(backend="pi", ready=bool(payload.get("ready")))

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def _nonnegative_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
        return None
    return int(value)

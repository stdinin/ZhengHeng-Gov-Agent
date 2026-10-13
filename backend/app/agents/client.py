"""Authenticated, internal-only client for statically registered department agents."""

from __future__ import annotations

import httpx

from backend.app.agents.models import (
    DepartmentAgentDefinition,
    DepartmentAgentResult,
    DepartmentExecutionRequest,
)


class DepartmentAgentClientError(RuntimeError):
    """A registered department endpoint did not return a trusted internal result."""


class HTTPDepartmentAgentClient:
    def __init__(
        self, *, service_token: str, client: httpx.AsyncClient | None = None
    ) -> None:
        self._service_token = service_token
        self._client = client or httpx.AsyncClient()
        self._owns_client = client is None

    async def execute(
        self, definition: DepartmentAgentDefinition, request: DepartmentExecutionRequest
    ) -> DepartmentAgentResult:
        try:
            response = await self._client.post(
                f"{definition.base_url.rstrip('/')}/internal/v1/execute",
                headers={"X-Internal-Service-Token": self._service_token},
                json=request.model_dump(mode="json"),
                timeout=definition.timeout_ms / 1_000,
            )
            response.raise_for_status()
            return DepartmentAgentResult.model_validate(response.json())
        except (httpx.HTTPError, TypeError, ValueError) as error:
            raise DepartmentAgentClientError("Department agent invocation failed.") from error

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

"""Small, admin-only read model for the V1.1 static agent topology."""

from __future__ import annotations

from collections import defaultdict
from typing import cast

import httpx
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from backend.app.agents.models import DepartmentAgentDefinition
from backend.app.agents.registry import department_agent_registry_from_settings
from backend.app.api.evolution import _require_admin
from backend.app.config import Settings
from backend.app.observability.tracing import TraceRecord
from backend.app.storage.trace_repository import TraceStore

router = APIRouter(prefix="/api/v1/admin/agent-network", tags=["admin", "agents"])


class AgentNetworkMember(BaseModel):
    agent_id: str
    dept_id: str
    health: str
    runtime_backend: str
    recent_latency_ms: float | None = None
    timeout_count: int = Field(ge=0)
    latest_child_trace_id: str | None = None


class AgentNetworkResponse(BaseModel):
    orchestrator_health: str
    pi_runtime_health: str
    members: list[AgentNetworkMember]


@router.get("", response_model=AgentNetworkResponse)
async def agent_network(request: Request) -> AgentNetworkResponse:
    await _require_admin(request)
    settings: Settings = request.app.state.settings
    traces = await _trace_store(request).list_recent(limit=200)
    child_traces = [trace for trace in traces if trace.trace_kind == "child" and trace.dept_id]
    by_department: dict[str, list[TraceRecord]] = defaultdict(list)
    for trace in child_traces:
        if trace.dept_id is not None:
            by_department[trace.dept_id].append(trace)
    registry = department_agent_registry_from_settings(settings)
    async with httpx.AsyncClient(timeout=2) as client:
        pi_health = await _pi_health(settings, client)
        members = [
            await _member(definition, by_department.get(definition.dept_id, []), client)
            for definition in registry.enabled_definitions()
        ]
    return AgentNetworkResponse(
        orchestrator_health="ready",
        pi_runtime_health=pi_health,
        members=members,
    )


def _trace_store(request: Request) -> TraceStore:
    return cast(TraceStore, request.app.state.trace_store)


async def _pi_health(settings: Settings, client: httpx.AsyncClient) -> str:
    if settings.agent_runtime_backend != "pi":
        return "not_configured"
    try:
        response = await client.get(
            f"{settings.pi_runtime_base_url.rstrip('/')}/internal/health/ready",
            headers={"X-Internal-Service-Token": settings.internal_service_token or ""},
        )
        return "healthy" if response.is_success else "unhealthy"
    except httpx.HTTPError:
        return "unreachable"


async def _member(
    definition: DepartmentAgentDefinition, traces: list[TraceRecord], client: httpx.AsyncClient
) -> AgentNetworkMember:
    agent_id = definition.agent_id
    dept_id = definition.dept_id
    base_url = definition.base_url.rstrip("/")
    try:
        response = await client.get(f"{base_url}/api/v1/health/live")
        health = "healthy" if response.is_success else "unhealthy"
    except httpx.HTTPError:
        health = "unreachable"
    latest = traces[0] if traces else None
    runtime_backend = _runtime_backend(latest) if latest is not None else "unknown"
    timeout_count = sum("timeout" in trace.errors for trace in traces)
    return AgentNetworkMember(
        agent_id=agent_id,
        dept_id=dept_id,
        health=health,
        runtime_backend=runtime_backend,
        recent_latency_ms=(latest.timings_ms.get("total") if latest is not None else None),
        timeout_count=timeout_count,
        latest_child_trace_id=latest.id if latest is not None else None,
    )


def _runtime_backend(trace: TraceRecord) -> str:
    for node in reversed(trace.nodes):
        if node.runtime_events:
            backend = node.runtime_events[-1].get("runtime_backend_used")
            if isinstance(backend, str):
                return backend
    return "unknown"

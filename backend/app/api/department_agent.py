"""Private API surface for one immutable department-agent process."""

from datetime import UTC, datetime
from secrets import compare_digest
from typing import cast

from fastapi import APIRouter, Request

from backend.app.agents.department_service import DepartmentAgentService
from backend.app.agents.models import DepartmentAgentResult, DepartmentExecutionRequest
from backend.app.api.errors import ApiError
from backend.app.config import Settings

router = APIRouter(prefix="/internal", include_in_schema=False)


def _executor(request: Request) -> DepartmentAgentService:
    executor = getattr(request.app.state, "department_executor", None)
    if executor is None:
        raise ApiError(
            status_code=503,
            code="DEPARTMENT_AGENT_UNAVAILABLE",
            message="Department agent execution is unavailable in this process.",
        )
    return cast(DepartmentAgentService, executor)


def _require_internal_token(request: Request) -> None:
    settings: Settings = request.app.state.settings
    configured = settings.internal_service_token
    supplied = request.headers.get("X-Internal-Service-Token", "")
    if not configured:
        raise ApiError(
            status_code=503,
            code="INTERNAL_AUTH_UNCONFIGURED",
            message="Internal service authentication is not configured.",
        )
    if not compare_digest(supplied, configured):
        raise ApiError(
            status_code=401,
            code="INTERNAL_AUTH_REQUIRED",
            message="Internal service token is required.",
        )


@router.get("/health/live")
async def live(request: Request) -> dict[str, str]:
    _require_internal_token(request)
    return {"status": "ok", "role": "department_agent"}


@router.get("/health/ready")
async def ready(request: Request) -> dict[str, str]:
    _require_internal_token(request)
    _executor(request)
    return {"status": "ok", "role": "department_agent"}


@router.post("/v1/execute", response_model=DepartmentAgentResult)
async def execute(
    payload: DepartmentExecutionRequest, request: Request
) -> DepartmentAgentResult:
    _require_internal_token(request)
    return await _executor(request).execute(payload, now=datetime.now(UTC))

from fastapi import APIRouter, Request

from backend.app.api.errors import ApiError
from backend.app.config import Settings
from backend.app.storage.readiness import DependencyStatus

router = APIRouter(prefix="/api/v1/health", tags=["health"])


@router.get("/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def ready(request: Request) -> dict[str, object]:
    settings: Settings = request.app.state.settings
    checker = request.app.state.readiness_checker
    statuses: dict[str, DependencyStatus] = await checker(settings)
    if not all(status.ready for status in statuses.values()):
        dependency_details = {name: status.model_dump() for name, status in statuses.items()}
        raise ApiError(
            status_code=503,
            code="DEPENDENCIES_UNREADY",
            message="One or more required dependencies are unavailable.",
            details={"dependencies": dependency_details},
        )
    return {
        "status": "ok",
        "dependencies": {name: status.model_dump() for name, status in statuses.items()},
    }

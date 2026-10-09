from typing import cast

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse

from backend.app.observability.metrics import MetricsRegistry

router = APIRouter(tags=["observability"])


@router.get("/metrics", include_in_schema=False)
async def metrics(request: Request) -> PlainTextResponse:
    registry = cast(MetricsRegistry, request.app.state.metrics_registry)
    return PlainTextResponse(registry.render_prometheus(), media_type="text/plain; version=0.0.4")

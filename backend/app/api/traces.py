from typing import cast

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from backend.app.api.errors import ApiError
from backend.app.security.auth import decode_access_token
from backend.app.storage.trace_repository import TraceStore
from backend.app.storage.users import UserStore

router = APIRouter(prefix="/api/v1/traces", tags=["traces"])


class TraceSummary(BaseModel):
    id: str
    session_id: str
    status: str
    created_at: object


class TraceListResponse(BaseModel):
    items: list[TraceSummary]


def _trace_store(request: Request) -> TraceStore:
    return cast(TraceStore, request.app.state.trace_store)


def _user_store(request: Request) -> UserStore:
    return cast(UserStore, request.app.state.user_store)


async def _authenticate(request: Request) -> str:
    authorization = request.headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise ApiError(status_code=401, code="AUTH_REQUIRED", message="Bearer token is required.")
    try:
        user_id = decode_access_token(token, request.app.state.settings)
    except ValueError as error:
        raise ApiError(status_code=401, code="INVALID_TOKEN", message=str(error)) from error
    if await _user_store(request).get_by_id(user_id) is None:
        raise ApiError(
            status_code=401,
            code="INVALID_TOKEN",
            message="Token user no longer exists.",
        )
    return user_id


@router.get("", response_model=TraceListResponse)
async def list_traces(
    request: Request,
    session_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
) -> TraceListResponse:
    user_id = await _authenticate(request)
    traces = await _trace_store(request).list_for_user(
        user_id,
        session_id=session_id,
        limit=limit,
    )
    return TraceListResponse(
        items=[
            TraceSummary(
                id=trace.id,
                session_id=trace.session_id,
                status=trace.status.value,
                created_at=trace.created_at,
            )
            for trace in traces
        ]
    )


@router.get("/{trace_id}")
async def get_trace(trace_id: str, request: Request) -> dict[str, object]:
    user_id = await _authenticate(request)
    trace = await _trace_store(request).get(trace_id)
    if trace is None:
        raise ApiError(
            status_code=404,
            code="TRACE_NOT_FOUND",
            message=f"Trace not found: {trace_id}",
        )
    if trace.user_id != user_id:
        raise ApiError(
            status_code=403,
            code="TRACE_FORBIDDEN",
            message="Trace access is not allowed.",
        )
    return {
        "id": trace.id,
        "session_id": trace.session_id,
        "query": trace.query,
        "normalized_query": trace.normalized_query,
        "intent": trace.intent,
        "rewritten_queries": trace.rewritten_queries,
        "department_routes": trace.department_routes,
        "memory_context": trace.memory_context,
        "matched_strategies": trace.matched_strategies,
        "retrieval_hits": trace.retrieval_hits,
        "retrieval_metadata": trace.retrieval_metadata,
        "nodes": [
            {
                "node": node.node,
                "input_summary": node.input_summary,
                "output_summary": node.output_summary,
                "latency_ms": node.latency_ms,
                "fallback": node.fallback,
                "token_usage": node.token_usage,
                "applied_strategy_ids": node.applied_strategy_ids,
            }
            for node in trace.nodes
        ],
        "status": trace.status.value,
        "answer": trace.answer,
        "citations": trace.citations,
        "verification": trace.verification,
        "retry_count": trace.retry_count,
        "errors": trace.errors,
        "timings_ms": trace.timings_ms,
        "created_at": trace.created_at,
        "updated_at": trace.updated_at,
    }

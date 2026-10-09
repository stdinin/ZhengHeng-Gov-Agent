import time
from collections.abc import AsyncIterator
from datetime import datetime
from typing import cast
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.app.api.errors import ApiError
from backend.app.harness.chat_service import ChatService, ChatServiceUnavailable
from backend.app.harness.citations import Citation
from backend.app.harness.state import AnswerStatus
from backend.app.observability.metrics import MetricsRegistry, is_fixed_dag_node
from backend.app.security.auth import decode_access_token
from backend.app.storage.trace_repository import TraceStore
from backend.app.storage.users import UserStore

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])


class ChatRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4_000)
    session_id: str | None = Field(default=None, min_length=1, max_length=128)


class CitationResponse(BaseModel):
    id: str
    chunk_id: str
    document_id: str
    version_id: str
    title: str
    department: str
    status: str
    excerpt: str
    document_number: str | None = None
    written_date: str | None = None
    source_url: str | None = None

    @classmethod
    def from_citation(cls, citation: Citation) -> "CitationResponse":
        return cls(
            id=citation.id,
            chunk_id=citation.chunk_id,
            document_id=citation.document_id,
            version_id=citation.version_id,
            title=citation.title,
            department=citation.department,
            status=citation.status.value,
            excerpt=citation.excerpt,
            document_number=citation.document_number,
            written_date=citation.written_date,
            source_url=citation.source_url,
        )


class VerificationResponse(BaseModel):
    passed: bool
    retryable: bool
    warnings: list[str]


class ChatResponse(BaseModel):
    trace_id: str
    session_id: str
    status: AnswerStatus
    answer: str
    citations: list[CitationResponse]
    verification: VerificationResponse
    attempts: int
    warnings: list[str]


class SessionTraceResponse(BaseModel):
    trace_id: str
    status: AnswerStatus
    answer: str
    citations: list[dict[str, object]]
    created_at: datetime


class ChatSessionResponse(BaseModel):
    session_id: str
    traces: list[SessionTraceResponse]


def _chat_service(request: Request) -> ChatService:
    return cast(ChatService, request.app.state.chat_service)


def _user_store(request: Request) -> UserStore:
    return cast(UserStore, request.app.state.user_store)


def _metrics(request: Request) -> MetricsRegistry:
    return cast(MetricsRegistry, request.app.state.metrics_registry)


def _trace_store(request: Request) -> TraceStore:
    return cast(TraceStore, request.app.state.trace_store)


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


async def _run_chat(payload: ChatRequest, request: Request) -> ChatResponse:
    user_id = await _authenticate(request)
    session_id = payload.session_id or str(uuid4())
    started = time.perf_counter()
    try:
        result = await _chat_service(request).answer(
            query=payload.query,
            trace_id=request.state.trace_id,
            session_id=session_id,
            user_id=user_id,
        )
    except ChatServiceUnavailable as error:
        _metrics(request).record_chat(
            status="ERROR",
            latency_seconds=time.perf_counter() - started,
        )
        raise ApiError(
            status_code=503,
            code="RETRIEVAL_UNAVAILABLE",
            message=str(error),
        ) from error
    elapsed = time.perf_counter() - started
    verification = result.state.verification
    if verification is None:
        _metrics(request).record_chat(status="ERROR", latency_seconds=elapsed)
        raise ApiError(
            status_code=503,
            code="VERIFICATION_UNAVAILABLE",
            message="The chat harness returned without a verification result.",
        )
    _metrics(request).record_chat(status=result.status.value, latency_seconds=elapsed)
    _metrics(request).record_verification(passed=verification.passed)
    for node, latency_ms in result.state.timings_ms.items():
        if is_fixed_dag_node(node):
            _metrics(request).record_node(node=node, latency_seconds=latency_ms / 1_000)
    return ChatResponse(
        trace_id=request.state.trace_id,
        session_id=session_id,
        status=result.status,
        answer=result.answer,
        citations=[CitationResponse.from_citation(item) for item in result.citations],
        verification=VerificationResponse(
            passed=verification.passed,
            retryable=verification.retryable,
            warnings=verification.warnings,
        ),
        attempts=result.attempts,
        warnings=result.warnings,
    )


@router.post("", response_model=ChatResponse)
async def chat(payload: ChatRequest, request: Request) -> ChatResponse:
    return await _run_chat(payload, request)


@router.post("/stream")
async def chat_stream(payload: ChatRequest, request: Request) -> StreamingResponse:
    response = await _run_chat(payload, request)

    async def events() -> AsyncIterator[str]:
        yield f"event: final\ndata: {response.model_dump_json()}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


@router.get("/sessions/{session_id}", response_model=ChatSessionResponse)
async def chat_session(session_id: str, request: Request) -> ChatSessionResponse:
    user_id = await _authenticate(request)
    traces = await _trace_store(request).list_for_user(
        user_id,
        session_id=session_id,
        limit=100,
    )
    return ChatSessionResponse(
        session_id=session_id,
        traces=[
            SessionTraceResponse(
                trace_id=trace.id,
                status=trace.status,
                answer=trace.answer,
                citations=trace.citations,
                created_at=trace.created_at,
            )
            for trace in traces
        ],
    )

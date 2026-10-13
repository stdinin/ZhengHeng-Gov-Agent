from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from inspect import isawaitable
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from backend.app.agents.composition import build_department_agent_executor
from backend.app.agents.department_service import DepartmentAgentService
from backend.app.agents.orchestrator_composition import build_multi_agent_chat_service
from backend.app.api.agent_network import router as agent_network_router
from backend.app.api.auth import router as auth_router
from backend.app.api.chat import router as chat_router
from backend.app.api.department_agent import router as department_agent_router
from backend.app.api.documents import router as documents_router
from backend.app.api.errors import ApiError
from backend.app.api.evolution import router as evolution_router
from backend.app.api.feedback import router as feedback_router
from backend.app.api.health import router as health_router
from backend.app.api.memory import router as memory_router
from backend.app.api.metrics import router as metrics_router
from backend.app.api.traces import router as traces_router
from backend.app.config import Settings
from backend.app.evolution.frozen_replay import FrozenTraceReplayExecutor
from backend.app.evolution.repository import EvolutionRepository, MongoEvolutionRepository
from backend.app.evolution.service import EvolutionService, FeedbackService
from backend.app.harness.chat_service import ChatService, HarnessChatService
from backend.app.harness.composition import build_chat_service
from backend.app.ingestion.indexer import DocumentIndexer
from backend.app.memory.repository import MemoryRepository, MongoMemoryRepository
from backend.app.observability.metrics import MetricsRegistry
from backend.app.retrieval.bm25 import OpenSearchBM25
from backend.app.retrieval.dense import MilvusDenseIndex
from backend.app.retrieval.embedding import build_embedding_provider
from backend.app.storage.document_repository import DocumentStore, MongoDocumentRepository
from backend.app.storage.readiness import DependencyStatus, check_dependencies
from backend.app.storage.trace_repository import MongoTraceStore, TraceStore
from backend.app.storage.users import MongoUserStore, UserStore

ReadinessChecker = Callable[[Settings], Awaitable[dict[str, DependencyStatus]]]


@asynccontextmanager
async def _application_lifespan(app: FastAPI) -> AsyncIterator[None]:
    try:
        yield
    finally:
        await _close_runtime_resources(app)


async def _close_runtime_resources(app: FastAPI) -> None:
    """Close every app-owned resource that exposes an explicit shutdown method."""

    names = (
        "user_store",
        "document_repository",
        "document_indexer",
        "chat_service",
        "department_executor",
        "memory_repository",
        "trace_store",
        "evolution_repository",
    )
    seen: set[int] = set()
    failures: list[Exception] = []
    for name in names:
        resource = getattr(app.state, name, None)
        if resource is None or id(resource) in seen:
            continue
        seen.add(id(resource))
        close = getattr(resource, "close", None)
        if not callable(close):
            continue
        try:
            result = close()
            if isawaitable(result):
                await result
        except Exception as error:  # Shutdown must attempt every independent resource.
            failures.append(error)
        finally:
            # A closed PyMongo async client retains monitor/topology objects.
            # Drop the application-owned reference while the event loop is
            # still alive so their finalizers cannot run after loop shutdown.
            setattr(app.state, name, None)
    if failures:
        raise RuntimeError("One or more application resources failed to close.") from failures[0]


def _error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details or {},
                "trace_id": request.state.trace_id,
            }
        },
    )


def create_app(
    *,
    settings: Settings | None = None,
    readiness_checker: ReadinessChecker = check_dependencies,
    user_store: UserStore | None = None,
    document_repository: DocumentStore | None = None,
    document_indexer: DocumentIndexer | None = None,
    chat_service: ChatService | None = None,
    department_executor: DepartmentAgentService | None = None,
    memory_repository: MemoryRepository | None = None,
    metrics_registry: MetricsRegistry | None = None,
    trace_store: TraceStore | None = None,
    evolution_repository: EvolutionRepository | None = None,
    evolution_service: EvolutionService | None = None,
    feedback_service: FeedbackService | None = None,
) -> FastAPI:
    app = FastAPI(
        title="政衡 Agent API",
        version="0.1.0",
        lifespan=_application_lifespan,
    )
    app.state.settings = settings or Settings()
    app.state.readiness_checker = readiness_checker
    app.state.user_store = user_store or MongoUserStore(app.state.settings)
    app.state.document_repository = document_repository or MongoDocumentRepository(
        app.state.settings
    )
    app.state.document_indexer = document_indexer or DocumentIndexer(
        repository=app.state.document_repository,
        sparse=OpenSearchBM25(
            app.state.settings,
            index_name=app.state.settings.opensearch_index,
        ),
        dense=MilvusDenseIndex(
            app.state.settings,
            collection_name=app.state.settings.milvus_collection,
        ),
        embedder=build_embedding_provider(app.state.settings),
    )
    app.state.memory_repository = memory_repository or MongoMemoryRepository(app.state.settings)
    app.state.metrics_registry = metrics_registry or MetricsRegistry()
    app.state.trace_store = trace_store or MongoTraceStore(app.state.settings)
    if app.state.settings.service_role == "department_agent":
        app.state.chat_service = chat_service
        app.state.department_executor = department_executor or build_department_agent_executor(
            app.state.settings,
            document_store=app.state.document_repository,
            trace_store=app.state.trace_store,
        )
    else:
        app.state.chat_service = chat_service or (
            build_multi_agent_chat_service(
                app.state.settings,
                trace_store=app.state.trace_store,
                memory_repository=app.state.memory_repository,
            )
            if (
                app.state.settings.multi_agent_enabled
                or app.state.settings.agent_execution_mode == "multi"
            )
            else build_chat_service(
                app.state.settings,
                document_store=app.state.document_repository,
                trace_store=app.state.trace_store,
            )
        )
        app.state.department_executor = None
    app.state.evolution_repository = evolution_repository or MongoEvolutionRepository(
        app.state.settings
    )
    replay_executor = (
        FrozenTraceReplayExecutor(
            harness=app.state.chat_service.harness,
            trace_store=app.state.trace_store,
        )
        if isinstance(app.state.chat_service, HarnessChatService)
        else None
    )
    app.state.evolution_service = evolution_service or EvolutionService(
        app.state.evolution_repository,
        replay_executor=replay_executor,
    )
    app.state.feedback_service = feedback_service or FeedbackService(
        app.state.evolution_repository,
        trace_store=app.state.trace_store,
    )

    @app.middleware("http")
    async def attach_trace_id(request: Request, call_next: Callable[..., Any]) -> Any:
        request.state.trace_id = request.headers.get("X-Trace-Id", str(uuid4()))
        response = await call_next(request)
        response.headers["X-Trace-Id"] = request.state.trace_id
        return response

    @app.exception_handler(ApiError)
    async def api_error_handler(request: Request, error: ApiError) -> JSONResponse:
        return _error_response(
            request,
            status_code=error.status_code,
            code=error.code,
            message=error.message,
            details=error.details,
        )

    @app.exception_handler(HTTPException)
    async def http_error_handler(request: Request, error: HTTPException) -> JSONResponse:
        return _error_response(
            request,
            status_code=error.status_code,
            code="HTTP_ERROR",
            message=str(error.detail),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        return _error_response(
            request,
            status_code=422,
            code="VALIDATION_ERROR",
            message="Request validation failed.",
            details={"errors": error.errors()},
        )

    app.include_router(health_router)
    if app.state.settings.service_role == "department_agent":
        app.include_router(department_agent_router)
    else:
        app.include_router(auth_router)
        app.include_router(documents_router)
        app.include_router(chat_router)
        app.include_router(memory_router)
        app.include_router(metrics_router)
        app.include_router(traces_router)
        app.include_router(feedback_router)
        app.include_router(evolution_router)
        app.include_router(agent_network_router)
    return app


app = create_app()

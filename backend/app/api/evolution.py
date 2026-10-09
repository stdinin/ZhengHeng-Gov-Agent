from datetime import UTC, datetime
from typing import Any, NoReturn, cast
from uuid import uuid4

from fastapi import APIRouter, Request, status
from pydantic import AliasChoices, BaseModel, Field, model_validator

from backend.app.api.errors import ApiError
from backend.app.evolution.models import (
    BadCase,
    BadCaseStatus,
    ExperimentRecord,
    StrategyAction,
    StrategyCandidate,
    StrategyScope,
    StrategyStatus,
    StrategyTrigger,
    StrategyType,
)
from backend.app.evolution.repository import EvolutionRepository
from backend.app.evolution.service import EvolutionService, EvolutionStateError
from backend.app.security.auth import User, decode_access_token
from backend.app.security.rbac import Role
from backend.app.storage.users import UserStore

router = APIRouter(tags=["evolution"])


class ReviewBadCaseRequest(BaseModel):
    status: BadCaseStatus = BadCaseStatus.REVIEWED


class ProposeStrategyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=256)
    version: int = Field(default=1, ge=1)
    strategy_type: StrategyType = Field(
        default=StrategyType.SKILL,
        validation_alias=AliasChoices("strategy_type", "type"),
        serialization_alias="type",
    )
    scope: StrategyScope = Field(default_factory=StrategyScope)
    trigger: StrategyTrigger = Field(default_factory=StrategyTrigger)
    actions: list[StrategyAction] = Field(min_length=1, max_length=16)

    @model_validator(mode="before")
    @classmethod
    def normalize_goal_action_shape(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        normalized = dict(value)
        actions = normalized.get("actions")
        if not isinstance(actions, list):
            return normalized
        normalized_actions: list[object] = []
        for action in actions:
            if not isinstance(action, dict):
                normalized_actions.append(action)
                continue
            action_value = dict(action)
            if "action_type" not in action_value and "type" in action_value:
                action_value["action_type"] = action_value["type"]
            normalized_actions.append(action_value)
        normalized["actions"] = normalized_actions
        return normalized


class ReplayStrategyRequest(BaseModel):
    source_trace_ids: list[str] = Field(min_length=1, max_length=100)


class ApproveGrayRequest(BaseModel):
    rollout_percent: int = Field(default=10, ge=1, le=100)


class RollbackRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=4_000)


def _repository(request: Request) -> EvolutionRepository:
    return cast(EvolutionRepository, request.app.state.evolution_repository)


def _service(request: Request) -> EvolutionService:
    return cast(EvolutionService, request.app.state.evolution_service)


def _user_store(request: Request) -> UserStore:
    return cast(UserStore, request.app.state.user_store)


async def _require_admin(request: Request) -> User:
    authorization = request.headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise ApiError(status_code=401, code="AUTH_REQUIRED", message="Bearer token is required.")
    try:
        user_id = decode_access_token(token, request.app.state.settings)
    except ValueError as error:
        raise ApiError(status_code=401, code="INVALID_TOKEN", message=str(error)) from error
    user = await _user_store(request).get_by_id(user_id)
    if user is None:
        raise ApiError(
            status_code=401,
            code="INVALID_TOKEN",
            message="Token user no longer exists.",
        )
    if user.role not in {Role.DEPT_ADMIN, Role.SUPER_ADMIN}:
        raise ApiError(
            status_code=403,
            code="ROLE_FORBIDDEN",
            message="Department administrator role is required for this operation.",
        )
    return user


def _raise_state_error(error: EvolutionStateError) -> NoReturn:
    message = str(error)
    if message.startswith(("Bad case not found:", "Strategy not found:")):
        raise ApiError(status_code=404, code="EVOLUTION_NOT_FOUND", message=message) from error
    raise ApiError(status_code=409, code="EVOLUTION_STATE_CONFLICT", message=message) from error


@router.get("/api/v1/badcases", response_model=list[BadCase])
async def list_badcases(request: Request, limit: int = 100) -> list[BadCase]:
    await _require_admin(request)
    if not 1 <= limit <= 200:
        raise ApiError(
            status_code=422,
            code="VALIDATION_ERROR",
            message="limit must be between 1 and 200.",
        )
    return await _repository(request).list_badcases(limit=limit)


@router.post("/api/v1/badcases/{badcase_id}/review", response_model=BadCase)
async def review_badcase(
    badcase_id: str, payload: ReviewBadCaseRequest, request: Request
) -> BadCase:
    await _require_admin(request)
    try:
        return await _service(request).review_badcase(badcase_id, status=payload.status)
    except EvolutionStateError as error:
        _raise_state_error(error)


@router.post(
    "/api/v1/badcases/{badcase_id}/propose-strategy",
    response_model=StrategyCandidate,
    status_code=status.HTTP_201_CREATED,
)
async def propose_strategy(
    badcase_id: str, payload: ProposeStrategyRequest, request: Request
) -> StrategyCandidate:
    admin = await _require_admin(request)
    now = datetime.now(UTC)
    candidate = StrategyCandidate(
        id=f"strategy_{uuid4().hex}",
        version=payload.version,
        status=StrategyStatus.CANDIDATE,
        strategy_type=payload.strategy_type,
        name=payload.name,
        created_by=admin.id,
        scope=payload.scope,
        trigger=payload.trigger,
        actions=payload.actions,
        created_at=now,
        updated_at=now,
    )
    try:
        return await _service(request).propose_strategy(badcase_id, candidate)
    except EvolutionStateError as error:
        _raise_state_error(error)


@router.get("/api/v1/strategies", response_model=list[StrategyCandidate])
async def list_strategies(request: Request, limit: int = 100) -> list[StrategyCandidate]:
    await _require_admin(request)
    if not 1 <= limit <= 200:
        raise ApiError(
            status_code=422,
            code="VALIDATION_ERROR",
            message="limit must be between 1 and 200.",
        )
    return await _repository(request).list_strategies(limit=limit)


@router.get("/api/v1/strategies/{strategy_id}", response_model=StrategyCandidate)
async def get_strategy(strategy_id: str, request: Request) -> StrategyCandidate:
    await _require_admin(request)
    strategy = await _repository(request).get_strategy(strategy_id)
    if strategy is None:
        raise ApiError(
            status_code=404,
            code="EVOLUTION_NOT_FOUND",
            message=f"Strategy not found: {strategy_id}",
        )
    return strategy


@router.post("/api/v1/strategies/{strategy_id}/replay", response_model=StrategyCandidate)
async def replay_strategy(
    strategy_id: str, payload: ReplayStrategyRequest, request: Request
) -> StrategyCandidate:
    await _require_admin(request)
    try:
        return await _service(request).replay_from_frozen_traces(
            strategy_id=strategy_id,
            source_trace_ids=payload.source_trace_ids,
        )
    except EvolutionStateError as error:
        _raise_state_error(error)


@router.post(
    "/api/v1/strategies/{strategy_id}/approve-gray", response_model=StrategyCandidate
)
async def approve_strategy_gray(
    strategy_id: str, payload: ApproveGrayRequest, request: Request
) -> StrategyCandidate:
    admin = await _require_admin(request)
    try:
        return await _service(request).approve_gray(
            strategy_id,
            rollout_percent=payload.rollout_percent,
            approved_by=admin.id,
        )
    except EvolutionStateError as error:
        _raise_state_error(error)


@router.post("/api/v1/strategies/{strategy_id}/promote", response_model=StrategyCandidate)
async def promote_strategy(strategy_id: str, request: Request) -> StrategyCandidate:
    await _require_admin(request)
    try:
        return await _service(request).promote(strategy_id)
    except EvolutionStateError as error:
        _raise_state_error(error)


@router.post("/api/v1/strategies/{strategy_id}/rollback", response_model=StrategyCandidate)
async def rollback_strategy(
    strategy_id: str, payload: RollbackRequest, request: Request
) -> StrategyCandidate:
    await _require_admin(request)
    try:
        return await _service(request).rollback(strategy_id, reason=payload.reason)
    except EvolutionStateError as error:
        _raise_state_error(error)


@router.get("/api/v1/experiments", response_model=list[ExperimentRecord])
async def list_experiments(
    request: Request, strategy_id: str | None = None, limit: int = 100
) -> list[ExperimentRecord]:
    await _require_admin(request)
    if not 1 <= limit <= 200:
        raise ApiError(
            status_code=422,
            code="VALIDATION_ERROR",
            message="limit must be between 1 and 200.",
        )
    return await _repository(request).list_experiments(strategy_id=strategy_id, limit=limit)

from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from backend.app.api.errors import ApiError
from backend.app.memory.models import MemoryItem, MemoryType
from backend.app.memory.repository import MemoryRepository
from backend.app.security.auth import decode_access_token
from backend.app.storage.users import UserStore

router = APIRouter(prefix="/api/v1/memory", tags=["memory"])


class CreateSemanticMemoryRequest(BaseModel):
    content: str = Field(min_length=1, max_length=8_000)
    consented: bool


def _repository(request: Request) -> MemoryRepository:
    return cast(MemoryRepository, request.app.state.memory_repository)


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


@router.get("/semantic", response_model=list[MemoryItem])
async def list_semantic_memory(request: Request) -> list[MemoryItem]:
    user_id = await _authenticate(request)
    return await _repository(request).list_for_user(user_id, MemoryType.USER_SEMANTIC)


@router.post("/semantic", response_model=MemoryItem, status_code=201)
async def create_semantic_memory(
    payload: CreateSemanticMemoryRequest, request: Request
) -> MemoryItem:
    if not payload.consented:
        raise ApiError(
            status_code=422,
            code="MEMORY_CONSENT_REQUIRED",
            message="User semantic memory requires explicit consent.",
        )
    user_id = await _authenticate(request)
    now = datetime.now(UTC)
    item = MemoryItem(
        id=str(uuid4()),
        memory_type=MemoryType.USER_SEMANTIC,
        user_id=user_id,
        content=payload.content,
        confidence=1.0,
        consented=True,
        created_at=now,
        updated_at=now,
    )
    await _repository(request).upsert(item)
    return item


@router.delete("/semantic/{memory_id}", status_code=204)
async def delete_semantic_memory(memory_id: str, request: Request) -> Response:
    user_id = await _authenticate(request)
    if not await _repository(request).delete_user_semantic(user_id, memory_id):
        raise ApiError(
            status_code=404,
            code="MEMORY_NOT_FOUND",
            message=f"User semantic memory not found: {memory_id}",
        )
    return Response(status_code=204)
